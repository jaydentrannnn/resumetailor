"""Application logging: a rotating JSON-lines file with PII and secrets redacted.

`setup_logging()` is called once per process (the web lifespan, `tailor.py main`). Every
record passes through `RedactingFilter` before any handler writes it, so an email,
phone number, API key or password that reaches a log message never lands on disk.
`run_context()` tags records with the job/operation they belong to, which is what makes
"Copy diagnostics" useful for one failed run.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

LOG_FILENAME = "app.log"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 5

#: Current job/operation id, attached to every record logged inside `run_context`.
_RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar("rt_run_id", default="")

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Secrets first: a key can contain digit runs the phone rule would half-eat.
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "[api-key]"),
    (re.compile(r"\b(?:sk|AIza)[A-Za-z0-9_\-]{16,}"), "[api-key]"),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|password|passwd|secret|token|authorization)"
            r"[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"
        ),
        r"\1[redacted]",
    ),
    # The session token in a sign-in link (`web/security.py`).
    (re.compile(r"([?&]t=)[A-Za-z0-9_\-]{8,}"), r"\1[redacted]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email]"),
    (
        re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),
        "[phone]",
    ),
)


def redact(text: str) -> str:
    """Replace emails, phone numbers, API keys and `password=…`-style values."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrite each record's rendered message (and traceback) in place, redacted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string must not drop the record
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        record.run_id = _RUN_ID.get()
        return True


class JsonLinesFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, run id, message, traceback."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "at": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "run_id": getattr(record, "run_id", ""),
            "message": record.getMessage(),
        }
        if record.exc_text:
            payload["traceback"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False)


_configured_dir: Path | None = None


def log_dir() -> Path | None:
    """Directory `setup_logging` writes to, or None when logging was never set up."""
    return _configured_dir


def setup_logging(directory: Path, *, level: int = logging.INFO) -> Path:
    """Attach the redacting rotating file handler to the root logger. Idempotent."""
    global _configured_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOG_FILENAME
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_resume_tailor", False):
            return path
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    handler._resume_tailor = True  # type: ignore[attr-defined]
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonLinesFormatter())
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    _configured_dir = directory
    return path


@contextmanager
def run_context(run_id: str) -> Iterator[None]:
    """Tag every record logged inside the block with `run_id`."""
    token = _RUN_ID.set(run_id)
    try:
        yield
    finally:
        _RUN_ID.reset(token)


def call_in_context(run_id: str, fn, *args, **kwargs):
    """Thread-target helper: run `fn(*args, **kwargs)` inside `run_context(run_id)`."""
    with run_context(run_id):
        return fn(*args, **kwargs)


def log_files() -> list[Path]:
    """Current log file plus rotated backups, newest first."""
    if _configured_dir is None:
        return []
    base = _configured_dir / LOG_FILENAME
    rotated = (base.with_name(f"{LOG_FILENAME}.{i}") for i in range(1, _BACKUPS + 1))
    return [path for path in (base, *rotated) if path.is_file()]
