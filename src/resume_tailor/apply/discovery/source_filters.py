"""Filters for every source: the global keep/skip/location words on ``ApplySettings``.

A source's own words are added to the global ones (a source can narrow, never undo a
global skip); ``ignore_global_include`` opts one source out of the global keep words.
Merging happens once, before a source is fetched, so every reader downstream
(`source_watchlists.source_keyword_filters` and its callers) sees one merged source.
"""

from __future__ import annotations

from typing import Any

FIELDS = ("include", "exclude", "locations")


def _merge(first: list[str], second: list[str]) -> list[str]:
    """``first`` then ``second``, trimmed, with case-insensitive repeats dropped."""
    seen: set[str] = set()
    out: list[str] = []
    for word in [*first, *second]:
        text = word.strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def with_global_filters(src: Any, filters: Any) -> Any:
    """``src`` (a `SourceConfig`) with the global ``filters`` (a `SourceFilters`) added."""
    if filters is None:
        return src
    include = [] if src.ignore_global_include else filters.include
    return src.model_copy(
        update={
            "include": _merge(include, src.include),
            "exclude": _merge(filters.exclude, src.exclude),
            "locations": _merge(filters.locations, src.locations),
        }
    )


def hoist_shared(data: dict[str, Any]) -> dict[str, Any]:
    """Move the words every source shares into a new ``source_filters`` (raw settings dict).

    Runs once, on settings saved before global filters existed (no ``source_filters``
    key). Because a source's words are added to the global ones, each source keeps
    exactly the filters it had. Needs at least two sources: one source's words are its
    own choice, not a shared default.
    """
    sources = data.get("sources")
    if "source_filters" in data or not isinstance(sources, list) or len(sources) < 2:
        return data
    if not all(isinstance(src, dict) for src in sources):
        return data
    shared: dict[str, list[str]] = {}
    for field in FIELDS:
        lists = [_merge([str(w) for w in src.get(field) or []], []) for src in sources]
        common = set.intersection(*({w.lower() for w in words} for words in lists))
        shared[field] = [w for w in lists[0] if w.lower() in common]
    if not any(shared.values()):
        return data

    def own(src: dict[str, Any], field: str) -> list[str]:
        hoisted = {w.lower() for w in shared[field]}
        return [w for w in src.get(field) or [] if str(w).strip().lower() not in hoisted]

    moved = [{**src, **{field: own(src, field) for field in FIELDS}} for src in sources]
    return {**data, "sources": moved, "source_filters": shared}
