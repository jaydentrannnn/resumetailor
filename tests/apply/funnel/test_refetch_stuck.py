"""Rows stuck at ``needs_browser``: fetched from the page their link resolved to, and
fetched again automatically (no model call) until they read, close, or run out of tries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from resume_tailor import config
from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.discovery.source_rows import SourceRow
from resume_tailor.apply.funnel import (
    daily,
    daily_batch,
    daily_progress,
    daily_retry,
    daily_row_run,
    daily_rows,
    store,
    store_models,
)
from resume_tailor.apply.funnel.screen import ScreenResult
from resume_tailor.web.schemas import ApplySettings, JobSettings

_ICIMS = "https://careers-primecontrols.icims.com/jobs/2282/enterprise-automation-developer/job"
_ASHBY = "https://jobs.ashbyhq.com/rhoda-ai/36a82229-5cab-48a7-99b6-ec9007c5b460/application"


@pytest.fixture
def apply_paths(tmp_path, monkeypatch):
    """Isolate the applications registry and output tree."""
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    return tmp_path


def _app(**fields) -> store_models.Application:
    return store_models.Application(
        **{
            "source": "vanshb03-newgrad",
            "source_job_id": "stuck-1",
            "company": "Prime Controls",
            "role": "Enterprise Automation Developer",
            "status": "needs_browser",
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        # A short link that a fetch resolved: read the ATS page, keyed for its feed.
        (
            {"posting_url": "https://go.vansh.nyc/AN", "final_url": _ASHBY,
             "canonical_key": "other:go.vansh.nyc:e86dbec0ffb3"},
            (_ASHBY, "ashby:rhoda-ai:36a82229-5cab-48a7-99b6-ec9007c5b460"),
        ),
        (
            {"posting_url": "https://go.vansh.nyc/BW", "final_url": _ICIMS,
             "canonical_key": "other:go.vansh.nyc:e72f017c592b"},
            (_ICIMS, "icims:https://careers-primecontrols:2282"),
        ),
        # The stored key is kept when it is a real one.
        (
            {"posting_url": "https://zapply.jobs/l/d/workday-pae-amentum-careers-R0148259",
             "final_url": "https://pae.wd1.myworkdayjobs.com/amentum_careers/job/US-VA/X_R0148259",
             "canonical_key": "workday:pae:R0148259"},
            ("https://pae.wd1.myworkdayjobs.com/amentum_careers/job/US-VA/X_R0148259",
             "workday:pae:R0148259"),
        ),
        # A posting already on an ATS stays the URL fetched.
        (
            {"posting_url": "https://boards.greenhouse.io/acme/jobs/1",
             "final_url": "https://boards.greenhouse.io/acme/jobs/1?error=true",
             "canonical_key": "greenhouse:acme:1"},
            ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse:acme:1"),
        ),
        # A company's own site: no feed to key.
        (
            {"posting_url": "https://www.tesla.com/careers/search/job/286986",
             "canonical_key": "other:www.tesla.com:abc"},
            ("https://www.tesla.com/careers/search/job/286986", None),
        ),
        # A link that led to LinkedIn is never fetched from there.
        (
            {"posting_url": "https://www.adzuna.com/land/ad/5938940362",
             "final_url": "https://www.linkedin.com/jobs/view/4481121442",
             "canonical_key": "other:www.adzuna.com:abc"},
            ("https://www.adzuna.com/land/ad/5938940362", None),
        ),
    ],
)
def test_fetch_target_prefers_the_ats_page_a_short_link_resolved_to(fields, expected):
    assert daily_rows.fetch_target(_app(**fields)) == expected


def test_fetch_target_uses_a_careers_page_that_names_its_greenhouse_job():
    page = "https://www.spotandtango.com/careers?gh_jid=4620638005"
    app = _app(posting_url="https://go.vansh.nyc/wt", final_url=page,
               canonical_key="other:go.vansh.nyc:abc")
    assert daily_rows.fetch_target(app) == (page, "greenhouse:careers:4620638005")


def test_fetch_target_resolves_a_wrapper_link_an_offline_sighting_left(monkeypatch):
    link = "https://zapply.jobs/l/d/workday-cox-cox-external-career-site-1-R202682166"
    workday = "https://cox.wd1.myworkdayjobs.com/Cox_External/job/Atlanta/Intern_R202682166"
    monkeypatch.setattr(daily_rows.identity, "resolve_final_url", lambda url: workday)
    app = _app(posting_url=link, final_url=link, canonical_key="other:zapply.jobs:abc")
    assert daily_rows.fetch_target(app) == (workday, "workday:cox:R202682166")


def test_fetch_target_detects_linkedin_as_a_board():
    # Guards the table above: LinkedIn must count as a board, never an ATS to fetch.
    assert fetch_jd.detect_ats("https://www.linkedin.com/jobs/view/1") == "linkedin"


def test_a_failed_fetch_says_why_on_the_row(apply_paths, monkeypatch, tmp_path):
    """The Apply page's "Why it failed" chip reads `error`; the nightly run used to put the
    reason only in the status history, so 126 of 127 stuck rows showed none."""
    reason = "Client error '403 Forbidden'; browser: Timeout 30000ms exceeded."
    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url, ats="other", text="", method="failed", error=reason
        ),
    )
    row = SourceRow(
        company="Tesla",
        role="Automation Engineer Intern",
        location="Fremont, CA",
        age="0d",
        job_id="tesla-286986",
        application_link="https://www.tesla.com/careers/search/job/286986",
    )
    daily_row_run._process_one(
        row,
        settings=ApplySettings(),
        job_defaults=JobSettings(),
        resume=None,
        known_tags=[],
        allow_browser=True,
        dry_run=False,
        fetch_only=True,
        log_path=tmp_path / "daily.log",
        log=lambda _line: None,
        summary=daily_progress.DailySummary(date="2026-10-29"),
        index=store.build_index(),
    )
    app = store.get("tesla-286986")
    assert app is not None and app.status == "needs_browser"
    assert app.error == reason


_NOW = datetime(2026, 10, 29, 18, 0, tzinfo=UTC)
_JD = "Build automation for battery cell lines in Python and PLCs. " * 10


def _stuck(job_id: str, *, failures: int = 1, hours_ago: float = 48, **fields) -> None:
    """Seed a row that has failed ``failures`` fetches, the last ``hours_ago`` hours ago."""
    app = _app(
        source_job_id=job_id,
        company=job_id,
        posting_url=f"https://careers.example.com/jobs/{job_id}",
        canonical_key=f"other:careers.example.com:{job_id}",
        **fields,
    )
    for n in range(failures):
        at = _NOW - timedelta(hours=hours_ago + 24 * (failures - 1 - n))
        app.status_history.append(
            store_models.StatusChange(status="needs_browser", at=at.isoformat(), note="offline")
        )
    store.upsert(app)


def _fetches(monkeypatch, results: dict[str, fetch_jd.FetchResult]) -> list[str]:
    """Stub `fetch_jd.fetch_jd`: the result whose key is in the URL. Returns the URLs."""
    calls: list[str] = []

    def fetch(url, allow_browser=True, canonical_key=None):
        calls.append(url)
        return next(r for k, r in results.items() if k in url)

    monkeypatch.setattr(fetch_jd, "fetch_jd", fetch)
    return calls


def _read(url: str) -> fetch_jd.FetchResult:
    return fetch_jd.FetchResult(final_url=url, ats="other", text=_JD, method="browser")


def test_only_rows_due_another_try_are_picked_longest_waiting_first(apply_paths):
    _stuck("recent", hours_ago=2)
    _stuck("old", hours_ago=72)
    _stuck("older", hours_ago=96)
    _stuck("worn-out", failures=5)
    _stuck("archived", archived_at="2026-10-20T00:00:00+00:00")
    _stuck("captured", capture_stub=True)
    _stuck("ready", status="ready")
    due = daily_retry._due_for_refetch(_NOW)
    assert [store.get(key).source_job_id for key in due] == ["older", "old"]


def test_the_sweep_reads_closes_and_screens_rows_without_the_model(apply_paths, monkeypatch):
    _stuck("opens")
    _stuck("closed")
    _stuck("screened")
    _stuck("still-blocked")
    calls = _fetches(monkeypatch, {
        "opens": _read("https://careers.example.com/jobs/opens"),
        "closed": fetch_jd.FetchResult(
            final_url="u", ats="workday", text="", method="failed",
            error="Posting closed (Workday no longer lists it)",
            closed="Posting closed (Workday no longer lists it)",
        ),
        "screened": _read("https://careers.example.com/jobs/screened"),
        "still-blocked": fetch_jd.FetchResult(
            final_url="u", ats="other", text="", method="failed", error="HTTP 403"
        ),
    })
    real_prefilter = daily_rows.prefilter_screen

    def prefilter(text, role, settings, **kwargs):
        if role == "screened":
            return ScreenResult(passed=False, reasons=["requires citizenship"])
        return real_prefilter(text, role, settings, **kwargs)

    monkeypatch.setattr(daily_rows, "prefilter_screen", prefilter)
    store.patch(store.get("screened").canonical_key, role="screened")

    moved = daily_retry.refetch_stuck(now=_NOW)

    assert moved == 3 and len(calls) == 4
    assert store.get("opens").status == "jd_fetched"
    assert store.get("closed").status == "skipped"
    assert store.get("screened").status == "screened_out"
    blocked = store.get("still-blocked")
    assert blocked.status == "needs_browser" and blocked.error == "HTTP 403"
    # A failed try counts toward the cap and waits another day before the next.
    assert daily_retry._due_for_refetch(_NOW) == []


def test_the_sweep_stops_at_its_per_run_cap_and_on_cancel(apply_paths, monkeypatch):
    for n in range(3):
        _stuck(f"row-{n}")
    calls = _fetches(monkeypatch, {"row-": _read("https://careers.example.com/jobs/x")})
    monkeypatch.setattr(daily_retry, "_REFETCH_PER_RUN", 2)
    assert daily_retry.refetch_stuck(now=_NOW) == 2
    assert len(calls) == 2
    assert daily_retry.refetch_stuck(should_cancel=lambda: True, now=_NOW) == 0
    assert len(calls) == 2


@pytest.mark.parametrize(("dry_run", "expected"), [(False, 1), (True, 0)])
def test_every_find_ends_with_the_sweep_unless_dry(apply_paths, monkeypatch, dry_run, expected):
    swept: list[bool] = []
    monkeypatch.setattr(daily.data, "load", lambda: None)
    monkeypatch.setattr(daily, "_resume_skills", lambda *a: [])
    monkeypatch.setattr(daily_batch, "_discover_new_rows", lambda *a, **k: [])
    monkeypatch.setattr(daily_batch, "_process_rows", lambda *a, **k: None)
    monkeypatch.setattr(
        daily_retry, "refetch_stuck", lambda **k: swept.append(True) or 0
    )
    daily.run_daily(settings=ApplySettings(enabled=True), fetch_only=True, dry_run=dry_run)
    assert len(swept) == expected
