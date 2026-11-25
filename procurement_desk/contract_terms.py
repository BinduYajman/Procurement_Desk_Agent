"""Banned contract terms in the supplier's latest message (policies/banned-terms.md)."""
from __future__ import annotations

import re
from fractions import Fraction

from .numbers import NUMBER_WORD, SPOKEN_SHARES, words_to_number
from .security import Finding
from .text import canonical

_AUTO_RENEWAL = re.compile(
    r"auto[- ]?renew|automatic(?:ally)?\s+renew|renews?\s+automatically|renew(?:s|al)? on its own|"
    r"from year to year|year[- ]to[- ]year|evergreen|continues? (?:each|every) year|rolls? over automatically", re.I)
_AUTO_RENEWAL_OK = re.compile(
    r"\b(?:no|not|never|without)\b[^.\n]{0,45}(?:auto[- ]?renew|automatic renewal|renewal)|"
    r"renewal only (?:by mutual agreement|if both parties sign again)", re.I)
_EXCLUSIVITY = re.compile(
    r"exclusiv|sole (?:supplier|source)|only from (?:us|this supplier|our company)|"
    r"(?:buy|purchase|source)[^.\n]{0,40}only from", re.I)
_EXCLUSIVITY_OK = re.compile(
    r"\b(?:not|no|never|without)\b[^.\n]{0,45}exclusiv|non[- ]exclusive|exclusive of\b", re.I)
_LIABILITY = re.compile(
    r"liab\w*[^.\n]{0,100}(?:unlimited|without (?:any )?(?:limit|cap)|no (?:limit|cap))|"
    r"unlimited[^.\n]{0,60}liab", re.I)
_LIABILITY_PARTY = re.compile(r"\b(?:acme|your|buyer|customer)\b", re.I)
_ADVANCE = re.compile(r"in advance|advance|upfront|up[- ]front|prepay(?:ment)?", re.I)
_PERCENT = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?:%|percent|per ?cent)|"
    r"(?P<words>(?:" + NUMBER_WORD + r"[\s\-]*)+)\s*(?:%|percent|per ?cent)|"
    r"(?P<spoken>" + "|".join(sorted((re.escape(k) for k in SPOKEN_SHARES), key=len, reverse=True)) + r")\b", re.I)
_CLAUSE_SPLIT = re.compile(r"(?<!\d)\.(?!\d)|[\n;]")

ADVANCE_LIMIT_PERCENT = Fraction(30)


def advance_share(clause: str) -> Fraction | None:
    """The advance/upfront share (percent) stated in a clause, in numbers or words; None if absent."""
    keywords = [m.span() for m in _ADVANCE.finditer(clause)]
    if not keywords:
        return None
    candidates: list[tuple[tuple[int, int], Fraction]] = []
    for m in _PERCENT.finditer(clause):
        if m.group("num"):
            value: Fraction | None = Fraction(m.group("num"))
        elif m.group("words"):
            value = words_to_number(m.group("words").strip())
        else:
            value = SPOKEN_SHARES.get(m.group("spoken").lower())
        if value is not None:
            candidates.append((m.span(), value))
    if not candidates:
        return None

    def gap(a: tuple[int, int], b: tuple[int, int]) -> int:
        return b[0] - a[1] if a[1] <= b[0] else a[0] - b[1]

    # The percentage closest to each advance keyword is the advance share ("20% advance, 80% on delivery").
    return max(min(candidates, key=lambda c: gap(c[0], kw))[1] for kw in keywords)


class BannedTermDetector:
    def scan(self, latest_message: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in _CLAUSE_SPLIT.split(latest_message):
            clause = canonical(raw).strip()
            if not clause:
                continue
            evidence = raw.strip()[:240]
            if _AUTO_RENEWAL.search(clause) and not _AUTO_RENEWAL_OK.search(clause):
                findings.append(Finding("BT-01", "Automatic renewal", evidence))
            share = advance_share(clause)
            if share is not None and share > ADVANCE_LIMIT_PERCENT:
                findings.append(Finding("BT-02", f"Advance payment above {ADVANCE_LIMIT_PERCENT}%", evidence))
            if _LIABILITY.search(clause) and _LIABILITY_PARTY.search(clause):
                findings.append(Finding("BT-03", "Unlimited liability for Acme", evidence))
            if _EXCLUSIVITY.search(clause) and not _EXCLUSIVITY_OK.search(clause):
                findings.append(Finding("BT-04", "Exclusivity", evidence))
        return findings
