"""Cover letters by Apply's `cover_letter_mode`: which fields get one, written once per
job, the same rule for uploads and text boxes, and never failing the fill."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from resume_tailor import config
from resume_tailor.apply.forms import fill_answers, fill_finish, fill_outcomes, fill_widgets
from resume_tailor.apply.funnel import cover_on_demand
from resume_tailor.web import job_followups
from resume_tailor.web.schemas import ApplySettings


@pytest.fixture
def job(monkeypatch, tmp_path):
    """A job directory, a regeneration stub that writes ``cover.pdf``, and a packet
    rebuild that reads the directory back."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    job_dir = tmp_path / "jobs" / "j1"
    job_dir.mkdir(parents=True)
    calls: list[str] = []

    def regenerate(job_id: str):
        calls.append(job_id)
        (job_dir / "cover.pdf").write_bytes(b"%PDF")

    def write_packet(job_id: str):
        cover = job_dir / "cover.pdf"
        artifacts = {"cover_pdf": str(cover)} if cover.is_file() else {}
        return SimpleNamespace(
            artifacts=artifacts, cover_letter="Body." if artifacts else "", preparation="fresh"
        )

    monkeypatch.setattr(job_followups, "regenerate_cover_letter", regenerate)
    monkeypatch.setattr(cover_on_demand.packet_mod, "write_packet", write_packet)
    return job_dir, calls


def _packet(**artifacts: str) -> SimpleNamespace:
    return SimpleNamespace(
        job_id="j1", role="Analyst", artifacts={"resume_pdf": "r.pdf", **artifacts},
        cover_letter="",
        preparation="old",
    )


def test_ensure_writes_once_and_updates_the_packet(job):
    job_dir, calls = job
    pkt = _packet()
    assert cover_on_demand.ensure(pkt)
    assert pkt.artifacts["cover_pdf"] == str(job_dir / "cover.pdf")
    assert pkt.cover_letter == "Body." and pkt.preparation == "fresh"
    assert cover_on_demand.ensure(_packet()) and calls == ["j1"]  # on disk: reused


def test_ensure_keeps_an_existing_letter(job):
    _, calls = job
    assert cover_on_demand.ensure(_packet(cover_pdf="old.pdf"))
    assert calls == []


def test_a_failed_draft_returns_false(job, monkeypatch):
    def fail(job_id):
        raise RuntimeError("model unreachable")

    monkeypatch.setattr(job_followups, "regenerate_cover_letter", fail)
    pkt = _packet()
    assert not cover_on_demand.ensure(pkt)
    assert "cover_pdf" not in pkt.artifacts


def _fill(tmp_path: Path, *, mode: str) -> fill_answers._FillAnswers:
    run = fill_answers._FillAnswers.__new__(fill_answers._FillAnswers)
    run.page = SimpleNamespace(get_by_text=lambda *a, **k: SimpleNamespace(count=lambda: 0))
    run.frames = [run.page]
    run.hints = {}
    run.uploads = []
    run.uploaded_controls = set()
    run.attempted_purposes = set()
    run.verified_purposes = set()
    run.cover_waiting = []
    run.pkt = _packet()
    run.settings = ApplySettings(cover_letter_mode=mode)
    run.needs_review = []
    run.long_text_answers = {}
    run.on_progress = None
    run.on_deadline = None
    run.started = time.monotonic()
    run.deadline = run.started + 240
    run.applicant_name = "Ada Lovelace"
    run.app = SimpleNamespace(role="Analyst")
    run.out_dir = tmp_path
    return run


@pytest.fixture
def browser(monkeypatch):
    uploaded: list[str] = []
    monkeypatch.setattr(fill_outcomes, "_attached_filename", lambda target, sel: "")
    monkeypatch.setattr(fill_widgets, "_stage_attachment", lambda path, **kwargs: path)

    def set_file(target, selector, path):
        uploaded.append(path)
        return True

    monkeypatch.setattr(fill_widgets, "_set_and_verify_file", set_file)
    return uploaded


def _cover_input(*, required: bool) -> dict:
    return {"selector": "#cover", "label": "Cover Letter", "required": required}


def test_an_optional_cover_field_is_left_empty(job, browser, tmp_path):
    _, calls = job
    run = _fill(tmp_path, mode="required")
    run._upload_one(_cover_input(required=False))
    assert calls == [] and browser == []
    assert run.uploads[0]["state"] == "not_requested"
    assert run.uploads[0]["reason"] == "Skipped: optional cover letter; setting is required"
    assert run.uploads[0]["cover_letter_mode"] == "required"


def test_a_required_cover_field_gets_a_letter_written_and_uploaded(job, browser, tmp_path):
    job_dir, calls = job
    run = _fill(tmp_path, mode="required")
    run._upload_one(_cover_input(required=True))
    # Written in the background while the step goes on; attached at the step's end.
    assert run.cover_waiting == [_cover_input(required=True)] and browser == []
    run._attach_waiting_covers()
    assert calls == ["j1"]
    assert browser == [str(job_dir / "cover.pdf")]
    assert run.uploads[0]["verified"] is True
    assert run.uploads[0]["reason"] == cover_on_demand.GENERATED_NOTE


def test_the_step_goes_on_while_the_letter_is_written(job, browser, tmp_path, monkeypatch):
    job_dir, calls = job
    started, release = threading.Event(), threading.Event()
    slow = job_followups.regenerate_cover_letter

    def regenerate(job_id: str):
        started.set()
        release.wait(5)
        slow(job_id)

    monkeypatch.setattr(job_followups, "regenerate_cover_letter", regenerate)
    run = _fill(tmp_path, mode="optional")
    run._upload_one(_cover_input(required=False))
    # The same input found again by another selector waits on the one letter.
    run._upload_one({**_cover_input(required=False), "selector": "input[type='file']#cover"})
    assert started.wait(5) and browser == [] and len(run.cover_waiting) == 1
    release.set()
    run._attach_waiting_covers()
    assert calls == ["j1"] and browser == [str(job_dir / "cover.pdf")]
    assert [upload["purpose"] for upload in run.uploads] == ["cover_letter"]


def test_a_letter_that_failed_in_the_background_is_not_written_again(job, browser, tmp_path,
                                                                     monkeypatch):
    attempts: list[str] = []

    def fail(job_id: str):
        attempts.append(job_id)
        raise RuntimeError("model unreachable")

    monkeypatch.setattr(job_followups, "regenerate_cover_letter", fail)
    run = _fill(tmp_path, mode="required")
    run._upload_one(_cover_input(required=True))
    run._attach_waiting_covers()
    assert attempts == ["j1"] and browser == []
    assert run.uploads[0]["verified"] is False and "cover letter" in run.uploads[0]["error"]


def test_with_cover_letters_off_a_required_field_reports_the_missing_letter(job, browser, tmp_path):
    _, calls = job
    run = _fill(tmp_path, mode="off")
    run._upload_one(_cover_input(required=True))
    assert calls == [] and browser == []
    assert run.uploads[0]["verified"] is False and "cover letter" in run.uploads[0]["error"]


def test_a_skipped_optional_field_does_not_block_readiness():
    resume = {"purpose": "resume", "verified": True}
    skipped = {"purpose": "cover_letter", "verified": False, "state": "not_requested"}
    missing = {"purpose": "cover_letter", "verified": False, "error": "No cover letter"}
    assert not fill_finish.upload_failed([resume, skipped])
    assert fill_finish.upload_failed([resume, missing])


@pytest.mark.parametrize(
    ("mode", "required", "has_letter", "action"),
    [
        ("off", True, False, "missing"),
        ("off", True, True, "use"),
        ("off", False, True, "skip"),
        ("required", True, False, "write"),
        ("required", False, False, "skip"),
        ("required", False, True, "skip"),
        ("optional", False, False, "write"),
        ("every", False, False, "write"),
        ("every", False, True, "use"),
    ],
)
def test_plan(mode, required, has_letter, action):
    assert cover_on_demand.plan(mode, required=required, has_letter=has_letter) == action


def test_the_old_switch_keeps_its_meaning():
    assert ApplySettings.model_validate({"cover_letter": True}).cover_letter_mode == "required"
    assert ApplySettings.model_validate({"cover_letter": False}).cover_letter_mode == "off"
    assert ApplySettings().cover_letter_mode == "required"
    assert "cover_letter" not in ApplySettings(cover_letter=True).model_dump()


def test_a_cover_letter_text_box_follows_the_upload_rule(job, tmp_path, monkeypatch):
    _, calls = job
    typed: list[str] = []
    run = _fill(tmp_path, mode="required")
    monkeypatch.setattr(run, "_fill_if_empty", lambda item, text: typed.append(text), raising=False)
    run._answer_one_long_text({"label": "Cover letter", "required": False}, "Cover letter")
    assert calls == [] and typed == [] and run.needs_review == []

    run._answer_one_long_text({"label": "Cover letter", "required": True}, "Cover letter")
    assert calls == ["j1"] and typed == ["Body."]


def test_with_cover_letters_off_a_required_text_box_is_left_for_review(job, tmp_path):
    _, calls = job
    run = _fill(tmp_path, mode="off")
    run._answer_one_long_text({"label": "Cover Letter", "required": True}, "Cover Letter")
    assert calls == [] and run.needs_review == ["Cover Letter"]


@pytest.mark.parametrize("required", [False, True])
def test_fallback_cover_input_keeps_required_metadata(tmp_path, required):
    run = _fill(tmp_path, mode="required")
    run.merged = {"file_inputs": []}
    def locator(selector):
        return SimpleNamespace(
            count=lambda: int(selector == "input[type='file']#cover_letter"),
            first=SimpleNamespace(evaluate=lambda _script: required),
        )
    run.page = SimpleNamespace(locator=locator)
    assert run._file_inputs() == [{
        "selector": "input[type='file']#cover_letter", "label": "Cover Letter", "required": required,
    }]


def test_a_background_letter_stays_with_its_profile(tmp_path, monkeypatch):
    """v1.24.0: a letter a timed-out fill left running rebuilt its packet in the profile
    switched to meanwhile. It is pinned to its own, and `busy` until it is done."""
    first, second = tmp_path / "first", tmp_path / "second"
    monkeypatch.setattr(config, "OUTPUT_DIR", first)
    release = threading.Event()
    seen: list[Path] = []

    def regenerate(job_id: str):
        assert release.wait(3)
        seen.append(config.OUTPUT_DIR)
        job_dir = config.OUTPUT_DIR / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "cover.pdf").write_bytes(b"%PDF")

    def write_packet(job_id: str):
        seen.append(config.OUTPUT_DIR)
        cover = config.OUTPUT_DIR / "jobs" / job_id / "cover.pdf"
        return SimpleNamespace(
            artifacts={"cover_pdf": str(cover)}, cover_letter="Body.", preparation="fresh"
        )

    monkeypatch.setattr(job_followups, "regenerate_cover_letter", regenerate)
    monkeypatch.setattr(cover_on_demand.packet_mod, "write_packet", write_packet)
    future = cover_on_demand.start(_packet())
    assert cover_on_demand.busy()
    monkeypatch.setattr(config, "OUTPUT_DIR", second)  # another profile is active now
    release.set()
    assert future.result(timeout=3)
    assert seen == [first, first]
    assert (first / "jobs" / "j1" / "cover.pdf").is_file() and not second.exists()
    assert not cover_on_demand.busy()
