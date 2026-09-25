"""Hermetic tests for CDP form fill policy and orchestration."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resume_tailor import config, data
from resume_tailor.apply import answer, browser, clicks, fill, packet, store, submit_guard, wizards
from resume_tailor.apply import profile as profile_mod
from resume_tailor.apply.packet import Packet
from resume_tailor.apply.profile import ApplicantProfile
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
                "status": "succeeded",
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
    (job_dir / "tailored.pdf").write_bytes(b"%PDF-1.4 prepared")
    (job_dir / "cover.pdf").write_bytes(b"%PDF-1.4 prepared cover")
    (job_dir / "expansion.json").write_text(
        '{"entries":[{"entry_key":"exp:one","title":"Intern","company":"Acme",'
        '"location":"Remote","start":"2025-01","end":"present",'
        '"bullets":["Built APIs."],"char_count":13}]}', encoding="utf-8",
    )
    return tmp_path


def test_stage_attachment_uses_user_facing_resume_and_cover_names(tmp_path):
    """ATS uploads expose descriptive names instead of internal artifact basenames."""
    resume = tmp_path / "tailored.pdf"
    cover = tmp_path / "cover.pdf"
    resume.write_bytes(b"resume")
    cover.write_bytes(b"cover")

    staged_resume = fill._stage_attachment(  # noqa: SLF001
        str(resume),
        purpose="resume",
        applicant_name="Ada Lovelace",
        role="Software Intern",
        out_dir=tmp_path / "application",
    )
    staged_cover = fill._stage_attachment(  # noqa: SLF001
        str(cover),
        purpose="cover_letter",
        applicant_name="Ada Lovelace",
        role="Software Intern",
        out_dir=tmp_path / "application",
    )

    assert staged_resume.endswith("Ada Lovelace Resume - Software Intern.pdf")
    assert staged_cover.endswith("Ada Lovelace Cover Letter - Software Intern.pdf")
    assert (tmp_path / "application" / "attachments" / "Ada Lovelace Resume - Software Intern.pdf").read_bytes() == b"resume"
    assert (tmp_path / "application" / "attachments" / "Ada Lovelace Cover Letter - Software Intern.pdf").read_bytes() == b"cover"


def test_greenhouse_cover_letter_input_is_classified_by_name():
    assert (
        fill._attachment_purpose(  # noqa: SLF001
            "",
            "input[name=\"job_application[cover_letter]\"]",
            {},
        )
        == "cover_letter"
    )


def test_workday_generic_upload_is_the_resume_by_hint_or_section():
    # Philips/Upbound: "Upload a file (5MB max)" under a "Resume/CV" heading. The hint
    # selector is written with single quotes, filler.js with double quotes.
    selector = 'input[data-automation-id="file-upload-input-ref"]'
    hints = {"input[data-automation-id='file-upload-input-ref']": "resume_upload"}
    label = "Upload a file (5MB max)*"
    assert fill._attachment_purpose(label, selector, hints) is None  # noqa: SLF001
    assert fill._attachment_purpose(label, selector, hints, hint_key="resume_upload") == "resume"  # noqa: SLF001
    assert fill._attachment_purpose(label, selector, {}, section="Resume/CV") == "resume"  # noqa: SLF001
    assert fill._attachment_purpose(label, selector, {}, section="Cover Letter") == "cover_letter"  # noqa: SLF001


def test_upload_verified_when_react_replaces_file_input(tmp_path):
    """Greenhouse removes an input after upload but renders the selected filename."""
    file_path = tmp_path / "Ada Resume.pdf"
    file_path.write_bytes(b"resume")
    target = MagicMock()
    control = target.locator.return_value.first
    control.evaluate.side_effect = RuntimeError("input removed after upload")
    target.get_by_text.return_value.count.return_value = 1
    assert fill._set_and_verify_file(target, "#resume", str(file_path))  # noqa: SLF001
    control.set_input_files.assert_called_once_with(str(file_path), timeout=5000)
    target.get_by_text.return_value.first.wait_for.assert_called_once_with(state="visible", timeout=3000)


def test_availability_after_program_start_is_reported():
    note = fill._availability_note("2027-06-14", "10-Week paid internship June 1, 2027- August 6, 2027")  # noqa: SLF001
    assert note and "2027-06-14" in note and "2027-06-01" in note
    assert fill._availability_note("2027-06-01", "paid internship June 1, 2027") is None  # noqa: SLF001


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
    settings = ApplySettings(auto_submit_enabled=True, auto_submit_ats=["greenhouse"])
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


def test_decide_submit_action_never_auto_submits_workday():
    """Workday is always handed over for review, even when listed and verified
    (`ApplySettings.auto_submit_max_per_run`'s documented exclusion)."""
    settings = ApplySettings(auto_submit_enabled=True, auto_submit_ats=["workday", "greenhouse"])
    for ats in ("workday", "Workday"):
        assert fill.decide_submit_action(ats=ats, settings=settings, ready_to_submit=True) == "awaiting_review"
    assert fill.decide_submit_action(ats="greenhouse", settings=settings, ready_to_submit=True) == "auto_submit"


@pytest.mark.parametrize("ats", ["linkedin", "indeed", "handshake", "LinkedIn"])
def test_job_board_apply_flows_are_assist_only(ats):
    """LinkedIn Easy Apply, Indeed Apply and Handshake are filled, never auto-submitted."""
    settings = ApplySettings(auto_submit_enabled=True, auto_submit_ats=[ats.lower()])
    assert fill.decide_submit_action(ats=ats, settings=settings, ready_to_submit=True) == "awaiting_review"
    assert (
        fill.decide_submit_action(
            ats=ats, settings=settings, ready_to_submit=True, submit_mode="auto_submit"
        )
        == "awaiting_review"
    )


def _stub_greenhouse_form(fill_paths, monkeypatch, **app_fields):
    """A ready Greenhouse application whose form fills cleanly and confirms on submit."""
    app = _ready_app(**app_fields)
    monkeypatch.setattr(fill, "_find_submit_button", lambda _page, _hints: MagicMock())  # noqa: SLF001
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
    def evaluate_form(script, args=None):
        if script == fill._load_filler_js():  # noqa: SLF001
            return filler_result if args and args.get("fields") else {"filled": [{"key": "existing", "label": "First", "value": "Ada", "selector": "#first_name"}], "leftovers": []}
        if script == fill._load_readiness_js():  # noqa: SLF001
            return []
        return {"errors": [], "unresolved": [], "advance_disabled": False}

    page.evaluate.side_effect = evaluate_form
    page.inner_text.side_effect = ["Application form", "Thank you for applying"]
    page.screenshot.side_effect = lambda path, **_: Path(path).write_bytes(b"png")
    page.locator.return_value.first.evaluate.return_value = "Ada Lovelace Resume - Intern.pdf"

    @contextmanager
    def _fake_browser():
        browser = MagicMock()
        browser.contexts = [MagicMock()]
        browser.contexts[0].new_page.return_value = page
        yield browser

    monkeypatch.setattr(browser, "cdp_browser", _fake_browser)

    return page


def _wizard_screen(page, snap):
    """Answer the wizard snapshot script with ``snap``; everything else as before."""
    previous = page.evaluate.side_effect

    def evaluate(script, args=None):
        if script == wizards.SNAPSHOT_JS:
            return snap
        return previous(script, args)

    page.evaluate.side_effect = evaluate


def test_wizard_sign_in_page_is_handed_over_unfilled(fill_paths, monkeypatch):
    """A Taleo login is the applicant's: nothing is typed and the tab is left open."""
    page = _stub_greenhouse_form(fill_paths, monkeypatch, ats="taleo")
    _wizard_screen(page, {"headings": ["Returning User"], "buttons": ["Log In"],
                          "password_inputs": 1, "fields": 2, "text": "Returning User"})
    result = fill.fill_application("src-1", settings=ApplySettings())
    assert result.status == "awaiting_review"
    assert "Sign in to Taleo" in result.handoff_reason
    assert fill._load_filler_js() not in [c.args[0] for c in page.evaluate.call_args_list]  # noqa: SLF001
    assert store.get("src-1").status == "awaiting_review"


def test_a_row_stored_as_other_is_recognised_from_its_url(fill_paths, monkeypatch):
    """Rows found before Taleo was a known platform still get its sign-in handoff."""
    taleo = "https://jpmc.taleo.net/careersection/2/jobdetail.ftl?job=1"
    page = _stub_greenhouse_form(fill_paths, monkeypatch, ats="other", final_url=taleo)
    _wizard_screen(page, {"password_inputs": 1, "fields": 2, "text": "Returning User"})
    result = fill.fill_application("src-1", settings=ApplySettings())
    assert "Sign in to Taleo" in result.handoff_reason


def test_wizard_code_screen_waits_for_the_code(fill_paths, monkeypatch):
    page = _stub_greenhouse_form(fill_paths, monkeypatch, ats="oracle")
    _wizard_screen(page, {"fields": 6, "otp_input": True, "text": "Enter the verification code"})
    result = fill.fill_application("src-1", settings=ApplySettings())
    assert result.status == "awaiting_otp"
    assert "code Oracle emailed" in result.handoff_reason


def test_wizard_review_page_ends_the_fill_for_the_applicant(fill_paths, monkeypatch):
    page = _stub_greenhouse_form(fill_paths, monkeypatch, ats="taleo")
    _wizard_screen(page, {"active_step": "5 - Review and Submit", "headings": ["Review and Submit"],
                          "buttons": ["Submit"], "fields": 1, "text": "Review and Submit"})
    messages: list[str] = []
    result = fill.fill_application(
        "src-1",
        settings=ApplySettings(auto_submit_enabled=True, auto_submit_ats=["greenhouse"]),
        on_progress=messages.append,
    )
    assert result.status == "awaiting_review"
    assert result.submit_action == "awaiting_review"
    assert "Taleo review page reached; the applicant submits" in messages
    assert not any(m.startswith("advancing wizard step") for m in messages)


def test_fill_application_auto_submit(fill_paths, monkeypatch):
    """End-to-end fill stub should mark the application submitted on policy A."""
    _stub_greenhouse_form(fill_paths, monkeypatch)
    result = fill.fill_application(
        "src-1",
        settings=ApplySettings(auto_submit_enabled=True, auto_submit_ats=["greenhouse"]),
    )

    assert result.status == "submitted"
    assert result.submit_action == "auto_submit"
    assert result.ready_to_submit is True
    updated = store.get("src-1")
    assert updated.status == "submitted"


_AUTO = ApplySettings(auto_submit_enabled=True, auto_submit_ats=["greenhouse"])


def test_auto_submit_writes_before_and_after_evidence(fill_paths, monkeypatch):
    _stub_greenhouse_form(fill_paths, monkeypatch)
    result = fill.fill_application("src-1", settings=_AUTO)
    assert result.status == "submitted"
    (audit,) = list((fill_paths / "applications" / "src-1").glob("submit-*"))
    before = json.loads((audit / "before.json").read_text(encoding="utf-8"))
    after = json.loads((audit / "after.json").read_text(encoding="utf-8"))
    assert before["fields"][0]["key"] == "first_name"
    assert after["status"] == "submitted"
    assert (audit / "before.png").exists() and (audit / "after.png").exists()


def test_paused_automation_holds_the_submit(fill_paths, monkeypatch):
    _stub_greenhouse_form(fill_paths, monkeypatch)
    clicked = []
    monkeypatch.setattr(clicks, "submit_click", lambda *a, **k: clicked.append(a))
    submit_guard.set_paused(True)
    result = fill.fill_application("src-1", settings=_AUTO)
    assert clicked == []
    assert result.status == "awaiting_review"
    assert result.ready_to_submit is True
    assert result.handoff_reason == "Automation is paused"
    assert store.get("src-1").status_history[-1].note == "Automation is paused"


def test_daily_cap_holds_the_submit(fill_paths, monkeypatch):
    _stub_greenhouse_form(fill_paths, monkeypatch)
    clicked = []
    monkeypatch.setattr(clicks, "submit_click", lambda *a, **k: clicked.append(a))
    settings = _AUTO.model_copy(update={"auto_submit_max_per_day": 0})
    result = fill.fill_application("src-1", settings=settings)
    assert clicked == []
    assert result.status == "awaiting_review"
    assert result.handoff_reason.startswith("Daily cap reached")


def test_duplicate_submitted_elsewhere_holds_the_submit(fill_paths, monkeypatch):
    _stub_greenhouse_form(fill_paths, monkeypatch)
    earlier = _ready_app(source_job_id="src-0", canonical_key="other:acme:0", company="ACME Inc.")
    store.set_status(earlier, "submitted", note="manual")
    store.upsert(earlier)
    clicked = []
    monkeypatch.setattr(clicks, "submit_click", lambda *a, **k: clicked.append(a))
    result = fill.fill_application("src-1", settings=_AUTO)
    assert clicked == []
    assert result.handoff_reason == "Possible duplicate of ACME Inc. — Intern"


def test_pause_during_pacing_wait_stops_the_submit(fill_paths, monkeypatch):
    _stub_greenhouse_form(fill_paths, monkeypatch)
    clicked = []
    monkeypatch.setattr(clicks, "submit_click", lambda *a, **k: clicked.append(a))
    monkeypatch.setattr(submit_guard, "_last_submit", submit_guard._clock())  # noqa: SLF001
    monkeypatch.setattr(submit_guard, "_sleep", lambda _s: submit_guard.set_paused(True))
    result = fill.fill_application("src-1", settings=_AUTO)
    assert clicked == []
    assert result.status == "awaiting_review"
    assert "paused" in result.handoff_reason


def test_non_english_form_is_handed_over(fill_paths, monkeypatch):
    page = _stub_greenhouse_form(fill_paths, monkeypatch)
    page.locator.return_value.first.get_attribute.return_value = "fr-FR"
    result = fill.fill_application("src-1", settings=_AUTO)
    assert result.status == "awaiting_review"
    assert result.handoff_reason.startswith("The form is in another language (fr-fr)")
    assert result.filled == []


def test_blocked_site_hands_over_and_rests_the_host(fill_paths, monkeypatch):
    from resume_tailor.apply import form_guards

    form_guards.reset_hosts()
    page = _stub_greenhouse_form(fill_paths, monkeypatch)
    page.title.return_value = "Access Denied"
    result = fill.fill_application("src-1", settings=_AUTO)
    assert result.status == "awaiting_review"
    assert "blocked automated access" in result.handoff_reason
    with pytest.raises(RuntimeError, match="refused automated visits recently"):
        fill.fill_application("src-1", settings=_AUTO)
    form_guards.reset_hosts()


class _ConfirmPage:
    def __init__(self, url: str, body: str) -> None:
        self.url = url
        self._body = body

    def locator(self, _selector):
        loc = MagicMock()
        loc.first.count.return_value = 0
        return loc

    def inner_text(self, _selector):
        return self._body


@pytest.mark.parametrize(
    ("ats", "before_url", "after_url", "before", "after", "confirmed"),
    [
        ("greenhouse", "https://x/apply", "https://x/apply", "Form", "Thank you for applying!", True),
        ("lever", "https://x/apply", "https://x/apply", "Form", "Application submitted.", True),
        ("icims", "https://x/apply", "https://x/job/confirmation", "Form", "Done", True),
        ("taleo", "https://x/a", "https://x/a", "Form", "Thank you for submitting", True),
        ("ashby", "https://x/a", "https://x/a", "Thanks for applying soon", "Thanks for applying soon", False),
        ("greenhouse", "https://x/confirmation", "https://x/confirmation", "Form", "Form", False),
        ("lever", "https://x/a", "https://x/a", "Form", "Please fix the errors", False),
    ],
)
def test_submission_confirmed_uses_per_ats_markers(ats, before_url, after_url, before, after, confirmed):
    page = _ConfirmPage(after_url, after)
    assert fill._submission_confirmed(  # noqa: SLF001
        page, before_url=before_url, before_body=before, confirmation_text="", ats=ats
    ) is confirmed


def test_unanswered_salary_question_forces_manual_review_even_with_auto_submit(fill_paths, monkeypatch):
    store.upsert(_ready_app())
    monkeypatch.setattr(packet, "build_packet", lambda _job_id: Packet(
        job_id="job-1", built_at="2026-01-01T00:00:00+00:00", ats="greenhouse",
        fields={"first_name": "Ada", "salary_expectation": "$45/hour"},
    ))
    monkeypatch.setattr(profile_mod, "load_profile", lambda: (ApplicantProfile(first_name="Ada", salary_expectation="$45/hour"), False))
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))
    monkeypatch.setattr(fill, "_find_submit_button", lambda _page, _hints: MagicMock())  # noqa: SLF001
    form = {
        "filled": [{"key": "first_name", "label": "First Name", "value": "Ada", "selector": "#first_name"}],
        "leftovers": [{"key": "salary_expectation", "label": "Desired salary", "type": "text", "selector": "#salary", "required": False, "reason": "No salary range in the applicant profile"}],
        "long_text": [], "file_inputs": [], "required_empty": [], "frames_skipped": 0,
    }
    page = MagicMock(url="https://example.com/apply")
    page.frames = [page]

    def evaluate_form(script, args=None):
        if script == fill._load_filler_js():  # noqa: SLF001
            return form if args and args.get("fields") else {"filled": form["filled"], "leftovers": form["leftovers"]}
        if script == fill._load_readiness_js():  # noqa: SLF001
            return []
        return {"errors": [], "unresolved": [], "advance_disabled": False}

    page.evaluate.side_effect = evaluate_form

    @contextmanager
    def fake_browser():
        instance = MagicMock()
        instance.contexts = [MagicMock()]
        instance.contexts[0].new_page.return_value = page
        yield instance

    monkeypatch.setattr(browser, "cdp_browser", fake_browser)
    result = fill.fill_application("src-1", settings=ApplySettings(auto_submit_enabled=True, auto_submit_ats=["greenhouse"]))
    assert result.status == "awaiting_review"
    assert result.ready_to_submit is False
    assert any(item.get("reason") == "No salary range in the applicant profile" for item in result.leftovers)
    page.click.assert_not_called()


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
    from resume_tailor.apply import form_routes
    monkeypatch.setattr(form_routes, "choose_email_sync", lambda page, *, deadline: "absent")
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
    from resume_tailor.apply import form_routes
    monkeypatch.setattr(form_routes, "choose_email_sync", lambda page, *, deadline: "absent")

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


def test_a_posting_in_another_country_withholds_the_work_authorization_answer(fill_paths, monkeypatch):
    """"Authorized to work" answers for the profile's country; a Canadian posting leaves
    its eligibility questions to the applicant, the resolver model included."""
    store.upsert(_ready_app(location="Toronto, ON, Canada"))
    sample_packet = Packet(
        job_id="job-1", built_at="2026-01-01T00:00:00+00:00",
        fields={"authorized_to_work": "Yes", "country": "United States"}, field_hints={},
    )
    monkeypatch.setattr(packet, "build_packet", lambda job_id: sample_packet)
    monkeypatch.setattr(profile_mod, "load_profile", lambda: (
        ApplicantProfile(country="United States", authorized_to_work=True), False,
    ))
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))

    @contextmanager
    def _broken_browser():
        raise RuntimeError("CDP unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(browser, "cdp_browser", _broken_browser)
    messages: list[str] = []
    fill.fill_application("src-1", on_progress=messages.append)
    assert "authorized_to_work" not in sample_packet.fields
    assert any("Job is in Canada; your work authorization is for United States" in m for m in messages)


def test_fill_application_readiness_guard_fails_when_zero_controls(fill_paths, monkeypatch):
    """When 0 controls are found on the page, fill must fail instead of falsely claiming awaiting_review."""
    app = _ready_app(ats="other")
    store.upsert(app)

    sample_packet = Packet(
        job_id="job-1",
        built_at="2026-01-01T00:00:00+00:00",
        ats="other",
        fields={},
        field_hints={},
    )
    monkeypatch.setattr(packet, "build_packet", lambda job_id: sample_packet)
    monkeypatch.setattr(profile_mod, "load_profile", lambda: (ApplicantProfile(), False))
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))

    filler_result = {
        "filled": [],
        "leftovers": [],
        "long_text": [],
        "file_inputs": [],
        "required_empty": [],
        "frames_skipped": 0,
    }
    page = MagicMock()
    page.url = "https://example.com/apply"
    page.frames = [page]
    page.evaluate.side_effect = [filler_result, []]

    # Mock locators to return 0 counts so barriers and buttons aren't falsely detected
    mock_loc = MagicMock()
    mock_loc.count.return_value = 0
    mock_loc.first = mock_loc
    page.locator.return_value = mock_loc
    page.get_by_role.return_value = mock_loc

    @contextmanager
    def _fake_browser():
        browser = MagicMock()
        browser.contexts = [MagicMock()]
        browser.contexts[0].new_page.return_value = page
        yield browser

    monkeypatch.setattr(browser, "cdp_browser", _fake_browser)
    monkeypatch.setattr(browser, "target_id", lambda _context, _page: "target-no-form")

    result = fill.fill_application("src-1")
    assert result.status == "fill_failed"
    assert "No application form controls detected" in (result.error or "")
    assert result.browser_target_id == "target-no-form"
    assert store.get("src-1").status == "fill_failed"


def test_workday_error_page_that_survives_refreshes_is_handed_over(fill_paths, monkeypatch):
    """Workday's "Something went wrong ... Error Code: VPS|" page is refreshed; if it keeps
    coming back, the tab is handed over for review, not failed as "no form controls"."""
    from resume_tailor.apply import form_routes, workday_auth, workday_flow  # noqa: PLC0415

    store.upsert(_ready_app(ats="workday"))
    monkeypatch.setattr(packet, "build_packet", lambda job_id: Packet(
        job_id="job-1", built_at="2026-01-01T00:00:00+00:00", ats="workday", fields={}, field_hints={},
    ))
    monkeypatch.setattr(profile_mod, "load_profile", lambda: (ApplicantProfile(), False))
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))
    page = MagicMock()
    page.url = "https://tenant.wd1.myworkdayjobs.com/en-US/site/job/City/R1/apply/applyManually"
    page.frames = [page]

    @contextmanager
    def _fake_browser():
        cdp = MagicMock()
        cdp.contexts = [MagicMock()]
        cdp.contexts[0].new_page.return_value = page
        yield cdp

    refreshes: list[int] = []

    def _still_broken(_page, *, deadline, progress, attempts):
        refreshes.append(attempts)
        return False, attempts

    monkeypatch.setattr(browser, "cdp_browser", _fake_browser)
    monkeypatch.setattr(browser, "target_id", lambda _context, _page: "target-wd")
    monkeypatch.setattr(workday_flow, "enter_application", lambda page, _context, **_kw: (page, "apply_form"))
    monkeypatch.setattr(workday_flow, "wait_for_state", lambda *_a, **_kw: "apply_form")
    monkeypatch.setattr(workday_flow, "recover_site_error", _still_broken)
    monkeypatch.setattr(form_routes, "choose_email_sync", lambda page, *, deadline: "absent")
    monkeypatch.setattr(workday_auth, "handle_workday_auth", lambda *_a, **_kw: "authenticated")

    result = fill.fill_application("src-1")
    assert result.status == "awaiting_review"
    assert "kept showing 'Something went wrong'" in (result.handoff_reason or "")
    assert result.browser_target_id == "target-wd"
    assert refreshes and all(attempts == workday_flow.SITE_ERROR_RELOADS for attempts in refreshes)
    assert store.get("src-1").status == "awaiting_review"


def test_a_step_is_blank_only_when_its_passes_saw_no_control_at_all():
    """Philips re-renders My Information for the saved country: a scan in that gap sees
    nothing, and that step is rescanned rather than advanced."""
    empty = {"filled": [{"key": "email"}], "leftovers": [], "long_text": [], "file_inputs": [], "required_empty": []}
    assert fill._scanned_nothing(empty, filled_start=1)
    assert not fill._scanned_nothing({**empty, "filled": [{"key": "email"}, {"key": "phone"}]}, filled_start=1)
    for key in ("leftovers", "long_text", "file_inputs", "required_empty"):
        assert not fill._scanned_nothing({**empty, key: [{"label": "x"}]}, filled_start=1)


def test_decide_submit_action_submit_mode_override():
    """Verify submit_mode parameter overrides the default policy."""
    settings = ApplySettings(auto_submit_enabled=True, auto_submit_ats=["greenhouse"])

    # Normal auto-submit ATS with ready_to_submit
    assert fill.decide_submit_action(ats="greenhouse", settings=settings, ready_to_submit=True) == "auto_submit"

    # User explicitly requested awaiting_review
    assert fill.decide_submit_action(
        ats="greenhouse", settings=settings, ready_to_submit=True, submit_mode="awaiting_review"
    ) == "awaiting_review"

    # Explicit run toggle cannot bypass the configured ATS allowlist.
    assert fill.decide_submit_action(
        ats="lever", settings=settings, ready_to_submit=True, submit_mode="auto_submit"
    ) == "awaiting_review"

    # Workday must also be listed before a verified submission.
    assert fill.decide_submit_action(
        ats="workday", settings=settings, ready_to_submit=True, submit_mode="auto_submit"
    ) == "awaiting_review"


def test_fill_application_multi_step_wizard(fill_paths, monkeypatch):
    """When a wizard next button is present, fill_application should advance through steps."""
    app = _ready_app(ats="lever")
    store.upsert(app)

    sample_packet = Packet(
        job_id="job-1",
        built_at="2026-01-01T00:00:00+00:00",
        ats="lever",
        fields={"first_name": "Ada"},
        field_hints={},
    )
    monkeypatch.setattr(packet, "build_packet", lambda job_id: sample_packet)
    monkeypatch.setattr(profile_mod, "load_profile", lambda: (ApplicantProfile(), False))
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))

    step1_result = {
        "filled": [{"key": "first_name", "label": "First", "value": "Ada", "selector": "#fn"}],
        "leftovers": [],
        "long_text": [],
        "file_inputs": [],
        "required_empty": [],
        "frames_skipped": 0,
    }
    step2_result = {
        "filled": [{"key": "last_name", "label": "Last", "value": "Lovelace", "selector": "#ln"}],
        "leftovers": [],
        "long_text": [],
        "file_inputs": [],
        "required_empty": [],
        "frames_skipped": 0,
    }
    page = MagicMock()
    page.url = "https://example.com/apply"
    page.frames = [page]
    form_step = 0

    def evaluate_form(script, args=None):
        nonlocal form_step
        if script == fill._load_filler_js():  # noqa: SLF001
            if args and args.get("fields"):
                form_step += 1
            current = step1_result if form_step <= 1 else step2_result
            return current
        if script == fill._load_readiness_js():  # noqa: SLF001
            return []
        return {"errors": [], "unresolved": [], "advance_disabled": False}

    page.evaluate.side_effect = evaluate_form

    # Mock advance button on first step, then 0 count on second step
    advance_loc = MagicMock()
    advance_loc.count.side_effect = [1, 0, 0, 0, 0, 0, 0, 0]
    advance_loc.is_visible.return_value = True
    advance_loc.first = advance_loc

    mock_empty = MagicMock()
    mock_empty.count.return_value = 0
    mock_empty.first = mock_empty
    page.locator.return_value = mock_empty

    def _get_by_role(role, name=None, **kwargs):
        if name and hasattr(name, "pattern") and "next" in name.pattern.lower():
            return advance_loc
        return mock_empty

    page.get_by_role = _get_by_role

    @contextmanager
    def _fake_browser():
        browser = MagicMock()
        browser.contexts = [MagicMock()]
        browser.contexts[0].new_page.return_value = page
        yield browser

    monkeypatch.setattr(browser, "cdp_browser", _fake_browser)

    result = fill.fill_application("src-1")
    assert result.status == "awaiting_review"
    assert advance_loc.click.called
    assert len(result.filled) == 2


def test_workday_textareas_are_recommitted_with_real_input_events():
    """Workday ignored a JS-set questionnaire textarea value; only textareas are re-entered."""
    calls: list[tuple[str, str]] = []

    class _Control:
        def __init__(self, selector: str) -> None:
            self.selector = selector

        def evaluate(self, script: str):
            calls.append((self.selector, script))
            return "TEXTAREA" if "salary" in self.selector else "INPUT"

        def fill(self, value: str, timeout: int = 0) -> None:
            calls.append((self.selector, f"fill:{value}"))

    class _Frame:
        def locator(self, selector: str):
            return MagicMock(first=_Control(selector))

    fill._commit_workday_textareas(  # noqa: SLF001
        [_Frame()],
        [
            {"key": "salary_expectation", "value": "$20/hour", "selector": "#salary"},
            {"key": "first_name", "value": "Ada", "selector": "#first"},
            {"key": "existing", "value": "kept", "selector": "#salary-old", "preserved": True},
        ],
    )
    assert ("#salary", "fill:$20/hour") in calls
    assert ("#salary", "el => el.blur()") in calls
    assert not any(value.startswith("fill:") for selector, value in calls if selector != "#salary")


class _FooterButton:
    """A visible Workday footer button with the given text."""

    def __init__(self, text: str, *, visible: bool = True) -> None:
        self.text, self.visible = text, visible

    @property
    def first(self) -> "_FooterButton":
        return self

    def count(self) -> int:
        return 1 if self.visible else 0

    def is_visible(self) -> bool:
        return self.visible

    def inner_text(self, timeout: int | None = None) -> str:
        return self.text

    def get_attribute(self, _name: str) -> str | None:
        return None


class _FooterPage:
    def __init__(self, footer_text: str) -> None:
        self.footer_text = footer_text

    def get_by_role(self, _role: str, name=None) -> _FooterButton:
        return _FooterButton("", visible=False)

    def locator(self, selector: str) -> _FooterButton:
        if "pageFooterNextButton" in selector:
            return _FooterButton(self.footer_text)
        return _FooterButton("", visible=False)


def test_workday_review_submit_is_never_an_advance_button():
    # Philips (2026-09-24): Review's Submit shares Next's `pageFooterNextButton` id, and
    # clicking it as "advance" submitted the application.
    assert fill._find_advance_button(_FooterPage("Submit")) is None  # noqa: SLF001
    assert fill._find_advance_button(_FooterPage("Save and Continue")) is not None  # noqa: SLF001
