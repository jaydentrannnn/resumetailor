"""Per-source run health (``source_status.json``).

Each source keeps its latest run (``found``, ``kept``, ``blank``, ``error``, ``at``) and
the last `HISTORY` runs. `health` reads that history for a verdict the Sources tab shows:
**rate_limited** when the last error says the site throttled or blocked us, **degraded**
when a source that used to find postings now finds none, or when most of what it found
has no company or title (its page or feed changed shape). A healthy source gets none.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

# --- per-source run health (`source_status.json`) ---------------------------------------
_STATUS_ERROR_LIMIT = 200

_STATUS_WRITE_ATTEMPTS = 5
#: Runs kept per source for `health`.
HISTORY = 10
#: Fewer rows than this are too few to call a source's blank fields a pattern.
_BLANK_MIN_ROWS = 4
_RATE_LIMITED = re.compile(
    r"\bHTTP 429\b|rate.?limit|too many requests|captcha|\bblocked\b", re.IGNORECASE
)
_RUN_KEYS = ("found", "kept", "blank", "error", "at")

def short_reason(text: str) -> str:
    """One line of an error, capped so the Sources tab can show it inline."""
    line = " ".join(str(text).split())
    if len(line) > _STATUS_ERROR_LIMIT:
        line = line[: _STATUS_ERROR_LIMIT - 1].rstrip() + "…"
    return line

def load_source_status() -> dict[str, Any]:
    """The latest per-source run results: ``{"sources": {id: entry}, "last_run_at": str|None}``.

    A missing or unreadable file, or entries of the wrong shape, read as "never run" —
    health is advisory and must never break the page.
    """
    import json

    from resume_tailor import config

    empty: dict[str, Any] = {"sources": {}, "last_run_at": None}
    try:
        raw = json.loads(config.SOURCE_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
        return empty
    entries = {str(sid): _run(entry) for sid, entry in raw["sources"].items() if _valid(entry)}
    for sid, entry in raw["sources"].items():
        history = entry.get("history") if str(sid) in entries else None
        if isinstance(history, list):
            entries[str(sid)]["history"] = [_run(r) for r in history if _valid(r)][-HISTORY:]
    last = raw.get("last_run_at")
    return {"sources": entries, "last_run_at": last if isinstance(last, str) else None}

def _valid(entry: Any) -> bool:
    return (isinstance(entry, dict) and isinstance(entry.get("found"), int)
            and isinstance(entry.get("kept"), int) and isinstance(entry.get("at"), str))


def _run(entry: dict[str, Any]) -> dict[str, Any]:
    """One run's fields, read leniently; ``blank`` only when recorded (older files lack it)."""
    run = {
        "found": entry["found"],
        "kept": entry["kept"],
        "error": entry.get("error") if isinstance(entry.get("error"), str) else None,
        "at": entry["at"],
    }
    if isinstance(entry.get("blank"), int):
        run["blank"] = entry["blank"]
    return run


def _with_history(previous: dict[str, Any] | None, entry: dict[str, Any]) -> dict[str, Any]:
    """``entry`` with the runs before it (a pre-history entry counts as one run)."""
    past = list((previous or {}).get("history") or ([_run(previous)] if previous else []))
    latest = {key: entry[key] for key in _RUN_KEYS if key in entry}
    return {**entry, "history": [*past, latest][-HISTORY:]}


def health(entry: dict[str, Any]) -> dict[str, str | None]:
    """The source's verdict from its runs: ``{"health": ..., "health_reason": ...}``."""
    runs = entry.get("history") or [entry]
    latest = runs[-1]
    error = latest.get("error") or ""
    if _RATE_LIMITED.search(error):
        return {"health": "rate_limited", "health_reason": "The site is limiting or blocking "
                "requests; it should recover on a later run."}
    earlier = max((r["found"] for r in runs[:-1]), default=0)
    if latest["found"] == 0 and earlier and error in ("", "No postings found"):
        return {"health": "degraded", "health_reason": f"Found nothing this run after "
                f"{earlier:,} before; its page or search may have changed."}
    blank = latest.get("blank") or 0
    if latest["found"] >= _BLANK_MIN_ROWS and blank * 2 >= latest["found"]:
        return {"health": "degraded", "health_reason": f"{blank:,} of {latest['found']:,} "
                "postings came without a company or title; its format may have changed."}
    return {"health": None, "health_reason": None}


def record_source_status(entries: dict[str, dict[str, Any]], run_at: str) -> None:
    """Merge this run's per-source results into ``source_status.json`` (atomic).

    Sources absent from ``entries`` (disabled, or not in this run) keep their previous
    entry. Never raises: a failed write is logged and the run carries on.
    """
    import json
    import logging
    import os
    import time

    from resume_tailor import config

    try:
        merged = load_source_status()
        previous = merged["sources"]
        merged["sources"].update(
            {sid: _with_history(previous.get(sid), entry) for sid, entry in entries.items()}
        )
        merged["last_run_at"] = run_at
        path = config.SOURCE_STATUS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        for attempt in range(_STATUS_WRITE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: a reader holds the file open for a moment
                if attempt == _STATUS_WRITE_ATTEMPTS - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except Exception:  # noqa: BLE001 - health is advisory
        logging.getLogger(__name__).warning("could not write source status", exc_info=True)

def failure_reason(exc: Exception) -> str:
    """A short human reason for a whole-source failure (credentials, network, HTTP)."""
    from urllib.parse import urlsplit

    if isinstance(exc, httpx.HTTPStatusError):
        host = urlsplit(str(exc.request.url)).netloc
        return short_reason(f"HTTP {exc.response.status_code} from {host}")
    if isinstance(exc, httpx.RequestError):
        try:
            host = urlsplit(str(exc.request.url)).netloc
        except RuntimeError:  # httpx raises when the error carries no request
            host = ""
        return short_reason(
            f"could not reach {host}" if host else f"could not reach the source: {exc}"
        )
    return short_reason(str(exc) or type(exc).__name__)
