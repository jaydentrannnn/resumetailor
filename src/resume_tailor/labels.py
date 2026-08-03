"""Shared label normalisation for user-facing names.

Both the template library (`web/template_ops.py`) and the workspace registry
(`workspace.py`) need identical rules for a saved-item label — strip/collapse
whitespace, enforce a max length, and reject case-insensitive duplicates — so the
rules live here once instead of drifting between the two call sites.
"""

from __future__ import annotations

from collections.abc import Iterable


def normalize_label(raw: str, *, max_len: int = 80, what: str = "Label") -> str:
    """Strip and collapse whitespace in `raw`; raise ValueError if invalid."""
    cleaned = " ".join((raw or "").split())
    if not cleaned:
        raise ValueError(f"{what} is required.")
    if len(cleaned) > max_len:
        raise ValueError(f"{what} is too long (max {max_len} characters).")
    return cleaned


def label_taken(label: str, existing: Iterable[str]) -> bool:
    """True when `label` case-insensitively matches any of `existing`."""
    needle = label.casefold()
    return any(item.casefold() == needle for item in existing)
