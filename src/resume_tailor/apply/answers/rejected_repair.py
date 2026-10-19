"""Typing a filled answer the form rejects again, in another shape (deterministic, no LLM).

A phone number, date or postal code the form refuses is typed again in the other shapes
the same value takes, until the form accepts one; the value itself never changes. Any
other refused answer, or one no shape fixes, is put back as it was and becomes a review
note naming the question and the form's own message. A box the form accepts is never
touched, and the value is never sent anywhere (`page_blockers` reports these apart).
"""

from __future__ import annotations

import contextlib
import logging
import re
from datetime import datetime
from typing import Any

from resume_tailor.apply.answers import phone, questions

_log = logging.getLogger(__name__)

#: Date shapes tried, after the one the box's placeholder spells out.
_DATE_FORMATS = (
    "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y",
)
_MONTH_FORMATS = ("%m/%Y", "%Y-%m", "%m-%Y", "%B %Y", "%b %Y")
#: Placeholder tokens, longest first, and the strftime field each spells.
_PLACEHOLDER_TOKENS = (
    ("YYYY", "%Y"), ("yyyy", "%Y"), ("MM", "%m"), ("mm", "%m"), ("DD", "%d"), ("dd", "%d"),
    ("YY", "%y"), ("yy", "%y"),
)
_POSTAL_LABEL = re.compile(r"\b(?:zip|postal|post)\s*code\b|\bpostcode\b", re.I)
_STILL_REFUSED_JS = """(el) => el.getAttribute('aria-invalid') === 'true'
  || (!!el.validity && !el.validity.valid)"""


def _placeholder_format(placeholder: str) -> str | None:
    """"MM/DD/YYYY" -> "%m/%d/%Y"; None when the placeholder is not a date pattern."""
    text = placeholder.strip()
    if not re.fullmatch(r"[MDYmdy]{2,4}(?:[-/. ][MDYmdy]{2,4}){1,2}", text):
        return None
    for token, field in _PLACEHOLDER_TOKENS:
        text = text.replace(token, field)
    return text


def date_readings(value: str) -> set[tuple[datetime, bool]]:
    """Every date ``value`` can spell, each with whether it names a day (else only a
    month): "05/06/2027" reads as May 6 and as June 5."""
    for formats, has_day in ((_DATE_FORMATS, True), (_MONTH_FORMATS, False)):
        found = set()
        for fmt in formats:
            with contextlib.suppress(ValueError):
                found.add((datetime.strptime(value.strip(), fmt), has_day))
        if found:
            return found
    return set()


def _spelled(reading: tuple[datetime, bool]) -> str:
    when, has_day = reading
    return when.strftime("%Y-%m-%d" if has_day else "%Y-%m")


def known_dates(fields: dict[str, Any]) -> set[str]:
    """The ISO dates and months among the applicant's packet fields: what settles which
    reading of "05/06/2027" was meant."""
    return {
        str(value).strip() for value in (fields or {}).values()
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value.strip())
    }


def _meant(value: str, known: set[str]) -> tuple[datetime, bool] | None:
    """The one date ``value`` means, or None: day and month could swap, and only a
    profile date settles which."""
    readings = date_readings(value)
    if len(readings) > 1:
        readings = {reading for reading in readings if _spelled(reading) in known}
    return readings.pop() if len(readings) == 1 else None


def _date_shapes(value: str, placeholder: str, known: set[str]) -> list[str]:
    meant = _meant(value, known)
    if meant is None:
        return []
    when, has_day = meant
    preferred = _placeholder_format(placeholder)
    if not (preferred and (has_day or "%d" not in preferred)):
        preferred = None
    # A shape the form could read with day and month swapped ("05/06/2027") is typed
    # only when the box's own placeholder says which comes first.
    found = [preferred] if preferred else []
    for fmt in _DATE_FORMATS if has_day else _MONTH_FORMATS:
        if not has_day or _one_reading(when, fmt):
            found.append(fmt)
    return [when.strftime(fmt) for fmt in dict.fromkeys(found)]


def _one_reading(when: datetime, fmt: str) -> bool:
    """Whether any form reads ``when`` typed as ``fmt`` as that date: year first (ISO),
    a month name, or a day no month number could be."""
    return (fmt.startswith("%Y") or "%B" in fmt or "%b" in fmt
            or when.day > 12 or when.day == when.month)


def _phone_shapes(value: str, country_code: str) -> list[str]:
    parts = phone.split(value, country_code)
    if parts is None:
        return []
    code, national = parts
    shapes = [f"+{code}{national}", national, f"+{code} {national}"]
    if code == "1":
        area, prefix, line = national[:3], national[3:6], national[6:]
        shapes[2:2] = [f"({area}) {prefix}-{line}", f"{area}-{prefix}-{line}"]
    return shapes


def _postal_shapes(value: str) -> list[str]:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 9:  # US ZIP+4
        return [f"{digits[:5]}-{digits[5:]}", digits[:5], digits]
    if len(digits) == 5:
        return [digits]
    compact = re.sub(r"\s+", "", value).upper()  # "SW1A 1AA" / "K1A 0B1"
    return [compact, f"{compact[:-3]} {compact[-3:]}"] if len(compact) > 4 else []


def _kind(item: dict[str, Any]) -> str:
    label = str(item.get("label") or "")
    match = questions.classify(questions.Question(label, kind="text"))
    key = match.key if match is not None else ""
    if item.get("kind") == "tel" or "phone" in key:
        return "phone"
    if key == "postal_code" or _POSTAL_LABEL.search(label):
        return "postal"
    return "date"


def shapes(
    item: dict[str, Any], value: str, *, country_code: str = "+1",
    known: set[str] | None = None,
) -> list[str]:
    """Other ways to type ``value`` for the rejected box ``item``, best first."""
    kind = _kind(item)
    if kind == "phone":
        found = _phone_shapes(value, country_code)
    elif kind == "postal":
        found = _postal_shapes(value)
    else:
        found = _date_shapes(value, str(item.get("placeholder") or ""), known or set())
    return [shape for shape in dict.fromkeys(found) if shape != value]


def _holds(
    kind: str, shape: str, retained: str, country_code: str,
    meant: tuple[datetime, bool] | None = None,
) -> bool:
    """Whether the box still holds the answer ``shape`` typed (a mask may reformat it;
    a widget that emptied it, kept part of it, or read it as another date does not)."""
    if not retained.strip():
        return False
    if kind == "phone":
        typed, kept = phone.split(shape, country_code), phone.split(retained, country_code)
        return typed is not None and typed == kept
    if kind == "postal":
        return re.sub(r"[\s-]", "", retained).upper() == re.sub(r"[\s-]", "", shape).upper()
    # Reformatted, it must spell the original date and nothing else.
    return retained.strip() == shape or (meant is not None and date_readings(retained) == {meant})


def note_for(item: dict[str, Any]) -> str:
    message = str(item.get("message") or "").strip() or "the form does not accept this answer"
    return f"{item.get('label') or 'A field'}: {message}"


def repair(
    target: Any, item: dict[str, Any], *, country_code: str = "+1",
    known: set[str] | None = None,
) -> bool:
    """Type ``item``'s value again in each other shape until the form accepts one and the
    box still holds it. False (with the original put back) when none does."""
    if item.get("kind") in {"select", "textarea"}:
        return False
    kind = _kind(item)
    try:
        control = target.locator(str(item["selector"])).first
        original = control.input_value(timeout=1000)
        meant = _meant(original, known or set()) if kind == "date" else None
        for shape in shapes(item, original, country_code=country_code, known=known):
            control.fill(shape, timeout=2000)
            control.blur(timeout=1000)
            target.wait_for_timeout(200)
            retained = control.input_value(timeout=1000)
            if (control.evaluate(_STILL_REFUSED_JS) is not True
                    and _holds(kind, shape, retained, country_code, meant)):
                return True
        control.fill(original, timeout=2000)
        control.blur(timeout=1000)
    except Exception as exc:  # noqa: BLE001 - a box that went away is left for review
        _log.debug("rejected-answer repair failed: %s", exc)
    return False
