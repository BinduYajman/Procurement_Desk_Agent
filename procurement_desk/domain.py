"""Core domain types: inputs, outputs and the closed vocabulary of outcomes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from fractions import Fraction
from typing import Any, Mapping, Optional


class Action(str, Enum):
    ACCEPT = "ACCEPT"
    COUNTER = "COUNTER"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class Reason(str, Enum):
    ACCEPTABLE_PRICE = "ACCEPTABLE_PRICE"
    COUNTER_OFFER = "COUNTER_OFFER"
    ABOVE_WALKAWAY = "ABOVE_WALKAWAY"
    BLACKLISTED_SUPPLIER = "BLACKLISTED_SUPPLIER"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    BANNED_TERM = "BANNED_TERM"
    MISSING_INFO = "MISSING_INFO"
    OVER_APPROVAL_LIMIT = "OVER_APPROVAL_LIMIT"


# The only (action, reason) pairs the playbook allows (policies/output-format.md).
VALID_OUTCOMES = frozenset({
    (Action.ACCEPT, Reason.ACCEPTABLE_PRICE),
    (Action.COUNTER, Reason.COUNTER_OFFER),
    (Action.REJECT, Reason.ABOVE_WALKAWAY),
    (Action.REJECT, Reason.BLACKLISTED_SUPPLIER),
    (Action.ESCALATE, Reason.MISSING_INFO),
    (Action.ESCALATE, Reason.PROMPT_INJECTION),
    (Action.ESCALATE, Reason.BANNED_TERM),
    (Action.ESCALATE, Reason.OVER_APPROVAL_LIMIT),
})

LABEL_PATTERN = re.compile(
    r"^(ACCEPT:ACCEPTABLE_PRICE:|COUNTER:COUNTER_OFFER:\d+|REJECT:(BLACKLISTED_SUPPLIER|ABOVE_WALKAWAY):|"
    r"ESCALATE:(MISSING_INFO|PROMPT_INJECTION|BANNED_TERM|OVER_APPROVAL_LIMIT):)$")


class InvalidThreadError(ValueError):
    """A thread row that cannot be processed (bad types, unknown category, ...)."""


@dataclass(frozen=True)
class ThreadInput:
    thread_id: str
    date: str
    supplier: str
    category: str
    quantity: int
    round: int
    our_last_counter: Optional[str]
    supplier_message: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "ThreadInput":
        """Validate and build a thread from a CSV row or JSON object."""
        try:
            thread_id = str(row["thread_id"]).strip()
            if not thread_id:
                raise ValueError("empty thread_id")
            when = str(row["date"]).strip()
            date.fromisoformat(when)
            quantity, rnd = int(str(row["quantity"]).strip()), int(str(row["round"]).strip())
            if quantity <= 0 or rnd <= 0:
                raise ValueError("quantity and round must be positive")
            counter = row.get("our_last_counter")
            return cls(thread_id, when, str(row["supplier"]).strip(), str(row["category"]).strip(), quantity, rnd,
                       str(counter).strip() if counter not in (None, "") else None, str(row["supplier_message"]))
        except KeyError as error:
            raise InvalidThreadError(f"missing field {error.args[0]!r}") from error
        except (ValueError, TypeError) as error:
            raise InvalidThreadError(str(error)) from error


@dataclass(frozen=True)
class Decision:
    thread_id: str
    action: Action
    reason: Reason
    counter_price: Optional[int] = None

    def __post_init__(self) -> None:
        if (self.action, self.reason) not in VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome {self.action.value}:{self.reason.value}")
        if (self.action is Action.COUNTER) != (self.counter_price is not None):
            raise ValueError("counter_price is required for COUNTER and forbidden otherwise")

    @property
    def label(self) -> str:
        counter = str(self.counter_price) if self.counter_price is not None else ""
        return f"{self.action.value}:{self.reason.value}:{counter}"


@dataclass(frozen=True)
class Money:
    currency: str          # ISO code, e.g. "INR"
    amount: Fraction
    raw: str = ""          # the text as written, for the audit trail
