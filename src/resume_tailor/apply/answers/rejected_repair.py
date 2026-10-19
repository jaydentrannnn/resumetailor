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


def _as_date(value: str) -> tuple[datetime, bool] | None:
    """The date ``value`` spells, and whether it names a day (else only a month)."""
    for formats, has_day in ((_DATE_FORMATS, True), (_MONTH_FORMATS, False)):
        for fmt in formats:
            with contextlib.suppress(ValueError):
                return datetime.strptime(value.strip(), fmt), has_day
    return None


def _date_shapes(value: str, placeholder: str) -> list[str]:
    found = _as_date(value)
    if found is None:
        return []
    when, has_day = found
    formats = [*(_DATE_FORMATS if has_day else _MONTH_FORMATS)]
    preferred = _placeholder_format(placeholder)
    if preferred and (has_day or "%d" not in preferred):
        formats.insert(0, preferred)
    return [when.strftime(fmt) for fmt in dict.fromkeys(formats)]


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


def shapes(item: dict[str, Any], value: str, *, country_code: str = "+1") -> list[str]:
    """Other ways to type ``value`` for the rejected box ``item``, best first."""
    label = str(item.get("label") or "")
    kind = str(item.get("kind") or "")
    match = questions.classify(questions.Question(label, kind="text"))
    key = match.key if match is not None else ""
    if kind == "tel" or "phone" in key:
        found = _phone_shapes(value, country_code)
    elif key == "postal_code" or _POSTAL_LABEL.search(label):
        found = _postal_shapes(value)
    else:
        found = _date_shapes(value, str(item.get("placeholder") or ""))
    return [shape for shape in dict.fromkeys(found) if shape != value]


def note_for(item: dict[str, Any]) -> str:
    message = str(item.get("message") or "").strip() or "the form does not accept this answer"
    return f"{item.get('label') or 'A field'}: {message}"


def repair(target: Any, item: dict[str, Any], *, country_code: str = "+1") -> bool:
    """Type ``item``'s value again in each other shape until the form accepts one. False
    (with the original put back) when none is accepted."""
    if item.get("kind") in {"select", "textarea"}:
        return False
    try:
        control = target.locator(str(item["selector"])).first
        original = control.input_value(timeout=1000)
        for shape in shapes(item, original, country_code=country_code):
            control.fill(shape, timeout=2000)
            control.blur(timeout=1000)
            target.wait_for_timeout(200)
            if control.evaluate(_STILL_REFUSED_JS) is not True:
                return True
        control.fill(original, timeout=2000)
        control.blur(timeout=1000)
    except Exception as exc:  # noqa: BLE001 - a box that went away is left for review
        _log.debug("rejected-answer repair failed: %s", exc)
    return False
