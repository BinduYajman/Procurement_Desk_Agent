"""Offer extraction: supplier text -> structured evidence of *what the supplier said*.

Extraction never does arithmetic and never decides anything. It records the quoted amounts and the
conditions attached to them (range, tier, discount, unit, period, GST) with the verbatim source line, so
that normalization can be audited and so that any other extractor can be plugged in behind the same
interface (see ``ExtractorChain``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Callable, Optional, Protocol, Sequence

from .domain import Money, ThreadInput
from .numbers import NUMBER_WORD, words_to_number
from .text import ParsedThread, parse_thread

ISO_CODES = frozenset(
    "AED AUD BDT BRL CAD CHF CNY CZK DKK EUR GBP HKD IDR ILS INR JPY KRW LKR MXN MYR NOK NPR NZD PHP PKR PLN QAR "
    "RUB SEK SGD THB TWD USD ZAR".split())
_SYMBOLS = {"₹": "INR", "RS": "INR", "RS.": "INR", "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
_CURRENCY = r"(?:₹|(?<![A-Za-z])Rs\.?|\$|€|£|¥|(?<![A-Za-z])(?:" + "|".join(sorted(ISO_CODES)) + r")(?![A-Za-z]))"
_AMOUNT = re.compile(
    r"(?P<cur>" + _CURRENCY + r")\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<mult>lakhs?|crores?|k\b)?"
    r"|(?P<words>(?:" + NUMBER_WORD + r"[\s\-]*(?:and\s+)?)+)\s+rupees", re.I)

# Phrases that introduce the supplier's *current* offer, and (for earlier messages) its earlier quote.
_CURRENT_CUE = re.compile(
    r"we can (?:do|offer)|we are pleased to quote|the best we can offer|"
    r"our (?:quote|final price|revised offer) is", re.I)
_PRIOR_CUE = re.compile(_CURRENT_CUE.pattern + r"|our (?:earlier |previous |prior )?quote (?:is|was)", re.I)
_CORRECTION = re.compile(r"^\s*CORRECTION", re.I)


class MissingInfo(str, Enum):
    NO_PRICE_FOUND = "no usable price in the supplier's latest offer"
    UNSUPPORTED_CURRENCY = "currency not listed in units-and-currency.md"
    MISSING_BILLING_PERIOD = "subscription price with no billing period"
    NO_PREVIOUS_QUOTE = "discount on a previous quote, but no earlier supplier quote in the thread"


@dataclass(frozen=True)
class OfferEvidence:
    """What the supplier's offer line says, without any arithmetic applied."""
    source_line: str
    amounts: tuple[Money, ...] = ()
    is_correction: bool = False
    is_range: bool = False
    tier_max_quantity: Optional[int] = None            # "X for orders of up to N, Y for larger orders"
    volume_discount: Optional[tuple[Fraction, int]] = None   # (percent, minimum quantity)
    free_units: Optional[tuple[int, int]] = None       # (free, per this many paid)
    list_discount_percent: Optional[Fraction] = None   # "D% off our list price of X"
    total_units: Optional[int] = None                  # "X in total for all N units"
    discount_on_previous_percent: Optional[Fraction] = None
    unit_divisor: int = 1                              # per dozen = 12; per pack of N; per N units
    unit_word: Optional[str] = None                    # word after "per" (category pack / sub-unit lookup)
    billing_period: Optional[str] = None               # "year" | "month"
    gst_inclusive: bool = False


@dataclass(frozen=True)
class ExtractionResult:
    candidates: tuple[OfferEvidence, ...] = ()          # current-offer lines, in message order
    previous_candidates: tuple[OfferEvidence, ...] = ()  # supplier's earlier quotes, newest first
    flags: tuple[str, ...] = ()
    extractor: str = "rules"


class OfferExtractor(Protocol):
    name: str

    def extract(self, thread: ThreadInput, parsed: ParsedThread,
                is_untrusted: Callable[[str], bool]) -> ExtractionResult: ...


# --------------------------------------------------------------------------- parsing helpers
def parse_amounts(text: str) -> list[Money]:
    """Every money amount in a piece of text, in order. Handles ₹/Rs/ISO codes, lakh/crore/k and words."""
    found: list[Money] = []
    for m in _AMOUNT.finditer(text):
        if m.group("words"):
            value = words_to_number(m.group("words").strip())
            if value is not None:
                found.append(Money("INR", value, m.group(0)))
            continue
        raw_currency = m.group("cur")
        code = _SYMBOLS.get(raw_currency.upper().rstrip("."), _SYMBOLS.get(raw_currency)) or raw_currency.upper()
        value = Fraction(m.group("num").replace(",", ""))
        mult = (m.group("mult") or "").lower()
        if mult.startswith("lakh"):
            value *= 100_000
        elif mult.startswith("crore"):
            value *= 10_000_000
        elif mult == "k":
            value *= 1_000
        found.append(Money(code, value, m.group(0)))
    return found


def _period(low: str) -> Optional[str]:
    if re.search(r"per (?:year|annum)\b|/ ?(?:year|yr)\b|\b(?:yearly|annually|annual)\b|\b(?:a|each) year\b|\bp\.a\.", low):
        return "year"
    if re.search(r"per month\b|/ ?(?:month|mo)\b|\bmonthly\b|\b(?:a|each) month\b", low):
        return "month"
    return None


def evidence_from_segment(segment: str, source_line: str, correction: bool = False) -> Optional[OfferEvidence]:
    low = segment.lower()
    previous = re.search(
        r"(\d+(?:\.\d+)?)\s*%\s*(?:further\s+)?off\s+(?:of\s+)?(?:our|the)\s+(?:previous|earlier|prior|last)\s+"
        r"(?:quote|offer|price)", low)
    amounts = tuple(parse_amounts(segment))
    if not amounts and not previous:
        return None
    tier = re.search(r"up to\s+(\d+)", low)
    volume = re.search(r"further\s+(\d+(?:\.\d+)?)\s*%\s*off for orders of\s+(\d+)", low)
    free = re.search(r"plus\s+(\d+)\s+free\s+\w+\s+for every\s+(\d+)", low)
    listing = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:discount\s+)?(?:on|off)\s+(?:of\s+)?(?:our\s+)?list price", low)
    total = re.search(r"in total for (?:all\s+)?(\d+)", low)
    is_range = bool(re.search(r"\bbetween\b|\brange\b|\branging\b", low)) and len(amounts) >= 2 and not tier
    divisor, unit_word = 1, None
    if re.search(r"per dozen|a dozen|/ ?dozen", low):
        divisor = 12
    else:
        pack = re.search(r"per pack of\s+(\d+)", low) or re.search(r"per\s+(\d+)\s+[a-z]", low)
        if pack:
            divisor = int(pack.group(1))
        else:
            word = re.search(r"per\s+([a-z]+)\b", low)
            unit_word = word.group(1) if word else None
    return OfferEvidence(
        source_line=source_line.strip(), amounts=amounts, is_correction=correction, is_range=is_range,
        tier_max_quantity=int(tier.group(1)) if tier else None,
        volume_discount=(Fraction(volume.group(1)), int(volume.group(2))) if volume else None,
        free_units=(int(free.group(1)), int(free.group(2))) if free else None,
        list_discount_percent=Fraction(listing.group(1)) if listing else None,
        total_units=int(total.group(1)) if total else None,
        discount_on_previous_percent=Fraction(previous.group(1)) if previous else None,
        unit_divisor=divisor, unit_word=unit_word, billing_period=_period(low),
        gst_inclusive=bool(re.search(
            r"incl(?:usive|uding|\.)?\s+(?:of\s+)?gst|gst\s+(?:is\s+)?(?:included|inclusive)", low)))


def _line_evidence(line: str, cue: re.Pattern[str]) -> Optional[OfferEvidence]:
    if _CORRECTION.match(line):                         # a correction replaces the price it corrects
        m = re.search(r"should read(.*?)(?:,\s*not\b|$)", line, re.I)
        return evidence_from_segment(m.group(1) if m else line, line, correction=True)
    m = cue.search(line)
    return evidence_from_segment(line[m.start():], line) if m else None


_PAYMENT_OR_VALIDITY = re.compile(r"advance|upfront|net-\d|valid|warranty|delivery within|invoice", re.I)


class RuleBasedExtractor:
    """Deterministic extractor for the supplier-message phrasings seen in Acme's threads."""
    name = "rules"

    def extract(self, thread: ThreadInput, parsed: ParsedThread,
                is_untrusted: Callable[[str], bool]) -> ExtractionResult:
        flags: list[str] = []
        candidates: list[OfferEvidence] = []
        lines = parsed.latest.body.split("\n")
        for line in lines:
            if not line.strip() or is_untrusted(line):      # injected text can never supply a price
                continue
            evidence = _line_evidence(line, _CURRENT_CUE)
            if evidence:
                candidates.append(evidence)
        if len(candidates) > 1:
            flags.append("MULTIPLE_PRICE_LINES")
        if not candidates and any(
                parse_amounts(l) and not _PAYMENT_OR_VALIDITY.search(l) and not is_untrusted(l) for l in lines):
            flags.append("UNRECOGNISED_PRICE_WORDING")      # an amount is present that no rule understood
        previous: list[OfferEvidence] = []
        for message in reversed(parsed.earlier_supplier_messages):
            for line in message.body.split("\n"):
                if line.strip() and not is_untrusted(line):
                    evidence = _line_evidence(line, _PRIOR_CUE)
                    if evidence:
                        previous.append(evidence)
        return ExtractionResult(tuple(candidates), tuple(previous), tuple(flags), self.name)


class ExtractorChain:
    """Try extractors in order; the first that finds a candidate offer wins.

    Evidence from any extractor other than the first must quote the message verbatim, so a probabilistic
    extractor (e.g. an LLM) can only *point at* text that is really in the thread. Its evidence then goes
    through exactly the same deterministic normalization and policy as everything else.
    """
    name = "chain"

    def __init__(self, extractors: Sequence[OfferExtractor]) -> None:
        if not extractors:
            raise ValueError("ExtractorChain needs at least one extractor")
        self.extractors = list(extractors)

    def extract(self, thread: ThreadInput, parsed: ParsedThread,
                is_untrusted: Callable[[str], bool]) -> ExtractionResult:
        result = ExtractionResult()
        for index, extractor in enumerate(self.extractors):
            result = extractor.extract(thread, parsed, is_untrusted)
            if index > 0:
                verbatim = tuple(c for c in result.candidates if c.source_line and c.source_line in parsed.full_text)
                if len(verbatim) != len(result.candidates):
                    result = ExtractionResult((), result.previous_candidates, result.flags + ("FALLBACK_EVIDENCE_REJECTED",),
                                              result.extractor)
            if result.candidates:
                return result
        return result
