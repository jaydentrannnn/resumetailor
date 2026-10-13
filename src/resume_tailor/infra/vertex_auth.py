"""One installation's Google connection; credentials never leave the backend."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any

from . import secret_store, vertex_catalog

SECRET = "oauth:google_vertex"
_lock = threading.RLock()
_epoch = 0
_tokens: dict[tuple[str, str], Any] = {}


class ConnectionError(RuntimeError):
    """An actionable, safe-to-display Google connection failure."""


def _read() -> dict:
    try:
        value = secret_store.get(SECRET)
        data = json.loads(value) if value else {}
        if not isinstance(data, dict) or (data and not isinstance(data.get("credentials"), dict)):
            raise ValueError("Invalid Google connection")
        return data
    except (ValueError, secret_store.SecretStoreError) as exc:
        raise ConnectionError(
            "Cannot read the Google connection. Unlock your keychain and reconnect."
        ) from exc


def state() -> dict[str, Any]:
    with _lock:
        value = _read()
        return {
            "connected": bool(value),
            "email": value.get("email"),
            "revision": value.get("revision", ""),
        }


def epoch() -> int:
    with _lock:
        return _epoch


def save(credentials: dict, email: str, expected_epoch: int) -> None:
    global _epoch
    with _lock:
        if expected_epoch != _epoch:
            raise ConnectionError("This sign-in was superseded. Connect Google Cloud again.")
        if not credentials.get("refresh_token"):
            raise ConnectionError(
                "Google did not provide offline access. Reconnect and grant access."
            )
        stored = {
            key: value
            for key, value in credentials.items()
            if key not in {"token", "id_token", "expiry"}
        }
        try:
            secret_store.set(
                SECRET,
                json.dumps({"credentials": stored, "email": email, "revision": uuid.uuid4().hex}),
            )
        except secret_store.SecretStoreError as exc:
            raise ConnectionError(
                "Cannot save the Google connection. Unlock your keychain and retry."
            ) from exc
        _epoch += 1
        _tokens.clear()
        vertex_catalog.clear_credentials()


def disconnect() -> None:
    global _epoch
    with _lock:
        try:
            secret_store.delete(SECRET)
        except secret_store.SecretStoreError as exc:
            raise ConnectionError(
                "Cannot remove the Google connection. Unlock your keychain and retry."
            ) from exc
        _epoch += 1
        _tokens.clear()
        vertex_catalog.clear_credentials()


def credentials(revision: str, project: str) -> dict:
    with _lock:
        value = _read()
        if not revision or value.get("revision") != revision:
            raise ConnectionError(
                "Google connection changed or was removed. Reconnect or start a new run."
            )
        return {**value["credentials"], "quota_project_id": project}


def access_token(revision: str, project: str = "") -> str:
    """Serialize refresh for metadata calls; tokens stay in memory only."""
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    with _lock:
        info = credentials(revision, project)
        key = (revision, project)
        token = _tokens.get(key)
        if token is None:
            token = Credentials.from_authorized_user_info(info)
            _tokens[key] = token
        try:
            if not token.valid:
                token.refresh(Request())
        except GoogleAuthError as exc:
            _tokens.pop(key, None)
            raise ConnectionError(
                "Google sign-in expired or was revoked. Reconnect Google Cloud."
            ) from exc
        return str(token.token)
