"""Normalization: structured offer evidence -> INR, excluding GST, per the category's normalized unit.

Pure, exact (``Fraction``) arithmetic implementing policies/units-and-currency.md and the precedents.
Every step is recorded so any decision can be explained line by line.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Optional

from .domain import ThreadInput
from .extraction import MissingInfo, OfferEvidence
from .playbook import Playbook


def fmt(value: Fraction, places: int = 2) -> str:
    """Human-readable rupee/number formatting for traces (exact values are kept elsewhere)."""
    quantum = Decimal(1).scaleb(-places)
    text = f"{(Decimal(value.numerator) / Decimal(value.denominator)).quantize(quantum):,}"
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True)
class TraceStep:
    description: str
    value: Optional[Fraction] = None

    def render(self) -> str:
        return self.description if self.value is None else f"{self.description} = {fmt(self.value)}"


@dataclass(frozen=True)
class NormalizedPrice:
    price: Optional[Fraction]                  # INR excl. GST per normalized unit; None if unusable
    steps: tuple[TraceStep, ...]
    problem: Optional[MissingInfo] = None

    @property
    def usable(self) -> bool:
        return self.price is not None


def normalize(evidence: OfferEvidence, thread: ThreadInput, playbook: Playbook,
              previous: Optional[OfferEvidence] = None) -> NormalizedPrice:
    category = playbook.categories[thread.category]
    quantity = thread.quantity
    steps: list[TraceStep] = [TraceStep(f"Supplier wrote: {evidence.source_line!r}")]

    # "D% off our previous quote" applies to the supplier's own previous quote.
    if evidence.discount_on_previous_percent is not None and not evidence.amounts:
        if previous is None:
            return NormalizedPrice(None, tuple(steps), MissingInfo.NO_PREVIOUS_QUOTE)
        prior = normalize(previous, thread, playbook)
        if prior.price is None:
            return NormalizedPrice(None, tuple(steps) + prior.steps, prior.problem or MissingInfo.NO_PREVIOUS_QUOTE)
        steps.append(TraceStep("Previous supplier quote, normalized", prior.price))
        price = prior.price * (1 - evidence.discount_on_previous_percent / 100)
        steps.append(TraceStep(f"x (1 - {fmt(evidence.discount_on_previous_percent)}%) discount on previous quote", price))
        return NormalizedPrice(price, tuple(steps))

    # Currency -> INR (a supplier contract rate replaces the table rate for that supplier and currency).
    inr: list[Fraction] = []
    for money in evidence.amounts:
        if money.currency == "INR":
            inr.append(money.amount)
            continue
        rate = playbook.fx_rate(thread.supplier, money.currency)
        if rate is None:
            return NormalizedPrice(None, tuple(steps), MissingInfo.UNSUPPORTED_CURRENCY)
        value = money.amount * rate[0]
        steps.append(TraceStep(f"{money.currency} {fmt(money.amount)} x INR {fmt(rate[0])} ({rate[1]})", value))
        inr.append(value)
    if not inr:
        return NormalizedPrice(None, tuple(steps), MissingInfo.NO_PRICE_FOUND)

    # Choose the base amount.
    if evidence.list_discount_percent is not None:
        price = inr[0] * (1 - evidence.list_discount_percent / 100)
        steps.append(TraceStep(f"List price {fmt(inr[0])} less {fmt(evidence.list_discount_percent)}%", price))
    elif evidence.is_range:
        price = max(inr[:2])
        steps.append(TraceStep("Quoted range: evaluated at the higher end (precedents P-01, P-04)", price))
    elif evidence.tier_max_quantity is not None and len(inr) >= 2:
        small = quantity <= evidence.tier_max_quantity
        price = inr[0] if small else inr[1]
        steps.append(TraceStep(
            f"Tiered price: quantity {quantity} is {'within' if small else 'above'} the tier limit "
            f"{evidence.tier_max_quantity}", price))
    else:
        price = inr[0]
        steps.append(TraceStep("Quoted price", price))

    if evidence.total_units:
        price = price / evidence.total_units
        steps.append(TraceStep(f"Total for all {evidence.total_units} units: divide by {evidence.total_units}", price))

    # Units: dozen / explicit pack / "per N units", else the category page's pack or sub-unit conversion.
    if evidence.unit_divisor != 1:
        price = price / evidence.unit_divisor
        steps.append(TraceStep(f"Quoted per {evidence.unit_divisor} units: divide by {evidence.unit_divisor}", price))
    elif evidence.unit_word:
        word = evidence.unit_word
        unit = word[:-1] if word.endswith("s") and not word.endswith("ss") else word
        if unit in category.sub_units:
            price = price * category.sub_units[unit]
            steps.append(TraceStep(f"Per {unit}: one normalized unit holds {category.sub_units[unit]} of them, multiply", price))
        elif unit in category.pack_size:
            price = price / category.pack_size[unit]
            steps.append(TraceStep(f"Per {unit}: a {unit} holds {category.pack_size[unit]} units, divide", price))

    if evidence.free_units:
        free, paid = evidence.free_units
        price = price * paid / (paid + free)
        steps.append(TraceStep(f"{free} free for every {paid} paid: x {paid}/{paid + free} (precedents P-02, P-05)", price))
    if evidence.volume_discount and evidence.tier_max_quantity is None:
        percent, threshold = evidence.volume_discount
        if quantity >= threshold:
            price = price * (1 - percent / 100)
            steps.append(TraceStep(f"Volume discount {fmt(percent)}%: quantity {quantity} >= {threshold}", price))
        else:
            steps.append(TraceStep(f"Volume discount not applied: quantity {quantity} < {threshold}"))
    if evidence.gst_inclusive:
        price = price / (1 + category.gst_rate)
        steps.append(TraceStep(f"GST-inclusive: divide by 1 + {fmt(category.gst_rate * 100)}%", price))

    # Billing period (subscription categories only; monthly <-> yearly is x/÷ 12).
    if category.period:
        if evidence.billing_period is None:
            return NormalizedPrice(None, tuple(steps), MissingInfo.MISSING_BILLING_PERIOD)
        if evidence.billing_period != category.period:
            price = price * 12 if evidence.billing_period == "month" else price / 12
            steps.append(TraceStep(f"Billing period {evidence.billing_period} -> {category.period} (precedent P-06)", price))
    steps.append(TraceStep(f"Normalized price ({category.normalized_unit})", price))
    return NormalizedPrice(price, tuple(steps))
