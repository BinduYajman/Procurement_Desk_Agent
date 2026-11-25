"""Number notation helpers: amounts in words, Indian units (lakh/crore), spoken fractions."""
from __future__ import annotations

import re
from fractions import Fraction

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
NUMBER_WORD = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
               r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
               r"hundred|thousand|lakh|crore)")


def words_to_number(text: str) -> Fraction | None:
    """'seventeen thousand four hundred' -> 17400; None if any token is not a number word."""
    total = current = 0
    for word in re.split(r"[\s\-]+", text.lower().replace(" and ", " ")):
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word == "thousand":
            total += max(current, 1) * 1000; current = 0
        elif word == "lakh":
            total += max(current, 1) * 100000; current = 0
        elif word == "crore":
            total += max(current, 1) * 10000000; current = 0
        elif word:
            return None
    return Fraction(total + current)


# Spoken shares of an order value, as percentages.
SPOKEN_SHARES = {
    "half": Fraction(50), "one half": Fraction(50), "a third": Fraction(100, 3), "one third": Fraction(100, 3),
    "two thirds": Fraction(200, 3), "a quarter": Fraction(25), "one quarter": Fraction(25),
    "three quarters": Fraction(75), "three-quarters": Fraction(75), "full": Fraction(100), "entire": Fraction(100),
}
