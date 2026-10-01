"""Passwords and API keys, kept out of the JSON files that hold everything else.

Backends, chosen once per process (`backend()`):

- **keyring**: the OS keychain (Windows Credential Manager, macOS Keychain, Secret
  Service on Linux desktops). Used whenever `keyring` finds a real backend.
- **file**: ``<DATA_ROOT>/secrets.enc``, a JSON map encrypted with Fernet. The key comes
  from ``RESUME_TAILOR_SECRET_KEY`` or a generated ``<DATA_ROOT>/.secret_key`` (mode
  0600). Used where no keychain exists (Docker, headless Linux). With the key file
  beside the data this is protection against a copied or synced JSON file, not against
  someone who can read the whole data folder; set ``RESUME_TAILOR_SECRET_KEY`` from
  outside the container for more.
- **memory**: a dict, for tests (``RESUME_TAILOR_SECRETS_BACKEND=memory``).

``RESUME_TAILOR_SECRETS_BACKEND`` forces one of the three. Names are plain strings; the
callers namespace them per profile (see `profile_name`).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Protocol

from resume_tailor import config

_log = logging.getLogger(__name__)

SERVICE = "ResumeTailor"
_FILE_NAME = "secrets.enc"
_KEY_FILE_NAME = ".secret_key"


class SecretStoreError(RuntimeError):
    """The backend refused a read or write (locked keychain, unreadable file, bad key)."""


class _Backend(Protocol):
    name: str

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class _MemoryBackend:
    name = "memory"

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class _KeyringBackend:
    name = "keyring"

    def __init__(self, keyring_module) -> None:
        self._keyring = keyring_module

    def get(self, name: str) -> str | None:
        try:
            return self._keyring.get_password(SERVICE, name)
        except Exception as exc:  # noqa: BLE001 - every keyring backend raises its own
            raise SecretStoreError(f"keychain read failed: {exc}") from exc

    def set(self, name: str, value: str) -> None:
        try:
            self._keyring.set_password(SERVICE, name, value)
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreError(f"keychain write failed: {exc}") from exc

    def delete(self, name: str) -> None:
        try:
            self._keyring.delete_password(SERVICE, name)
        except self._keyring.errors.PasswordDeleteError:
            return
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreError(f"keychain delete failed: {exc}") from exc


class _FileBackend:
    name = "file"

    def __init__(self, path: Path, key_path: Path) -> None:
        self.path = path
        self.key_path = key_path
        self._lock = threading.Lock()

    def _fernet(self):
        from cryptography.fernet import Fernet

        key = os.environ.get("RESUME_TAILOR_SECRET_KEY", "").strip().encode()
        if not key:
            if self.key_path.is_file():
                key = self.key_path.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                self.key_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(key)
        try:
            return Fernet(key)
        except ValueError as exc:
            raise SecretStoreError(
                "RESUME_TAILOR_SECRET_KEY / .secret_key is not a valid Fernet key"
            ) from exc

    def _read(self) -> dict[str, str]:
        from cryptography.fernet import InvalidToken

        if not self.path.is_file():
            return {}
        try:
            plain = self._fernet().decrypt(self.path.read_bytes())
        except InvalidToken as exc:
            raise SecretStoreError(
                f"{self.path.name} cannot be decrypted with the current key"
            ) from exc
        data = json.loads(plain.decode("utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _write(self, values: dict[str, str]) -> None:
        token = self._fernet().encrypt(json.dumps(values).encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".enc.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(token)
        tmp.replace(self.path)

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        with self._lock:
            values = self._read()
            values[name] = value
            self._write(values)

    def delete(self, name: str) -> None:
        with self._lock:
            values = self._read()
            if values.pop(name, None) is not None:
                self._write(values)


_backend: _Backend | None = None
_backend_lock = threading.Lock()


def _file_backend() -> _FileBackend:
    return _FileBackend(config.DATA_ROOT / _FILE_NAME, config.DATA_ROOT / _KEY_FILE_NAME)


def _choose() -> _Backend:
    forced = os.environ.get("RESUME_TAILOR_SECRETS_BACKEND", "").strip().lower()
    if forced == "memory":
        return _MemoryBackend()
    if forced == "file":
        return _file_backend()
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        keyring = None
    if keyring is not None:
        chosen = keyring.get_keyring()
        usable = not isinstance(chosen, fail.Keyring) and getattr(chosen, "priority", 0) > 0
        if usable or forced == "keyring":
            return _KeyringBackend(keyring)
    _log.warning(
        "no OS keychain available; storing secrets encrypted in %s",
        config.DATA_ROOT / _FILE_NAME,
    )
    return _file_backend()


def backend() -> _Backend:
    """The process's secret backend, chosen on first use."""
    global _backend
    with _backend_lock:
        if _backend is None:
            _backend = _choose()
        return _backend


def reset_backend() -> None:
    """Forget the chosen backend (tests, or after changing the env override)."""
    global _backend
    with _backend_lock:
        _backend = None


def get(name: str) -> str | None:
    """The stored secret, or None when there is none."""
    return backend().get(name)


def set(name: str, value: str) -> None:  # noqa: A001 - mirrors keyring's own verbs
    """Store ``value``; an empty value deletes the secret."""
    if value:
        backend().set(name, value)
    else:
        backend().delete(name)


def delete(name: str) -> None:
    """Remove the secret; a missing one is not an error."""
    backend().delete(name)


def profile_name(key: str, workspace_id: str | None = None) -> str:
    """A per-profile secret name: ``profile:<workspace id>:<key>``."""
    return f"profile:{workspace_id or config.active_workspace_id() or 'default'}:{key}"
