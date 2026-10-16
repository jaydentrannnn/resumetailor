"""Manual submission is observed on the recorded requisition without browser actions."""

import asyncio
import threading

import pytest

from resume_tailor import config
from resume_tailor.apply.discovery import identity
from resume_tailor.apply.funnel import answer_harvest, store, store_models, submission_monitor

POSTING = (
    "https://osv-rubicon.wd5.myworkdayjobs.com/en-US/MagniteCareers/job/"
    "United-Kingdom---Belfast/Software-Engineer---Student-Placement_"
    "R-01418"
)
CANDIDATE_HOME = "https://osv-rubicon.wd5.myworkdayjobs.com/en-US/MagniteCareers/userHome"
_REAL_WATCH = answer_harvest.watch


def _app(source_id="tracked", **overrides):
    return store_models.Application(
        **{
            "source": "manual",
            "source_job_id": source_id,
            "company": "Synthetic Employer",
            "role": "Software Engineer",
            "posting_url": POSTING,
            "final_url": POSTING,
            "canonical_key": identity.canonical_key(POSTING),
            "ats": "workday",
            "status": "awaiting_review",
            "fill": {
                "browser_target_id": "recorded-target",
                "browser_url": POSTING,
                "status": "awaiting_review",
                "filled": ["First Name"],
                "uploads": [{"key": "resume"}],
                "error": "old error",
                "handoff_reason": "Review before submission",
            },
            **overrides,
        }
    )


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    return tmp_path


@pytest.mark.parametrize(
    "body",
    [
        "Application Submitted",
        "Your application has been successfully submitted.",
        "Thank you for applying!",
    ],
)
def test_explicit_confirmation_on_exact_recorded_application(body):
    evidence = submission_monitor.confirmation(POSTING, POSTING, body, "workday")
    assert evidence and evidence["requisition"] == "R-01418"
    assert evidence["url"] == POSTING


def test_workday_candidate_home_requires_requisition_and_submitted_status():
    row = "Software Engineer\nR-01418\nOctober 12, 2026\nIn Progress"
    evidence = submission_monitor.confirmation(
        POSTING, CANDIDATE_HOME, "Application Submitted\n" + row, "workday", rows=[row]
    )
    assert evidence and evidence["requisition"] == "R-01418"


@pytest.mark.parametrize(
    ("current_url", "body"),
    [
        (CANDIDATE_HOME, "R-99999\nApplication Submitted"),
        (CANDIDATE_HOME, "R-014180\nApplication Submitted"),
        (POSTING.replace("osv-rubicon", "other-employer"), "R-01418\nApplication Submitted"),
        (POSTING.replace("R-01418", "R-99999"), "Application Submitted"),
        (POSTING, "Thank you for your interest in our company."),
        (POSTING, "Review Your Application\nSubmit Application"),
        (CANDIDATE_HOME, "Application Submitted"),
        (POSTING, "Application has not been submitted."),
    ],
)
def test_wrong_requisition_host_or_ambiguous_message_is_not_confirmation(current_url, body):
    assert submission_monitor.confirmation(POSTING, current_url, body, "workday") is None


def test_candidate_home_submitted_status_must_belong_to_tracked_row():
    rows = [
        "Software Engineer\nR-01418\nNot Yet Submitted",
        "Unrelated Job\nR-99999\nOctober 12, 2026\nIn Progress",
    ]
    body = "My Applications\nApplication Submitted\n" + "\n".join(rows)
    assert (
        submission_monitor.confirmation(POSTING, CANDIDATE_HOME, body, "workday", rows=rows) is None
    )


@pytest.mark.parametrize("rows", [[], ["Software Engineer\nR-01418\nIn Progress"]])
def test_candidate_home_without_recorded_submission_date_stays_unconfirmed(rows):
    assert (
        submission_monitor.confirmation(
            POSTING, CANDIDATE_HOME, "R-01418\nApplication Submitted", "workday", rows=rows
        )
        is None
    )


def test_workday_apply_path_still_matches_posting_requisition():
    evidence = submission_monitor.confirmation(
        POSTING, POSTING + "/apply", "Application Submitted", "workday"
    )
    assert evidence and evidence["requisition"] == "R-01418"


def test_matching_greenhouse_confirmation_works_without_workday_requisition():
    url = "https://job-boards.greenhouse.io/synthetic/jobs/8263774"
    evidence = submission_monitor.confirmation(
        url, url, "Thank you for your application", "greenhouse"
    )
    assert evidence and evidence["requisition"] == "8263774"


def test_greenhouse_posting_saved_on_boards_is_confirmed_on_job_boards():
    # Point72 / Anduril (2026-10-16): saved on boards., applied to on job-boards.
    posting = "https://boards.greenhouse.io/synthetic/jobs/8885733002"
    landed = "https://job-boards.greenhouse.io/synthetic/jobs/8885733002/confirmation"
    evidence = submission_monitor.confirmation(posting, landed, "Thank you for applying", "greenhouse")
    assert evidence and evidence["requisition"] == "8885733002"
    other = landed.replace("8885733002", "1111111111")
    assert submission_monitor.confirmation(posting, other, "Thank you for applying", "greenhouse") is None


VARIANT = (
    "https://synthetic.wd5.myworkdayjobs.com/External/job/Bellevue/"
    "AI-Intern---Summer-2027_R5054820-2"
)
COMPLETED = "https://synthetic.wd5.myworkdayjobs.com/en-US/External/jobTasks/completed/application"


def test_workday_location_variant_matches_the_bare_requisition_the_page_shows():
    # GE Vernova (2026-10-16): the URL's R5054820-2 is requisition R5054820 on the page.
    row = "AI Intern - Summer 2027\tR5054820\tSubmitted\tOctober 15, 2026"
    evidence = submission_monitor.confirmation(
        VARIANT, COMPLETED, "Application Submitted\n" + row, "workday", rows=[row]
    )
    assert evidence and evidence["requisition"] == "R5054820-2"
    bare_url = VARIANT.removesuffix("-2")
    assert submission_monitor.confirmation(VARIANT, bare_url, "Application Submitted", "workday")


@pytest.mark.parametrize(
    "body",
    [
        "Application Submitted\nR5054821",  # another requisition
        "Application Submitted\nR5054820-3",  # a sibling variant's own id
        "R5054820\nReview Your Application",  # no confirmation
    ],
)
def test_workday_variant_still_needs_its_own_requisition_and_a_confirmation(body):
    assert submission_monitor.confirmation(VARIANT, COMPLETED, body, "workday") is None


def test_dashed_requisition_without_variant_is_not_shortened():
    # R-01418 must not be read as requisition "R" plus a variant number.
    assert submission_monitor.confirmation(
        POSTING, CANDIDATE_HOME, "R\nApplication Submitted", "workday", rows=["R\nOctober 12, 2026"]
    ) is None


def test_record_persists_confirmation_and_archives_only_matched_application(isolated_store):
    app = _app()
    unrelated = _app(
        "unrelated",
        posting_url=POSTING.replace("R-01418", "R-99999"),
        final_url="",
        canonical_key="workday:osv-rubicon:R-99999",
    )
    store.upsert(app)
    store.upsert(unrelated)
    evidence = {"url": CANDIDATE_HOME, "requisition": "R-01418", "signal": "Application Submitted"}
    result = submission_monitor.record(app, evidence)
    saved = store.get(app.source_job_id)
    assert saved and saved.status == "submitted" and saved.archived_at
    assert saved.error is None
    restored_result = store_models.FillResult.model_validate(saved.fill)
    assert restored_result.submit_action == "manual_submit"
    assert restored_result.error is None and restored_result.handoff_reason == ""
    assert restored_result.confirmation_evidence["requisition"] == "R-01418"
    assert restored_result.confirmation_evidence["at"]
    assert restored_result.browser_target_id == "recorded-target"
    assert restored_result.filled == ["First Name"] and restored_result.uploads == [
        {"key": "resume"}
    ]
    assert result.status == "submitted"
    assert saved.status_history[-1].note.startswith("Manual submission confirmed")
    other = store.get(unrelated.source_job_id)
    assert other and other.status == "awaiting_review" and other.archived_at is None


def test_delayed_confirmation_cannot_write_into_a_different_workspace(isolated_store, monkeypatch):
    app = _app()
    store.upsert(app)
    old_path = config.APPLICATIONS_PATH
    monkeypatch.setattr(config, "APPLICATIONS_PATH", isolated_store / "other" / "applications.json")
    evidence = {"url": POSTING, "requisition": "R-01418", "signal": "Application Submitted"}
    assert submission_monitor.record(app, evidence, workspace_path=old_path) is None
    assert store.load_all() == {}
    monkeypatch.setattr(config, "APPLICATIONS_PATH", old_path)
    assert store.get(app.source_job_id).status == "awaiting_review"


def test_delayed_confirmation_preserves_a_later_terminal_decision(isolated_store):
    stale = _app()
    store.upsert(stale)
    store.patch(stale.source_job_id, status="rejected")
    evidence = {"url": POSTING, "requisition": "R-01418", "signal": "Application Submitted"}
    assert submission_monitor.record(stale, evidence) is None
    assert store.get(stale.source_job_id).status == "rejected"


class _ReadOnlyPage:
    def __init__(self, url, body="", failure=None, rows=None):
        self.url, self.body, self.failure = url, body, failure
        self.rows = rows if rows is not None else [body]
        self.reads = []

    def locator(self, selector):
        assert selector == "body"
        return self

    async def inner_text(self, **kwargs):
        self.reads.append(kwargs)
        if self.failure:
            raise self.failure
        return self.body

    async def evaluate(self, expression):
        assert expression == submission_monitor.ROWS_JS
        return self.rows

    def click(self, *args, **kwargs):
        pytest.fail("The manual submission monitor must never click")


def test_inspect_reads_and_records_without_clicking(isolated_store):
    app = _app()
    store.upsert(app)
    page = _ReadOnlyPage(CANDIDATE_HOME, "R-01418\nOctober 12, 2026\nApplication Submitted")
    assert asyncio.run(submission_monitor.inspect(app, page)) is True
    assert page.reads == [{"timeout": 4000}]
    assert store.get(app.source_job_id).status == "submitted"


@pytest.mark.parametrize("failure", [None, RuntimeError("tab closed")])
def test_inspect_closed_or_unconfirmed_tab_preserves_review_status(isolated_store, failure):
    app = _app()
    store.upsert(app)
    page = _ReadOnlyPage(CANDIDATE_HOME, "R-01418\nIn Progress", failure=failure)
    assert asyncio.run(submission_monitor.inspect(app, page)) is False
    assert store.get(app.source_job_id).status == "awaiting_review"


def test_startup_restores_retained_target_watchers_without_starting_real_thread(monkeypatch):
    watched = [
        _app("review"),
        _app("otp", status="awaiting_otp"),
        _app("uncertain", status="submit_unconfirmed"),
        _app("done", status="submitted"),
        _app("no-target", fill={"status": "awaiting_review"}),
    ]
    monkeypatch.setattr(
        answer_harvest.store, "load_all", lambda: {app.source_job_id: app for app in watched}
    )
    monkeypatch.setattr(answer_harvest, "_WATCHED", set())
    monkeypatch.setattr(answer_harvest, "_THREAD", None)
    monkeypatch.setattr(answer_harvest, "_STOP", threading.Event())
    monkeypatch.setattr(answer_harvest, "watch", _REAL_WATCH)
    started = []

    class _Thread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self.kwargs)

    monkeypatch.setattr(answer_harvest.threading, "Thread", _Thread)
    answer_harvest.restore()
    assert {"review", "otp", "uncertain"} == answer_harvest._WATCHED
    assert len(started) == 1 and started[0]["daemon"] is True
    assert started[0]["target"] is answer_harvest._loop
