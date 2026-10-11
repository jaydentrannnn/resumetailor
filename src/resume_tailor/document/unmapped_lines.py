"""Lines above the first section that map to no name/contact field.

Before this existed such a line (a street address in a table layout's contact block, a
tagline under the name) stayed frozen text in the template: shown on every resume and
cover letter, editable nowhere. The analysis now lists them so the wizard can keep each
one as an editable custom field (`template_profile.CustomFieldSlot`), keep it verbatim,
or remove it. Pure: reads the analysis' paragraph view, never the document.
"""

from __future__ import annotations

import re

from . import analysis_types, entry_structure

_STREET_RE = re.compile(r"^\d+[A-Za-z]?\s+\S+")


def detect(
    paras: list[analysis_types._Para],
    *,
    first_heading_id: int | None,
    claimed_ids: set[int],
) -> list[analysis_types.UnmappedLine]:
    """Every non-blank, non-bullet, non-chrome line above `first_heading_id` whose id
    is not in `claimed_ids` (the name, the contact line, each contact slot).

    Nothing is reported without a detected heading — "above the first section" has no
    meaning then, and the analysis already fails such a document on its own terms."""
    if first_heading_id is None:
        return []
    lines: list[analysis_types.UnmappedLine] = []
    taken: set[str] = set()
    for p in paras:
        if p.id >= first_heading_id:
            break
        text = p.text.strip()
        if p.id in claimed_ids or p.is_bullet or entry_structure._is_chrome(text):
            continue
        label = _guess_label(text, len(lines) + 1)
        key = _unique_key(label, taken)
        lines.append(
            analysis_types.UnmappedLine(
                paragraph_id=p.id,
                text=text,
                # A collapsed tag carries one run's formatting and no hyperlink, so a
                # linked line is kept verbatim unless the user chooses otherwise.
                suggestion="static" if p.has_hyperlink else "field",
                suggested_key=key,
                suggested_label=label,
            )
        )
    return lines


def _guess_label(text: str, ordinal: int) -> str:
    if _STREET_RE.match(text):
        return "Street address"
    return f"Line {ordinal}"


def key_for(label: str) -> str:
    """A `CUSTOM_KEY_PATTERN`-valid slug for `label` ("Street address" -> "street_address")."""
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:32]
    if not slug or not slug[0].isalpha():
        slug = f"line_{slug}" if slug else "line"
    return slug


def _unique_key(label: str, taken: set[str]) -> str:
    base = key_for(label)
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    taken.add(key)
    return key
