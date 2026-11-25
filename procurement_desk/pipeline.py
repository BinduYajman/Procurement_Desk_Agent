"""The decision pipeline: parse -> extract -> normalize -> screen -> decide -> audit record."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Iterable, Optional

from . import __version__
from .contract_terms import BannedTermDetector
from .domain import Action, Decision, Reason, ThreadInput
from .extraction import ExtractionResult, MissingInfo, OfferExtractor, RuleBasedExtractor
from .normalization import NormalizedPrice, TraceStep, fmt, normalize
from .playbook import Playbook, ResolvedValues
from .policy import PolicyContext, PolicyEngine, RuleTrail
from .security import Finding, PromptInjectionDetector
from .text import parse_thread

log = logging.getLogger("procurement_desk")

# Only Legal is named by the playbook (banned-terms.md). The other owners are deployment configuration.
DEFAULT_ESCALATION_OWNERS = {
    Reason.BANNED_TERM: "Legal", Reason.PROMPT_INJECTION: "Security", Reason.MISSING_INFO: "Buyer",
    Reason.OVER_APPROVAL_LIMIT: "Approver",
}


def _decimal(value: Optional[Fraction], places: int = 6) -> Optional[str]:
    return None if value is None else fmt(value, places)


@dataclass
class DecisionRecord:
    """A decision plus everything needed to audit, explain and reproduce it."""
    thread: ThreadInput
    decision: Decision
    fired_rule: str
    trail: tuple[RuleTrail, ...] = ()
    price_steps: tuple[TraceStep, ...] = ()
    normalized_price: Optional[Fraction] = None
    acceptable_price: Optional[Fraction] = None
    values: Optional[ResolvedValues] = None
    findings: tuple[Finding, ...] = ()
    flags: tuple[str, ...] = ()
    error: Optional[str] = None
    playbook_fingerprint: str = ""
    engine_version: str = __version__
    extractor: str = ""

    @property
    def label(self) -> str:
        return self.decision.label

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_schema": 1, "thread_id": self.thread.thread_id, "label": self.label,
            "action": self.decision.action.value, "reason": self.decision.reason.value,
            "counter_price": self.decision.counter_price, "fired_rule": self.fired_rule,
            "normalized_price": _decimal(self.normalized_price),
            "normalized_price_exact": None if self.normalized_price is None else str(self.normalized_price),
            "acceptable_price": _decimal(self.acceptable_price),
            "deal_value": None if self.normalized_price is None else _decimal(self.normalized_price * self.thread.quantity, 2),
            "numbers_in_force": None if self.values is None else {
                "target": str(self.values.target), "walkaway": str(self.values.walkaway),
                "approval_limit": str(self.values.approval_limit), "provenance": list(self.values.provenance)},
            "price_trace": [s.render() for s in self.price_steps],
            "rule_trail": [{"rule": t.rule_id, "title": t.title, "source": t.source, "fired": t.fired, "detail": t.detail}
                           for t in self.trail],
            "findings": [{"rule": f.rule_id, "title": f.title, "evidence": f.evidence} for f in self.findings],
            "flags": list(self.flags), "error": self.error, "extractor": self.extractor,
            "playbook_fingerprint": self.playbook_fingerprint, "engine_version": self.engine_version,
        }

    def escalation_ticket(self) -> Optional[dict[str, Any]]:
        """A review ticket for a human, for every ESCALATE decision."""
        if self.decision.action is not Action.ESCALATE:
            return None
        t = self.thread
        return {
            "thread_id": t.thread_id, "reason": self.decision.reason.value,
            "suggested_owner": DEFAULT_ESCALATION_OWNERS.get(self.decision.reason, "Buyer"),
            "supplier": t.supplier, "category": t.category, "quantity": t.quantity, "round": t.round,
            "why": next((x.detail for x in self.trail if x.fired), self.error or ""),
            "deal_value": None if self.normalized_price is None else _decimal(self.normalized_price * t.quantity, 2),
            "evidence": [f.evidence for f in self.findings], "flags": list(self.flags),
        }

    def explain(self) -> str:
        t, lines = self.thread, []
        lines.append(f"{t.thread_id}  {t.supplier} / {t.category}  qty {t.quantity}  round {t.round}  date {t.date}")
        lines.append(f"DECISION  {self.label}   (rule {self.fired_rule})")
        if self.values:
            lines.append(f"Numbers in force: target {fmt(self.values.target)}, walk-away {fmt(self.values.walkaway)}, "
                         f"approval limit {fmt(self.values.approval_limit)}")
            lines.extend(f"    - {why}" for why in self.values.provenance)
        if self.price_steps:
            lines.append("Price normalization:")
            lines.extend(f"    {s.render()}" for s in self.price_steps)
        lines.append("Rules checked, in order:")
        for x in self.trail:
            lines.append(f"    {x.rule_id} {'FIRED ' if x.fired else 'passed'} {x.title} -- {x.detail}")
        if self.flags:
            lines.append("Flags: " + ", ".join(self.flags))
        if self.error:
            lines.append(f"Error: {self.error}")
        return "\n".join(lines)


class DecisionPipeline:
    """Stateless apart from the (immutable) playbook, so it can be shared across threads and processes."""

    def __init__(self, playbook: Playbook, extractor: Optional[OfferExtractor] = None,
                 injection: Optional[PromptInjectionDetector] = None, terms: Optional[BannedTermDetector] = None,
                 engine: Optional[PolicyEngine] = None, strict: bool = False) -> None:
        self.playbook = playbook
        self.extractor: OfferExtractor = extractor or RuleBasedExtractor()
        self.injection = injection or PromptInjectionDetector()
        self.terms = terms or BannedTermDetector()
        self.engine = engine or PolicyEngine()
        self.strict = strict

    # ------------------------------------------------------------------ public API
    def decide(self, thread: ThreadInput) -> DecisionRecord:
        try:
            return self._decide(thread)
        except Exception as error:                      # noqa: BLE001 - fail safe: a human reviews it
            if self.strict:
                raise
            log.exception("thread %s could not be processed", thread.thread_id)
            return self._safe_escalation(thread, f"{type(error).__name__}: {error}")

    def decide_many(self, threads: Iterable[ThreadInput]) -> list[DecisionRecord]:
        return [self.decide(t) for t in threads]

    def invalid_input(self, thread_id: str, message: str) -> DecisionRecord:
        """A row that could not even be parsed: escalate rather than guess."""
        thread = ThreadInput(thread_id, "1970-01-01", "", "", 1, 1, None, "")
        return self._safe_escalation(thread, f"InvalidInput: {message}", "INVALID_INPUT")

    # ------------------------------------------------------------------ internals
    def _safe_escalation(self, thread: ThreadInput, error: str, flag: str = "INTERNAL_ERROR") -> DecisionRecord:
        return DecisionRecord(thread, Decision(thread.thread_id, Action.ESCALATE, Reason.MISSING_INFO), "SAFE-FAIL",
                              flags=(flag,), error=error, playbook_fingerprint=self.playbook.fingerprint,
                              extractor=self.extractor.name)

    def _decide(self, thread: ThreadInput) -> DecisionRecord:
        pb = self.playbook
        category = pb.categories.get(thread.category)
        if category is None:
            raise KeyError(f"unknown category {thread.category!r}")
        supplier = pb.supplier_for(thread.supplier)
        parsed = parse_thread(thread.supplier_message)

        injection = self.injection.scan(thread.supplier_message)            # whole thread
        banned = self.terms.scan(parsed.latest.body)                         # latest message only
        extraction: ExtractionResult = self.extractor.extract(
            thread, parsed, lambda line: bool(self.injection.scan_line(line)))

        previous = None
        for candidate in extraction.previous_candidates:
            if normalize(candidate, thread, pb).usable:
                previous = candidate
                break
        normalized: Optional[NormalizedPrice] = None
        missing: Optional[MissingInfo] = None
        for candidate in extraction.candidates:
            attempt = normalize(candidate, thread, pb, previous)
            if attempt.usable:
                normalized, missing = attempt, None
                break
            missing = attempt.problem          # keep looking: a later candidate line may be usable
        if not extraction.candidates:
            missing = MissingInfo.NO_PRICE_FOUND

        values = pb.values_for(thread.category, thread.supplier, thread.date)
        ctx = PolicyContext(thread, category, supplier, values, normalized, missing, injection, banned)
        decision, fired, trail = self.engine.run(ctx)

        flags = list(extraction.flags)
        if not supplier.known:
            flags.append("UNKNOWN_SUPPLIER")
        if thread.round > category.rounds:
            flags.append("ROUND_ABOVE_FINAL_ROUND")
        if decision.counter_price is not None and thread.our_last_counter:
            try:
                if decision.counter_price < int(Fraction(thread.our_last_counter.replace(",", ""))):
                    flags.append("COUNTER_BELOW_OUR_LAST_COUNTER")
            except (ValueError, ZeroDivisionError):
                flags.append("UNPARSEABLE_LAST_COUNTER")
        findings: tuple[Finding, ...] = tuple(injection) if fired == "R3" else tuple(banned) if fired == "R4" else ()
        return DecisionRecord(
            thread, decision, fired, tuple(trail), normalized.steps if normalized else (),
            normalized.price if normalized else None, ctx.level, values, findings, tuple(flags), None,
            pb.fingerprint, __version__, extraction.extractor)
