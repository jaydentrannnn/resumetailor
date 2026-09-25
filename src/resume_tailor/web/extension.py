"""Browser-extension pairing (plan P4-X, X1): short codes in, long-lived tokens out.

The extension's requests come from a ``chrome-extension://`` origin, which the request
gate's cross-site check refuses and which never carries the app's session cookie. So
the extension gets its own credential:

1. The student opens Settings → Browser and asks for a code. The app shows a 6-digit
   code, valid for `CODE_TTL` and `MAX_ATTEMPTS` wrong guesses, one code at a time.
2. The student types it into the extension popup, which posts it to
   ``/api/extension/pair/complete`` and gets back a random token.
3. Every later extension request sends that token in ``X-RT-Extension``.

Only a SHA-256 of each token is stored (``<DATA_ROOT>/extensions.json``, one file for
every profile, like the automation switch), so reading the file does not let anyone
act as the extension. Revoking a pairing deletes its hash.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resume_tailor import config

HEADER_NAME = "x-rt-extension"
CODE_TTL = 120.0
MAX_ATTEMPTS = 5
MAX_PAIRINGS = 20
_LAST_SEEN_EVERY = 60.0

_LOCK = threading.Lock()
#: The one pending code: ``{"code", "expires", "attempts"}`` or None.
_pending: dict[str, Any] | None = None
_seen_written: dict[str, float] = {}


class PairingError(ValueError):
    """A pairing code that is wrong, expired, or used up."""


def store_path() -> Path:
    return config.DATA_ROOT / "extensions.json"


def _clock() -> float:
    return time.monotonic()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load() -> list[dict[str, Any]]:
    try:
        raw = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = raw.get("pairings") if isinstance(raw, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and r.get("id") and r.get("token_sha256")]


def _save(rows: list[dict[str, Any]]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"pairings": rows}, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def reset() -> None:
    """Forget the pending code and the last-seen throttle (tests)."""
    global _pending
    with _LOCK:
        _pending = None
        _seen_written.clear()


def start_pairing() -> dict[str, Any]:
    """A fresh 6-digit code, replacing any code not yet used."""
    global _pending
    code = f"{secrets.randbelow(1_000_000):06d}"
    with _LOCK:
        _pending = {"code": code, "expires": _clock() + CODE_TTL, "attempts": 0}
    return {"code": code, "expires_in": int(CODE_TTL)}


def complete_pairing(code: str, label: str = "") -> tuple[str, str]:
    """Trade a valid code for ``(pairing id, token)``; the code is then used up.

    Raises:
        PairingError: No code pending, the code expired, too many wrong guesses, or
            the code does not match.
    """
    global _pending
    offered = "".join(ch for ch in str(code) if ch.isdigit())
    with _LOCK:
        pending = _pending
        if pending is None:
            raise PairingError("No pairing code is waiting. Ask ResumeTailor for a new one.")
        if _clock() > pending["expires"]:
            _pending = None
            raise PairingError("That code expired. Ask ResumeTailor for a new one.")
        if not hmac.compare_digest(offered, pending["code"]):
            pending["attempts"] += 1
            if pending["attempts"] >= MAX_ATTEMPTS:
                _pending = None
                raise PairingError("Too many wrong codes. Ask ResumeTailor for a new one.")
            raise PairingError("That code is not right. Check the number in ResumeTailor.")
        _pending = None
        token = secrets.token_urlsafe(32)
        row = {
            "id": uuid.uuid4().hex[:12],
            "label": (label or "Browser extension").strip()[:80],
            "created_at": _now_iso(),
            "last_seen": _now_iso(),
            "token_sha256": _hash(token),
        }
        rows = _load()
        rows.append(row)
        _save(rows[-MAX_PAIRINGS:])
    return row["id"], token


def verify_token(token: str) -> str | None:
    """The pairing id ``token`` belongs to, or None. Refreshes ``last_seen`` now and then."""
    if not token:
        return None
    digest = _hash(token)
    with _LOCK:
        rows = _load()
        match = next((r for r in rows if hmac.compare_digest(str(r["token_sha256"]), digest)), None)
        if match is None:
            return None
        now = _clock()
        if now - _seen_written.get(match["id"], -_LAST_SEEN_EVERY) >= _LAST_SEEN_EVERY:
            _seen_written[match["id"]] = now
            match["last_seen"] = _now_iso()
            _save(rows)
        return str(match["id"])


def list_pairings() -> list[dict[str, str]]:
    """Every pairing without its token hash, newest first."""
    with _LOCK:
        rows = _load()
    return [
        {k: str(r.get(k) or "") for k in ("id", "label", "created_at", "last_seen")}
        for r in reversed(rows)
    ]


def revoke(pairing_id: str) -> bool:
    """Delete one pairing; True when it existed."""
    with _LOCK:
        rows = _load()
        kept = [r for r in rows if r["id"] != pairing_id]
        if len(kept) == len(rows):
            return False
        _save(kept)
        _seen_written.pop(pairing_id, None)
    return True
