"""Text hygiene and thread structure. Supplier text is untrusted; nothing here executes or obeys it."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Look-alike letters sometimes used to evade keyword filters (Cyrillic/Greek -> Latin).
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s", "ј": "j",
    "ԁ": "d", "ɡ": "g", "α": "a", "ε": "e", "ο": "o", "ι": "i", "ν": "v", "ρ": "p", "τ": "t",
})


def canonical(text: str) -> str:
    """Normalize text for *matching only*: NFKC, drop invisible/format characters, fold look-alikes."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return text.translate(_CONFUSABLES)


def clean(text: str) -> str:
    """Normalize supplier text before parsing: NFKC (full-width digits, ligatures) and no invisible characters."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


@dataclass(frozen=True)
class Message:
    sender: str
    body: str


@dataclass(frozen=True)
class ParsedThread:
    latest: Message
    earlier: tuple[Message, ...]       # oldest first

    @property
    def full_text(self) -> str:
        return "\n".join([m.body for m in self.earlier] + [self.latest.body])

    @property
    def earlier_supplier_messages(self) -> tuple[Message, ...]:
        return tuple(m for m in self.earlier if m.sender.casefold() != "acme procurement")


_HEADER = re.compile(r"\[(Earlier|Latest) message — ([^,\]]+)[^\]]*\]\n?")


def parse_thread(text: str) -> ParsedThread:
    """Split a thread into its latest message and earlier messages.

    A thread without "[Earlier/Latest message ...]" headers is a single latest message.
    """
    text = clean(text)
    headers = list(_HEADER.finditer(text))
    if not headers:
        return ParsedThread(Message("supplier", text), ())
    messages = []
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        messages.append(Message(header.group(2).strip(), text[header.end():end]))
    return ParsedThread(messages[-1], tuple(messages[:-1]))
