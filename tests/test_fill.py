"""Hermetic tests for CDP form fill policy and orchestration."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resume_tailor import config, data
from resume_tailor.apply import answer, browser, fill, packet, profile as profile_mod, store
from resume_tailor.apply.profile import ApplicantProfile
from resume_tailor.apply.packet import Packet
from resume_tailor.web.schemas import ApplySettings


@pytest.fixture
def fill_paths(tmp_path, monkeypatch):
    """Isolate store, job output, and applications output for fill tests."""
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    job_dir = tmp_path / "output" / "jobs" / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "run.json").write_text(
        json.dumps(
            {
                "job_id": "job-1",
                "metadata": {
                    "company": "Acme",
                    "role": "Intern",
                    "posting_url": "https://example.com/apply",
                    "ats": "greenhouse",
                },
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "jd.txt").write_text("Need Python.", encoding="utf-8")
    (job_dir / "requirements.json").write_text(
        '{"title":"Intern","seniority":"intern","keywords":[]}',
        encoding="utf-8",
    )
    (job_dir / "bullets.json").write_text('{"a":"Built APIs."}', encoding="utf-8")
    return tmp_path


def _ready_app(**overrides) -> store.Application:
    """Build a minimal application ready for fill."""
    data = {
        "source": "simplify",
        "source_job_id": "src-1",
        "company": "Acme",
        "role": "Intern",
        "posting_url": "https://example.com/apply",
        "final_url": "https://example.com/apply",
        "ats": "greenhouse",
        "status": "ready",
        "job_id": "job-1",
    }
    data.update(overrides)
    return store.Application(**data)


def test_decide_submit_action_policy_a():
    """Policy A: ATS in auto list and form ready → auto submit."""
    settings = ApplySettings(auto_submit_ats=["greenhouse"])
    assert (
        fill.decide_submit_action(
            ats="greenhouse",
            settings=settings,
            ready_to_submit=True,
        )
        == "auto_submit"
    )


def test_decide_submit_action_policy_b():
    """Policy B: ATS not listed or form incomplete → awaiting review."""
    settings = ApplySettings(auto_submit_ats=["greenhouse"])
    assert (
        fill.decide_submit_action(
            ats="lever",
            settings=settings,
            ready_to_submit=True,
        )
        == "awaiting_review"
    )
    assert (
        fill.decide_submit_action(
            ats="greenhouse",
            settings=settings,
            ready_to_submit=False,
        )
        == "awaiting_review"
    )


def test_decide_submit_action_workday_never_auto_submits():
    """Workday is excluded in code, even if explicitly listed in auto_submit_ats."""
    settings = ApplySettings(auto_submit_ats=["workday", "greenhouse"])
    assert (
        fill.decide_submit_action(
            ats="workday",
            settings=settings,
            ready_to_submit=True,
        )
        == "awaiting_review"
    )
    assert (
        fill.decide_submit_action(
            ats="Workday",
            settings=settings,
            ready_to_submit=True,
        )
        == "awaiting_review"
    )


def test_fill_application_auto_submit(fill_paths, monkeypatch):
    """End-to-end fill stub should mark the application submitted on policy A."""
    app = _ready_app()
    store.upsert(app)

    sample_packet = Packet(
        job_id="job-1",
        built_at="2026-01-01T00:00:00+00:00",
        posting_url="https://example.com/apply",
        company="Acme",
        role="Intern",
        ats="greenhouse",
        fields={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
        field_hints={"#submit_app": "submit", "confirmation_text": "Thank you"},
        artifacts={"resume_pdf": str(fill_paths / "resume.pdf")},
    )
    (fill_paths / "resume.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(packet, "build_packet", lambda job_id: sample_packet)
    monkeypatch.setattr(
        profile_mod,
        "load_profile",
        lambda: (ApplicantProfile(first_name="Ada"), False),
    )
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))

    filler_result = {
        "filled": [{"key": "first_name", "label": "First", "value": "Ada", "selector": "#first_name"}],
        "leftovers": [],
        "long_text": [],
        "file_inputs": [{"selector": "#resume", "label": "Resume"}],
        "required_empty": [],
        "frames_skipped": 0,
    }

    page = MagicMock()
    page.url = "https://example.com/apply"
    page.frames = [page]
    page.evaluate.side_effect = [filler_result, []]
    page.inner_text.return_value = "Thank you for applying"

    @contextmanager
    def _fake_browser():
        browser = MagicMock()
        browser.contexts = [MagicMock()]
        browser.contexts[0].new_page.return_value = page
        yield browser

    monkeypatch.setattr(browser, "cdp_browser", _fake_browser)

    result = fill.fill_application(
        "src-1",
        settings=ApplySettings(auto_submit_ats=["greenhouse"]),
    )

    assert result.status == "submitted"
    assert result.submit_action == "auto_submit"
    assert result.ready_to_submit is True
    updated = store.get("src-1")
    assert updated.status == "submitted"


def test_fill_application_awaiting_review(fill_paths, monkeypatch):
    """Policy B leaves the form open and sets ``awaiting_review`` status."""
    app = _ready_app(ats="lever")
    store.upsert(app)

    sample_packet = Packet(
        job_id="job-1",
        built_at="2026-01-01T00:00:00+00:00",
        ats="lever",
        fields={"email": "ada@example.com"},
        field_hints={},
    )
    monkeypatch.setattr(packet, "build_packet", lambda job_id: sample_packet)
    monkeypatch.setattr(
        profile_mod,
        "load_profile",
        lambda: (ApplicantProfile(), False),
    )
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))

    filler_result = {
        "filled": [],
        "leftovers": [{"label": "Phone", "type": "tel", "options": [], "required": True, "selector": "#phone"}],
        "long_text": [],
        "file_inputs": [],
        "required_empty": ["Phone"],
        "frames_skipped": 0,
    }

    page = MagicMock()
    page.url = "https://example.com/apply"
    page.frames = [page]
    page.evaluate.side_effect = [filler_result, ["Phone"]]

    @contextmanager
    def _fake_browser():
        browser = MagicMock()
        browser.contexts = [MagicMock()]
        browser.contexts[0].new_page.return_value = page
        yield browser

    monkeypatch.setattr(browser, "cdp_browser", _fake_browser)
    submit_called = {"value": False}
    original_click = MagicMock()

    def _track_click(*args, **kwargs):
        submit_called["value"] = True
        return original_click(*args, **kwargs)

    page.click = _track_click

    result = fill.fill_application(
        "src-1",
        settings=ApplySettings(auto_submit_ats=["greenhouse"]),
    )

    assert result.status == "awaiting_review"
    assert result.submit_action == "awaiting_review"
    assert submit_called["value"] is False
    assert store.get("src-1").status == "awaiting_review"


def test_fill_application_answer_stage_pinned_to_apply_settings_model(fill_paths, monkeypatch):
    """The long-text answer call is pinned to `ApplySettings.model_spec`, not `_ACTIVE`.

    Regression guard for the bug found 2026-09-21: `answer_question` runs outside the
    job queue, so without an explicit pin it silently falls through to
    `config.backend_for`'s hardcoded Claude default whenever `_ACTIVE` is empty.
    """
    app = _ready_app(ats="lever")
    store.upsert(app)

    sample_packet = Packet(
        job_id="job-1",
        built_at="2026-01-01T00:00:00+00:00",
        ats="lever",
        fields={"email": "ada@example.com"},
        field_hints={},
    )
    monkeypatch.setattr(packet, "build_packet", lambda job_id: sample_packet)
    monkeypatch.setattr(
        profile_mod, "load_profile", lambda: (ApplicantProfile(), False)
    )
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))

    filler_result = {
        "filled": [],
        "leftovers": [],
        "long_text": [{"label": "Why us?", "maxlength": 500, "selector": "#why"}],
        "file_inputs": [],
        "required_empty": [],
        "frames_skipped": 0,
    }
    page = MagicMock()
    page.url = "https://example.com/apply"
    page.frames = [page]
    page.evaluate.side_effect = [filler_result, []]

    @contextmanager
    def _fake_browser():
        browser = MagicMock()
        browser.contexts = [MagicMock()]
        browser.contexts[0].new_page.return_value = page
        yield browser

    monkeypatch.setattr(browser, "cdp_browser", _fake_browser)

    seen: dict[str, str] = {}

    def _fake_answer_question(question, **kwargs):
        backend = config.backend_for("answer")
        seen["origin"] = backend.origin
        seen["model"] = backend.model
        return answer.AnswerResult(answer="", warnings=[], source="model", offenders=[])

    monkeypatch.setattr(answer, "answer_question", _fake_answer_question)

    config._ACTIVE.clear()  # a real bug would resolve to Claude here
    fill.fill_application(
        "src-1",
        settings=ApplySettings(model_provider="lmstudio", model_name="some-test-model"),
    )

    assert seen == {"origin": "lmstudio", "model": "some-test-model"}


def test_fill_application_failure_sets_fill_failed(fill_paths, monkeypatch):
    """Exceptions during CDP fill should persist ``fill_failed`` on the application."""
    app = _ready_app()
    store.upsert(app)

    monkeypatch.setattr(
        packet,
        "build_packet",
        lambda job_id: Packet(
            job_id="job-1",
            built_at="2026-01-01T00:00:00+00:00",
            fields={},
            field_hints={},
        ),
    )
    monkeypatch.setattr(
        profile_mod,
        "load_profile",
        lambda: (ApplicantProfile(), False),
    )
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))

    @contextmanager
    def _broken_browser():
        raise RuntimeError("CDP unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(browser, "cdp_browser", _broken_browser)

    result = fill.fill_application("src-1")
    assert result.status == "fill_failed"
    assert "CDP unreachable" in (result.error or "")
    assert store.get("src-1").status == "fill_failed"
    assert store.get("src-1").status == "fill_failed"
