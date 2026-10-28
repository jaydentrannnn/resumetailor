"""A Continue fill replaces the app's own outdated upload and keeps the applicant's files."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import (
    fill_answers,
    fill_finish,
    fill_outcomes,
    fill_widgets,
    upload_replace,
)
from resume_tailor.apply.funnel.store_models import FillResult

OLD_SHA = "0" * 64
STAGED = "Ada Lovelace Resume - Intern.pdf"


@pytest.mark.parametrize(
    ("prior", "shown", "current", "expected"),
    [
        ({"uploaded_by_app": True, "filename": STAGED, "artifact_sha256": OLD_SHA}, STAGED,
         "1" * 64, "stale"),
        ({"uploaded_by_app": True, "filename": STAGED, "artifact_sha256": OLD_SHA}, STAGED,
         OLD_SHA, "current"),
        # Another file in the same slot, or a record from before the app kept one.
        ({"uploaded_by_app": True, "filename": STAGED, "artifact_sha256": OLD_SHA},
         "my_resume.pdf", "1" * 64, "theirs"),
        ({"filename": STAGED, "verified": True}, STAGED, "1" * 64, "theirs"),
        # No digest to compare on one side: the app cannot tell (audit #33), so the
        # file is kept for the applicant to check rather than claimed as current.
        ({"uploaded_by_app": True, "filename": STAGED}, STAGED, "1" * 64, "ambiguous"),
        ({"uploaded_by_app": True, "filename": STAGED, "artifact_sha256": OLD_SHA}, STAGED,
         "", "ambiguous"),
    ],
)
def test_attached_by_app_reads_the_upload_record(prior, shown, current, expected):
    assert upload_replace.attached_by_app(
        [{"purpose": "resume", **prior}], "resume", shown, current
    ) == expected


def test_a_file_the_applicant_attached_is_theirs_under_the_apps_name():
    """Audit #33: they replaced the app's upload with their own copy of that name."""
    prior = [{"purpose": "resume", "uploaded_by_app": True, "filename": STAGED,
              "artifact_sha256": OLD_SHA}]
    assert upload_replace.attached_by_app(prior, "resume", STAGED, "1" * 64, [STAGED]) == "theirs"


class _Target:
    """An upload frame: ``listed`` is the filename text its widget shows."""

    def __init__(self, listed: str = ""):
        self.listed = listed

    def get_by_text(self, name, **_kwargs):
        return SimpleNamespace(count=lambda: int(bool(self.listed) and name in self.listed))


def _run(tmp_path, monkeypatch, *, prior=(), input_holds="", listed="", removed=True,
         sticks=True):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 current")
    run = fill_answers._FillAnswers.__new__(fill_answers._FillAnswers)
    target = _Target(listed)
    run.page, run.frames, run.hints = target, [target], {}
    run.uploads, run.uploaded_controls = [], set()
    run.verified_purposes, run.attempted_purposes = set(), set()
    run.settings = SimpleNamespace(cover_letter_mode="never")
    run.pkt = SimpleNamespace(artifacts={"resume_pdf": str(resume)}, role="Intern")
    run.app = SimpleNamespace(role="Intern")
    run.applicant_name, run.out_dir = "Ada Lovelace", tmp_path / "out"
    run.previous_fill = FillResult(uploads=[{"purpose": "resume", **item} for item in prior])
    run.lines, run.on_progress = [], None
    run.progress = run.lines.append
    sent: list[str] = []
    monkeypatch.setattr(fill_outcomes, "_attached_filename", lambda _t, _sel: input_holds)
    monkeypatch.setattr(fill_widgets, "_set_and_verify_file",
                        lambda _t, _sel, path: sent.append(Path(path).name) or sticks)
    removals: list[str] = []
    monkeypatch.setattr(upload_replace, "remove_listed",
                        lambda _t, name: removals.append(name) or removed)
    run._upload_one({"selector": "#resume", "label": "Resume"})  # noqa: SLF001
    return run, sent, removals, upload_replace.artifact_sha256(resume)


OURS = {"uploaded_by_app": True, "filename": STAGED, "artifact_sha256": OLD_SHA}


@pytest.mark.parametrize("where", ["input", "listed"])
def test_the_apps_outdated_upload_is_replaced(tmp_path, monkeypatch, where):
    run, sent, removals, sha = _run(
        tmp_path, monkeypatch, prior=[OURS],
        input_holds=STAGED if where == "input" else "", listed=STAGED if where == "listed" else "",
    )
    assert sent == [STAGED]
    # A native input swaps its file on upload; a listing widget has the old one removed.
    assert removals == ([STAGED] if where == "listed" else [])
    (record,) = run.uploads
    assert record["verified"] and record["uploaded_by_app"] and record["artifact_sha256"] == sha
    assert record["reason"] == upload_replace.REPLACED_NOTE


def test_an_outdated_upload_that_cannot_be_removed_is_not_uploaded_twice(tmp_path, monkeypatch):
    run, sent, _removals, _sha = _run(tmp_path, monkeypatch, prior=[OURS], listed=STAGED,
                                      removed=False)
    assert sent == []
    (record,) = run.uploads
    assert not record["verified"] and record["error"] == upload_replace.NOT_REPLACED_NOTE


@pytest.mark.parametrize("why", ["not removed", "input refused the new file"])
def test_a_failed_replacement_keeps_the_old_file_known_as_the_apps(tmp_path, monkeypatch, why):
    """The next Continue tries again instead of keeping the outdated file as the
    applicant's own."""
    run, _sent, _removals, sha = _run(
        tmp_path, monkeypatch, prior=[OURS],
        listed=STAGED if why == "not removed" else "",
        input_holds=STAGED if why != "not removed" else "",
        removed=False, sticks=False,
    )
    (record,) = run.uploads
    assert not record["verified"]
    assert record["filename"] == STAGED and record["artifact_sha256"] == OLD_SHA
    assert upload_replace.attached_by_app(run.uploads, "resume", STAGED, sha) == "stale"


def test_the_apps_current_upload_is_kept(tmp_path, monkeypatch):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 current")  # what `_run` writes again
    pinned = str(tmp_path / "fills" / "1" / "resume_pdf" / "resume.pdf")
    prior = [{**OURS, "artifact_sha256": upload_replace.artifact_sha256(resume),
              "artifact_path": pinned}]
    run, sent, removals, _sha = _run(tmp_path, monkeypatch, prior=prior, listed=STAGED)
    assert sent == [] and removals == []
    (record,) = run.uploads
    assert record["state"] == "preserved" and record["uploaded_by_app"]
    # The exact file on the form stays named, for "What was sent" (audit review #7).
    assert record["artifact_path"] == pinned


@pytest.mark.parametrize(
    ("prior", "input_holds"),
    [([], "my_own_resume.pdf"), ([OURS], "my_own_resume.pdf"), ([{"filename": STAGED}], STAGED)],
)
def test_a_file_the_app_did_not_upload_is_kept(tmp_path, monkeypatch, prior, input_holds):
    run, sent, removals, _sha = _run(tmp_path, monkeypatch, prior=prior, input_holds=input_holds)
    assert sent == [] and removals == []
    (record,) = run.uploads
    assert record["state"] == "kept_existing" and record["verified"]
    assert "uploaded_by_app" not in record


def test_a_fresh_upload_records_that_the_app_made_it(tmp_path, monkeypatch):
    run, sent, _removals, sha = _run(tmp_path, monkeypatch)
    assert sent == [STAGED]
    (record,) = run.uploads
    assert record["uploaded_by_app"] and record["artifact_sha256"] == sha
    assert "reason" not in record


def _seen_off_its_step(tmp_path, prior, touched=()):
    """Continue on a page that only shows the earlier upload (Workday's Review step)."""
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 current")
    run = fill_finish._FillFinish.__new__(fill_finish._FillFinish)
    run.pkt = SimpleNamespace(artifacts={"resume_pdf": str(resume)})
    run.fill_mode, run.uploads = "continue", []
    run.previous_fill = FillResult(uploads=[{"purpose": "resume", **prior}],
                                   user_touched_uploads=list(touched))
    run._filename_visible = lambda _name: True  # noqa: SLF001
    run._verify_uploads()  # noqa: SLF001
    (record,) = run.uploads
    return record


def test_an_outdated_upload_seen_off_its_step_is_not_verified(tmp_path):
    record = _seen_off_its_step(tmp_path, OURS)
    assert not record["verified"] and record["error"] == upload_replace.EARLIER_STEP_NOTE
    assert record["uploaded_by_app"]  # the next Continue still knows it is the app's


def test_a_current_upload_seen_off_its_step_keeps_its_pinned_copy(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 current")  # what `_seen_off_its_step` writes again
    pinned = str(tmp_path / "fills" / "1" / "resume_pdf" / "resume.pdf")
    record = _seen_off_its_step(tmp_path, {
        **OURS, "artifact_sha256": upload_replace.artifact_sha256(resume), "artifact_path": pinned,
    })
    assert record["verified"] and record["artifact_path"] == pinned


@pytest.mark.parametrize("why", ["replaced by the applicant", "no version on record"])
def test_a_file_seen_off_its_step_the_app_cannot_vouch_for_is_never_recorded_as_its_own(
    tmp_path, why
):
    """The applicant replaced the app's upload under its name (or the app kept no hash):
    "What was sent" must not keep the app's old pinned copy as what the form has."""
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 current")
    pinned = str(tmp_path / "fills" / "1" / "resume_pdf" / "resume.pdf")
    prior = {**OURS, "artifact_sha256": upload_replace.artifact_sha256(resume),
             "artifact_path": pinned}
    if why == "no version on record":
        del prior["artifact_sha256"]
    record = _seen_off_its_step(
        tmp_path, prior, touched=[STAGED] if why == "replaced by the applicant" else ()
    )
    assert record["verified"] and record["state"] == "kept_existing"
    assert not {"uploaded_by_app", "artifact_sha256", "artifact_path"} & set(record)
    if why == "no version on record":
        assert record["reason"] == upload_replace.AMBIGUOUS_NOTE


def test_a_file_seen_off_its_step_that_the_app_did_not_upload_is_kept(tmp_path):
    record = _seen_off_its_step(tmp_path, {"filename": STAGED})
    assert record["verified"] and record["state"] == "kept_existing"


def test_remove_clicks_are_text_checked():
    loc = SimpleNamespace(evaluate=lambda *_a, **_k: "Submit application", click=lambda **_k: None)
    with pytest.raises(clicks.SubmitRefused):
        clicks.safe_click(loc, purpose="remove")


# -- the remove control is found inside the upload component only (real browser) ---------


@pytest.fixture
def page():
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True, channel="msedge")
            except Exception:  # noqa: BLE001
                path = os.environ.get("PW_CHROMIUM_PATH")
                browser = playwright.chromium.launch(headless=True, executable_path=path or None)
            try:
                yield browser.new_page()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Local Chromium unavailable: {exc}")


# One step holds both a work-experience row (with its own Delete) and the upload widget.
_WORKDAY_STEP = f"""
<div data-automation-id="applyFlowMyExpPage">
<div data-automation-id="workExperience-1">
  <input aria-label="Job Title" value="Analyst">
  <button onclick="this.parentElement.remove()">Delete</button>
</div>
<div data-automation-id="attachments-FileUpload">
  <input type="file" data-automation-id="file-upload-input-ref">
  <div data-automation-id="file-upload-item">
    <div data-automation-id="file-upload-item-name">{STAGED}</div>
    <button data-automation-id="delete-file" aria-label="Delete {STAGED}"
            onclick="this.closest('[data-automation-id=file-upload-item]').remove()"></button>
  </div>
</div>
</div>
"""


def test_the_listed_file_is_removed_by_its_own_delete_control(page):
    page.set_content(_WORKDAY_STEP)
    assert upload_replace.remove_listed(page, STAGED)
    assert page.locator("[data-automation-id=workExperience-1] input").count() == 1


def test_a_widget_without_a_remove_control_is_left_alone(page):
    page.set_content(_WORKDAY_STEP.replace('data-automation-id="delete-file"', "")
                     .replace(f'aria-label="Delete {STAGED}"', ""))
    assert not upload_replace.remove_listed(page, STAGED)
    assert page.get_by_text(STAGED).count() == 1
    assert page.locator("[data-automation-id=workExperience-1]").count() == 1


def test_a_file_without_a_recorded_version_is_kept_for_the_applicant(tmp_path, monkeypatch):
    run, sent, removals, _sha = _run(
        tmp_path, monkeypatch, prior=[{"uploaded_by_app": True, "filename": STAGED}],
        listed=STAGED,
    )
    assert sent == [] and removals == []
    (record,) = run.uploads
    assert record["state"] == "kept_existing"
    assert record["reason"] == upload_replace.AMBIGUOUS_NOTE
