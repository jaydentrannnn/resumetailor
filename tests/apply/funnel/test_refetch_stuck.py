"""Rows stuck at ``needs_browser``: fetched from the page their link resolved to, and
fetched again automatically (no model call) until they read, close, or run out of tries."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.discovery.source_rows import SourceRow
from resume_tailor.apply.funnel import (
    daily_progress,
    daily_row_run,
    daily_rows,
    store,
    store_models,
)
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
