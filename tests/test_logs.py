"""App log: redaction, JSON lines, run ids, and the diagnostics bundle."""

from __future__ import annotations

import io
import json
import logging
import zipfile

import pytest

from resume_tailor import logs


@pytest.mark.parametrize(
    ("raw", "hidden"),
    [
        ("contact alex@example.com now", "alex@example.com"),
        ("call (555) 010-0199 please", "010-0199"),
        ("key sk-ant-api03-abcdefghijklmnop", "abcdefghijklmnop"),
        ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
        ("GEMINI key AIzaSyA1234567890abcdefghij", "AIzaSyA1234567890abcdefghij"),
    ],
)
def test_redact_hides_pii_and_secrets(raw: str, hidden: str) -> None:
    assert hidden not in logs.redact(raw)


def test_redact_keeps_ordinary_numbers() -> None:
    assert logs.redact("rendered 2 pages in 14 iterations") == "rendered 2 pages in 14 iterations"


@pytest.fixture
def log_setup(tmp_path, monkeypatch):
    root = logging.getLogger()
    before = list(root.handlers)
    monkeypatch.setattr(logs, "_configured_dir", None)
    path = logs.setup_logging(tmp_path)
    yield path
    for handler in list(root.handlers):
        if handler not in before:
            root.removeHandler(handler)
            handler.close()


def test_file_is_json_lines_with_run_id_and_redaction(log_setup) -> None:
    log = logging.getLogger("resume_tailor.test")
    with logs.run_context("job123"):
        log.warning("failed for %s", "alex@example.com")
    try:
        raise ValueError("password=topsecret99")
    except ValueError:
        log.exception("boom")
    lines = [json.loads(line) for line in log_setup.read_text(encoding="utf-8").splitlines()]
    first, second = lines[-2], lines[-1]
    assert first["run_id"] == "job123"
    assert "alex@example.com" not in first["message"]
    assert second["run_id"] == ""
    assert "topsecret99" not in second["traceback"]


def test_setup_is_idempotent(log_setup, tmp_path) -> None:
    count = sum(getattr(h, "_resume_tailor", False) for h in logging.getLogger().handlers)
    logs.setup_logging(tmp_path)
    assert sum(getattr(h, "_resume_tailor", False) for h in logging.getLogger().handlers) == count


def test_diagnostics_bundle_contents(log_setup) -> None:
    from resume_tailor.web.routes import diagnostics

    logging.getLogger("resume_tailor.test").warning("hello from test")
    data = diagnostics.build_bundle()
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        names = set(bundle.namelist())
        assert {"summary.json", "settings.redacted.json", "logs/app.log"} <= names
        summary = json.loads(bundle.read("summary.json"))
        assert "backends" in summary and "calibration" in summary
