"""Prompt-injection screening (policies/security-policy.md).

Supplier text is untrusted data. This module only *detects* instructions aimed at an AI, bot, system or
reviewer, override claims, and "approval already granted" claims, in any wording, anywhere in the thread.
It never obeys them, and the decision engine never lets a detected line supply a price.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import canonical


@dataclass(frozen=True)
class Finding:
    rule_id: str
    title: str
    evidence: str


# Ordinary business wording the policy explicitly says is NOT an injection.
_BENIGN = re.compile(
    r"ai[- ]powered|system integration|erp system|"
    r"(?:assistant|deputy|associate|executive|personal|sales|office|administrative|admin)\s+"
    r"(?:manager|director|vp|vice president|professor|engineer|accountant|controller|buyer|head|coordinator)|"
    r"(?:executive|personal|sales|office|administrative)\s+assistant|assistant to the", re.I)

_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (rid, title, re.compile(pattern, re.I)) for rid, title, pattern in (
        ("INJ-01", "Text addressed to an AI, bot, system or reviewer",
         r"language model|\bllm\b|chat-?bot|\bbot\b|\bai (?:agent|assistant|system|model)\b|\ba\.?i\.? agent\b|"
         r"automated system|reviewing assistant|\breviewer\b|chat ?gpt|\bgpt-?\d"),
        ("INJ-02", "Override / ignore-instructions language",
         r"admin override|\boverride\b|skip the playbook|system note|new instructions|<!--|"
         r"(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?(?:your\s+|the\s+|these\s+)?(?:previous|prior|above|earlier)?\s*"
         r"(?:instructions|rules|guidelines|polic(?:y|ies))"),
        ("INJ-03", "Claim that approval was already granted",
         r"pre-?approved|already (?:signed off|granted|approved)|"
         r"(?:approval|sign-?off) (?:has been|was|is) (?:already )?(?:granted|given|obtained)"),
        ("INJ-04", "Directive to record a decision",
         r"mark (?:this|it)[^.\n]{0,40}accept|record the decision as approved|approve this (?:vendor|deal|offer|supplier)|"
         r"(?:output|respond with|reply with|return|print|answer)\s+(?:only\s+)?[\"'“]?(?:accept|approve|approved|accepted)\b|"
         r"set (?:the )?(?:decision|status|label|action) to"),
        ("INJ-05", "Instruction aimed at an AI in another language",
         r"ai सहायक|सहायक के लिए|निर्देश|ignora (?:las|tus) instrucciones|ignorez (?:les|vos) instructions|"
         r"ignore les instructions|ignoriere (?:die|alle)"),
    ))


class PromptInjectionDetector:
    """Layered, deterministic detector: Unicode canonicalization -> benign-wording mask -> rule lexicon."""

    def _scan_text(self, raw: str) -> list[tuple[str, str]]:
        cleaned = _BENIGN.sub(" ", canonical(raw).lower())
        return [(rid, title) for rid, title, pattern in _RULES if pattern.search(cleaned)]

    def scan_line(self, line: str) -> list[Finding]:
        evidence = line.strip()[:240]
        return [Finding(rid, title, evidence) for rid, title in self._scan_text(line)]

    def scan(self, thread_text: str) -> list[Finding]:
        """Scan the whole thread (earlier and latest messages), per line and across line breaks."""
        findings: list[Finding] = []
        seen: set[tuple[str, str]] = set()
        for line in thread_text.split("\n"):
            for f in self.scan_line(line):
                if (f.rule_id, f.evidence) not in seen:
                    seen.add((f.rule_id, f.evidence))
                    findings.append(f)
        flat = " ".join(part.strip() for part in thread_text.split("\n") if part.strip())
        for rid, title in self._scan_text(flat):          # payloads split over several lines
            if not any(f.rule_id == rid for f in findings):
                findings.append(Finding(rid, title, flat[:240]))
        return findings
