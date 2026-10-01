"""Phone numbers in the two shapes application forms ask for (plan P4-E, E16).

The applicant types a phone once, in whatever shape they like ("(555) 010-0000",
"+44 7700 900123", "07700 900123"). Forms want either:

- **E.164**, ``+15550100000``, when one box holds the whole international number
  (a ``+1`` placeholder, an ``international`` hint, a ``^\\+`` pattern); or
- **the national number**, ``5550100000``, when a separate country-code control sits
  beside the box, so the code is never typed twice.

Pure string rules, no phone library: country code from the typed ``+``/``00`` prefix,
else the profile's ``phone_country_code``; a national trunk ``0`` is dropped for
non-NANP codes; NANP numbers keep 10 digits. Anything that is not 8-15 digits once
normalised is left alone (``None``), and the form gets the phone as typed.
"""

from __future__ import annotations

import re

#: Calling codes by length, longest first matched: enough to split a typed ``+`` number.
_CODES_1 = {"1", "7"}
_CODES_2 = frozenset(
    "20 27 30 31 32 33 34 36 39 40 41 43 44 45 46 47 48 49 51 52 53 54 55 56 57 58 60 61 "
    "62 63 64 65 66 81 82 84 86 90 91 92 93 94 95 98".split()
)


def _code_digits(country_code: str) -> str:
    return re.sub(r"\D", "", country_code or "")


def _split_international(digits: str) -> tuple[str, str]:
    """``(code, national)`` for digits typed after ``+``/``00``."""
    if digits[:1] in _CODES_1:
        return digits[:1], digits[1:]
    if digits[:2] in _CODES_2:
        return digits[:2], digits[2:]
    return digits[:3], digits[3:]


def split(phone: str, country_code: str = "+1") -> tuple[str, str] | None:
    """``(calling code digits, national digits)``, or None when it does not parse."""
    raw = (phone or "").strip()
    if not raw:
        return None
    raw = re.split(r"\s*(?:x|ext\.?|extension|#)\s*\d+\s*$", raw, flags=re.I)[0]
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        code, national = _split_international(digits)
    elif digits.startswith("00"):
        code, national = _split_international(digits[2:])
    else:
        code = _code_digits(country_code) or "1"
        national = digits
        # Drop a NANP leading 1, or a national trunk 0 elsewhere.
        trunk = "1" if code == "1" and len(national) == 11 else "0" if code != "1" else ""
        if trunk and national.startswith(trunk):
            national = national[1:]
    if code == "1" and len(national) != 10:
        return None
    if not national or not 8 <= len(code) + len(national) <= 15:
        return None
    return code, national


def e164(phone: str, country_code: str = "+1") -> str | None:
    """``+15550100000``, or None when ``phone`` does not parse."""
    parts = split(phone, country_code)
    return f"+{parts[0]}{parts[1]}" if parts else None


def national(phone: str, country_code: str = "+1") -> str | None:
    """The number without its calling code, for a form with a separate code control."""
    parts = split(phone, country_code)
    return parts[1] if parts else None
