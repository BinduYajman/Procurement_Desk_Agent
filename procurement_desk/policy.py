"""The decision procedure (policies/decision-procedure.md) as an ordered list of explicit rules.

Rules run in playbook order and the first one that fires wins. Each rule has a stable id, cites the
playbook clause it implements, and leaves a trail entry, so a reviewer can see exactly which rules were
checked and why the thread stopped where it did.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Optional, Protocol

from .domain import Action, Decision, Reason, ThreadInput
from .extraction import MissingInfo
from .normalization import NormalizedPrice, fmt
from .playbook import Category, ResolvedValues, Supplier
from .security import Finding


def round_half_up(value: Fraction) -> int:
    """Nearest rupee, x.5 rounds up (decision-procedure step 5)."""
    return int((Decimal(value.numerator) / Decimal(value.denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_limit(round_no: int, rounds: int, target: Fraction, walkaway: Fraction, beta: int) -> Fraction:
    """L(r) = target + (walkaway - target) * ((r-1)/(R-1))**beta, exactly (concession-schedule.md)."""
    return target + (walkaway - target) * (Fraction(round_no - 1, rounds - 1) ** beta)


@dataclass
class PolicyContext:
    thread: ThreadInput
    category: Category
    supplier: Supplier
    values: ResolvedValues
    normalized: Optional[NormalizedPrice]
    missing: Optional[MissingInfo]
    injection: list[Finding]
    banned_terms: list[Finding]
    level: Optional[Fraction] = None          # L(r), filled in by the price rule


@dataclass(frozen=True)
class RuleTrail:
    rule_id: str
    title: str
    source: str
    fired: bool
    detail: str


class PolicyRule(Protocol):
    id: str
    title: str
    source: str

    def evaluate(self, ctx: PolicyContext) -> Optional[tuple[Decision, str]]: ...


def _escalate(ctx: PolicyContext, reason: Reason) -> Decision:
    return Decision(ctx.thread.thread_id, Action.ESCALATE, reason)


class MissingInformation:
    id, title, source = "R1", "Missing information", "decision-procedure.md step 1; units-and-currency.md"

    def evaluate(self, ctx: PolicyContext):
        if ctx.normalized is None or ctx.normalized.price is None:
            problem = ctx.missing or MissingInfo.NO_PRICE_FOUND
            return _escalate(ctx, Reason.MISSING_INFO), problem.value
        return None


class BlacklistedSupplier:
    id, title, source = "R2", "Blacklisted supplier", "decision-procedure.md step 2; suppliers/"

    def evaluate(self, ctx: PolicyContext):
        if ctx.supplier.blacklisted:
            return Decision(ctx.thread.thread_id, Action.REJECT, Reason.BLACKLISTED_SUPPLIER), f"{ctx.supplier.name} is blacklisted"
        return None


class PromptInjection:
    id, title, source = "R3", "Prompt injection anywhere in the thread", "decision-procedure.md step 3; security-policy.md"

    def evaluate(self, ctx: PolicyContext):
        if ctx.injection:
            first = ctx.injection[0]
            return _escalate(ctx, Reason.PROMPT_INJECTION), f"{first.rule_id} {first.title}: {first.evidence!r}"
        return None


class BannedTerm:
    id, title, source = "R4", "Banned contract term in the latest message", "decision-procedure.md step 4; banned-terms.md"

    def evaluate(self, ctx: PolicyContext):
        if ctx.banned_terms:
            first = ctx.banned_terms[0]
            return _escalate(ctx, Reason.BANNED_TERM), f"{first.rule_id} {first.title}: {first.evidence!r}"
        return None


class PriceDecision:
    id, title, source = "R5", "Price against the concession schedule", "decision-procedure.md step 5; concession-schedule.md"

    def evaluate(self, ctx: PolicyContext):
        assert ctx.normalized is not None and ctx.normalized.price is not None
        price, cat, thread = ctx.normalized.price, ctx.category, ctx.thread
        target, walk = ctx.values.target, ctx.values.walkaway
        if ctx.supplier.probation:                       # step 7: no concessions, L(r) = target every round
            level = target
        else:
            level = round_limit(min(thread.round, cat.rounds), cat.rounds, target, walk, cat.beta)
        ctx.level = level
        detail = f"p = {fmt(price)} vs L({thread.round}) = {fmt(level)}"
        if price <= level:
            return None
        if thread.round >= cat.rounds:
            return Decision(thread.thread_id, Action.REJECT, Reason.ABOVE_WALKAWAY), detail + " on the final round"
        return Decision(thread.thread_id, Action.COUNTER, Reason.COUNTER_OFFER, round_half_up(level)), detail + ", counter at L(r)"


class ApprovalLimit:
    id, title, source = "R6", "Approval limit", "decision-procedure.md step 6; approval-limits.md"

    def evaluate(self, ctx: PolicyContext):
        assert ctx.normalized is not None and ctx.normalized.price is not None
        value = ctx.normalized.price * ctx.thread.quantity
        detail = f"p x quantity = {fmt(value)} vs limit {fmt(ctx.values.approval_limit)}"
        if value > ctx.values.approval_limit:
            return _escalate(ctx, Reason.OVER_APPROVAL_LIMIT), detail
        return Decision(ctx.thread.thread_id, Action.ACCEPT, Reason.ACCEPTABLE_PRICE), detail


DEFAULT_RULES: tuple[PolicyRule, ...] = (
    MissingInformation(), BlacklistedSupplier(), PromptInjection(), BannedTerm(), PriceDecision(), ApprovalLimit())


@dataclass
class PolicyEngine:
    rules: tuple[PolicyRule, ...] = field(default_factory=lambda: DEFAULT_RULES)

    def run(self, ctx: PolicyContext) -> tuple[Decision, str, list[RuleTrail]]:
        trail: list[RuleTrail] = []
        for rule in self.rules:
            outcome = rule.evaluate(ctx)
            if outcome is None:
                trail.append(RuleTrail(rule.id, rule.title, rule.source, False, "passed"))
                continue
            decision, detail = outcome
            trail.append(RuleTrail(rule.id, rule.title, rule.source, True, detail))
            return decision, rule.id, trail
        raise RuntimeError("Policy engine ended without a decision; the final rule must always decide")
