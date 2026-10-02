"""Per-source run health (``source_status.json``)."""

from __future__ import annotations

from typing import Any

import httpx

# --- per-source run health (`source_status.json`) ---------------------------------------
_STATUS_ERROR_LIMIT = 200

_STATUS_WRITE_ATTEMPTS = 5

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
    entries = {
        str(sid): {
            "found": entry["found"],
            "kept": entry["kept"],
            "error": entry.get("error") if isinstance(entry.get("error"), str) else None,
            "at": entry["at"],
        }
        for sid, entry in raw["sources"].items()
        if isinstance(entry, dict)
        and isinstance(entry.get("found"), int)
        and isinstance(entry.get("kept"), int)
        and isinstance(entry.get("at"), str)
    }
    last = raw.get("last_run_at")
    return {"sources": entries, "last_run_at": last if isinstance(last, str) else None}

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
        merged["sources"].update(entries)
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
