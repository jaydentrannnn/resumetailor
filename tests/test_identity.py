"""Hermetic tests for ATS identity helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest

from resume_tailor import config
from resume_tailor.apply import fetch_jd, identity, store


@pytest.fixture
def resolve_cache(tmp_path, monkeypatch):
    """Isolate the permanent URL resolve cache under a temp applications dir."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    return tmp_path / "applications"


def test_canonical_key_greenhouse_boards():
    key = identity.canonical_key(
        "https://boards.greenhouse.io/figma/jobs/6143238004?gh_jid=6143238004"
    )
    assert key == "greenhouse:figma:6143238004"


def test_canonical_key_greenhouse_job_boards():
    key = identity.canonical_key(
        "https://job-boards.greenhouse.io/doordashusa/jobs/8171041"
    )
    assert key == "greenhouse:doordashusa:8171041"


def test_canonical_key_greenhouse_via_gh_jid_on_careerpuck():
    key = identity.canonical_key(
        "https://app.careerpuck.com/job-board/lyft/job/8767726002?gh_jid=8767726002"
    )
    assert key == "greenhouse:lyft:8767726002"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://cai.wd5.myworkdayjobs.com/computer_aid/job/"
            "PA-CLIENT-STATE/Data-Analyst-Intern_R8551",
            "workday:cai:R8551",
        ),
        (
            "https://amfam.wd1.myworkdayjobs.com/AmFamGroupInternCareers/job/"
            "WI-Madison/Consumer-Research-and-Insights-Intern-2027_R39474",
            "workday:amfam:R39474",
        ),
        (
            "https://mfs.wd1.myworkdayjobs.com/en-US/MFS-Careers/job/Boston/"
            "Global-Institutional-Strategic-Accounts-Co-op-Spring-2027"
            "--January---June-_MFS-231931",
            "workday:mfs:MFS-231931",
        ),
        (
            "https://gehc.wd5.myworkdayjobs.com/GEHC_ExternalSite/job/"
            "Salt-Lake-City/Software-Engineering-Summer-Intern-2027_R4046481-1",
            "workday:gehc:R4046481-1",
        ),
        (
            "https://fmr.wd1.myworkdayjobs.com/fidelitycareers/job/"
            "One-Destiny-Way-Westlake-TX/"
            "Summer-2027-Undergraduate-Internship---Software_2134524",
            "workday:fmr:2134524",
        ),
        (
            "https://nebraskamed.wd5.myworkdayjobs.com/nm/job/Omaha-NE/"
            "Intern---Forward-Deployed-AI-Engineer_REQ-38924",
            "workday:nebraskamed:REQ-38924",
        ),
        (
            "https://generalmotors.wd5.myworkdayjobs.com/en-CA/Careers_GM/job/"
            "Warren-Michigan-United-States-of-America/"
            "XMLNAME-2027-Summer-Intern---Digital-Product"
            "--Software-Engineering_JR-202620546",
            "workday:generalmotors:JR-202620546",
        ),
    ],
)
def test_canonical_key_workday_uses_final_path_segment_id(url, expected):
    """The requisition id is the text after the URL's last ``_``, not the first
    letters-plus-year match anywhere in the path (the pre-fix behavior, which
    turned ``…Intern-2027_R39474`` into ``ERN-2027``)."""
    assert identity.canonical_key(url) == expected


def test_canonical_key_workday_falls_back_without_underscore_suffix():
    key = identity.canonical_key(
        "https://acme.wd1.myworkdayjobs.com/External/job/Remote/R12345"
    )
    assert key == "workday:acme:R12345"


def test_canonical_key_other_fallback():
    key = identity.canonical_key(
        "https://apply.careers.microsoft.com/careers/job/1970393556982258"
    )
    assert key.startswith("other:apply.careers.microsoft.com:")


def test_group_key_collapses_locations():
    a = identity.group_key(
        "Northrop Grumman",
        "2027 Embedded Software Engineer Intern - Baltimore MD",
    )
    b = identity.group_key(
        "Northrop Grumman",
        "2027 Embedded Software Engineer Intern - Camarillo CA",
    )
    assert a == b


def test_group_key_strips_year_season_and_parens():
    a = identity.group_key(
        "ICF", "2027 Summer Intern, Software Developer (Reston, VA)"
    )
    b = identity.group_key("ICF", "Summer Intern, Software Developer")
    assert a == b


def test_resolve_final_url_caches_and_skips_second_http(resolve_cache, monkeypatch):
    """First call hits HTTP and writes the cache; second call is a cache hit."""
    calls: list[str] = []

    class _Resp:
        status_code = 200
        url = "https://boards.greenhouse.io/acme/jobs/99?utm_source=x&gh_jid=99"

    def _head(url, **kwargs):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(identity.httpx, "head", _head)
    wrapper = "https://simplify.jobs/p/abc"
    first = identity.resolve_final_url(wrapper)
    assert first == "https://boards.greenhouse.io/acme/jobs/99?gh_jid=99"
    assert len(calls) == 1
    cache_path = config.APPLICATIONS_OUTPUT_DIR / "url_resolve_cache.json"
    assert cache_path.is_file()
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    assert raw[wrapper] == first

    second = identity.resolve_final_url(wrapper)
    assert second == first
    assert len(calls) == 1


def test_resolve_final_url_passthrough_for_direct_ats():
    url = "https://boards.greenhouse.io/figma/jobs/1"
    assert identity.resolve_final_url(url) == url


@pytest.mark.parametrize(
    ("url", "key", "ats"),
    [
        (
            "https://jpmc.taleo.net/careersection/2/jobdetail.ftl?job=240012345&lang=en",
            "taleo:jpmc:240012345",
            "taleo",
        ),
        (
            "https://career4.successfactors.com/sfcareer/jobreqcareer"
            "?jobId=1&company=AcmeCorp&career_job_req_id=98765",
            "successfactors:acmecorp:98765",
            "successfactors",
        ),
        (
            "https://ejaa.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/"
            "CX_1/job/12345/?utm_medium=jobshare",
            "oracle:ejaa:12345",
            "oracle",
        ),
        (
            "https://jobs.jobvite.com/acme/job/oAbC123x?nl=0",
            "jobvite:acme:oAbC123x",
            "jobvite",
        ),
        ("https://acme.bamboohr.com/careers/42", "bamboohr:acme:42", "bamboohr"),
        ("https://acme.bamboohr.com/jobs/view.php?id=77", "bamboohr:acme:77", "bamboohr"),
        (
            "https://www.linkedin.com/jobs/view/summer-analyst-at-acme-4012345678/",
            "linkedin:jobs:4012345678",
            "linkedin",
        ),
        (
            "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4012345678",
            "linkedin:jobs:4012345678",
            "linkedin",
        ),
        ("https://www.indeed.com/viewjob?jk=AB12cd34ef56&from=serp", "indeed:jobs:ab12cd34ef56", "indeed"),
        ("https://app.joinhandshake.com/stu/jobs/9876543", "handshake:jobs:9876543", "handshake"),
        ("https://uci.joinhandshake.com/jobs/9876543", "handshake:jobs:9876543", "handshake"),
    ],
)
def test_canonical_key_and_ats_for_more_platforms(url, key, ats):
    assert identity.canonical_key(url) == key
    assert fetch_jd.detect_ats(url) == ats


def test_platform_pages_without_a_job_id_fall_back_to_the_path_digest():
    assert identity.canonical_key("https://jpmc.taleo.net/careersection/2/moresearch.ftl").startswith(
        "other:jpmc.taleo.net:"
    )
    assert identity.canonical_key("https://www.linkedin.com/jobs/").startswith("other:")
    # An Oracle Cloud page that is not the candidate site is not an Oracle posting.
    assert fetch_jd.detect_ats("https://docs.oraclecloud.com/en/cloud/") != "oracle"


def test_ats_kinds_agree():
    """`fetch_jd.detect_ats` may only return kinds the store accepts."""
    assert get_args(fetch_jd.AtsName) == get_args(store.AtsKind)
