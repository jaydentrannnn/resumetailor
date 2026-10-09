"""Plain-language "what changed" between two saved master resumes (no LLM, ever).

Works on the raw JSON dicts rather than `MasterResume`, so an old or hand-edited
version that no longer validates still gets a summary. Entries are matched by `id`,
falling back to their name field (education and skill groups carry no id), so a
renamed entry reads as an edit, while a reordered list reads as one "Reordered" line.
"""

from __future__ import annotations

import json
from typing import Any

#: How an entry is named in a change line, per section kind (first non-empty wins).
_NAME_FIELDS = ("company", "name", "school", "label", "text", "title", "degree")
#: Fields that are not "header" fields of an entry.
_SKIP_FIELDS = {"id", "bullets"}
_FIELD_LABELS = {
    "start": "dates", "end": "dates", "dates": "dates", "date": "dates",
    "gpa": "GPA", "show_gpa": "GPA visibility", "tags": "extra skills",
    "items": "skills", "tech": "tech", "url": "link", "link": "link",
    "linkedin": "LinkedIn", "github": "GitHub",
}


def _label(field: str) -> str:
    return _FIELD_LABELS.get(field, field.replace("_", " "))


def _join(words: list[str]) -> str:
    unique = list(dict.fromkeys(words))
    if len(unique) <= 2:
        return " and ".join(unique)
    return ", ".join(unique[:-1]) + " and " + unique[-1]


def _count(n: int, noun: str) -> str:
    return f"a {noun}" if n == 1 else f"{n} {noun}s"


def _name(entry: dict[str, Any]) -> str:
    for field in _NAME_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return text if len(text) <= 40 else text[:39] + "…"
    return "an entry"


def _key(entry: dict[str, Any], index: int) -> str:
    if entry.get("id"):
        return f"id:{entry['id']}"
    for field in _NAME_FIELDS:
        if isinstance(entry.get(field), str) and entry[field].strip():
            return f"{field}:{entry[field].strip().lower()}"
    return f"index:{index}"


def _keyed(items: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        if isinstance(item, dict):
            out.setdefault(_key(item, index), item)
    return out


def _bullet_parts(old: list[Any], new: list[Any]) -> list[str]:
    before = {b.get("id"): b for b in old if isinstance(b, dict)}
    after = {b.get("id"): b for b in new if isinstance(b, dict)}
    added = len(after.keys() - before.keys())
    removed = len(before.keys() - after.keys())
    edited = sum(
        1 for k in after.keys() & before.keys()
        if after[k].get("text") != before[k].get("text")
        or after[k].get("tags") != before[k].get("tags")
    )
    parts = []
    if added:
        parts.append(f"added {_count(added, 'bullet')}")
    if edited:
        parts.append(f"edited {_count(edited, 'bullet')}")
    if removed:
        parts.append(f"removed {_count(removed, 'bullet')}")
    shared = [k for k in after if k in before]
    if not (added or removed) and shared != [k for k in before if k in after]:
        parts.append("reordered bullets")
    return parts


def _entry_parts(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    fields = [
        _label(f) for f in sorted(old.keys() | new.keys())
        if f not in _SKIP_FIELDS and old.get(f) != new.get(f)
    ]
    parts = [f"changed {_join(fields)}"] if fields else []
    return parts + _bullet_parts(old.get("bullets") or [], new.get("bullets") or [])


def _section_lines(
    old: dict[str, Any], new: dict[str, Any], edits: list[tuple[str, str]]
) -> list[str]:
    """Structural lines for one section; per-entry edits are appended to `edits`."""
    title = (new.get("title") or old.get("title") or "a section").strip()
    lines = []
    if (old.get("title") or "") != (new.get("title") or ""):
        lines.append(f"Renamed section '{old.get('title')}' to '{new.get('title')}'")
    before = _keyed(old.get("entries") or [])
    after = _keyed(new.get("entries") or [])
    for key, entry in after.items():
        if key not in before:
            lines.append(f"Added '{_name(entry)}' to {title}")
    for key, entry in before.items():
        if key not in after:
            lines.append(f"Removed '{_name(entry)}' from {title}")
    for key, entry in after.items():
        if key in before:
            parts = _entry_parts(before[key], entry)
            if parts:
                edits.append((f"{_name(entry)} ({title})", ", ".join(parts)))
    shared = [k for k in after if k in before]
    if shared != [k for k in before if k in after]:
        lines.append(f"Reordered {title}")
    return lines


def changes(old_text: str, new_text: str) -> list[str]:
    """Change lines from `old_text` to `new_text`, most structural first.

    Empty when nothing a person would notice changed (whitespace, key order).
    """
    try:
        old, new = json.loads(old_text), json.loads(new_text)
    except ValueError:
        return ["Edited outside the app (not readable as a resume)"]
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    lines: list[str] = []
    old_contact, new_contact = old.get("contact") or {}, new.get("contact") or {}
    contact = [
        _label(f) for f in sorted(old_contact.keys() | new_contact.keys())
        if old_contact.get(f) != new_contact.get(f)
    ]
    if contact:
        lines.append(f"Changed {_join(contact)} in contact details")
    if old.get("summary_variants") != new.get("summary_variants"):
        lines.append("Edited the summary")

    before = _keyed(old.get("sections") or [])
    after = _keyed(new.get("sections") or [])
    for key, section in after.items():
        if key not in before:
            lines.append(f"Added section '{section.get('title', '')}'")
    for key, section in before.items():
        if key not in after:
            lines.append(f"Removed section '{section.get('title', '')}'")
    edits: list[tuple[str, str]] = []
    for key, section in after.items():
        if key in before:
            lines.extend(_section_lines(before[key], section, edits))
    shared = [k for k in after if k in before]
    if shared != [k for k in before if k in after]:
        lines.append("Reordered sections")
    return lines + _edit_lines(edits)


#: The same edit on this many entries or more reads as one line ("changed dates in 13 entries").
_GROUP_AT = 3


def _edit_lines(edits: list[tuple[str, str]]) -> list[str]:
    counts: dict[str, int] = {}
    for _, parts in edits:
        counts[parts] = counts.get(parts, 0) + 1
    lines, grouped = [], set()
    for where, parts in edits:
        if counts[parts] < _GROUP_AT:
            lines.append(f"{where}: {parts}")
        elif parts not in grouped:
            grouped.add(parts)
            lines.append(f"{parts[0].upper()}{parts[1:]} in {counts[parts]} entries")
    return lines
