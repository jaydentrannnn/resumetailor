"""`ats_fingerprint`: the platform a landed page belongs to. A platform's own host or path
is enough alone; page signals need two that agree."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from resume_tailor.apply.ats import ats_fingerprint as fp
from resume_tailor.apply.discovery import fetch_jd


@pytest.mark.parametrize(("url", "platform"), [
    ("https://careers-acme.icims.com/jobs/1234/job", "icims"),
    ("https://jobs.smartrecruiters.com/Acme/7444", "smartrecruiters"),
    ("https://acme.eightfold.ai/careers/job/123456789012", "eightfold"),
    ("https://acme.avature.net/careers/JobDetail/1", "avature"),
    ("https://acme.jibeapply.com/jobs/1", "jibe"),
    ("https://careers.acme.com/hcmUI/CandidateExperience/en/sites/CX/job/1", "oracle"),
])
def test_a_platform_host_or_path_is_enough(url, platform):
    assert fp.from_signals(url, None) == platform


@pytest.mark.parametrize(("url", "signals", "platform"), [
    ("https://careers.acme.com/apply", {"elements": ["apply-flow-header", "oj-input-text"]}, "oracle"),
    ("https://careers.acme.com/apply", {"elements": ["oc-oneclick-form-root", "spl-input"]},
     "smartrecruiters"),
    ("https://careers.acme.com/jobs", {"iframe_ids": ["icims_content_iframe"],
                                       "iframe_hosts": ["careers-acme.icims.com"]}, "icims"),
    ("https://careers.acme.com/careers/job/123456789012", {"elements": ["apply-widget"]},
     "eightfold"),
    ("https://careers.acme.com/careers/job/123456789012", {"script_hosts": ["static.vscdn.net"]},
     "eightfold"),
    ("https://careers.acme.com/careers/Login", {"elements": ["portal-data"]}, "avature"),
])
def test_two_agreeing_page_signals(url, signals, platform):
    assert fp.from_signals(url, signals) == platform


@pytest.mark.parametrize(("url", "signals"), [
    ("https://careers.acme.com/apply", {"elements": ["apply-flow-header"]}),
    ("https://careers.acme.com/apply", {"elements": ["oj-input-text"]}),
    ("https://careers.acme.com/apply", {"elements": ["spl-input"]}),
    ("https://careers.acme.com/jobs", {"iframe_ids": ["icims_content_iframe"]}),
    ("https://careers.acme.com/jobs/42", {"elements": ["apply-widget"]}),
    ("https://careers.acme.com/about", {"elements": ["portal-data"]}),
])
def test_one_page_signal_is_not_enough(url, signals):
    assert fp.from_signals(url, signals) is None


def test_fetched_html_gives_the_same_signals():
    html = ('<html><body><oc-oneclick-form-root></oc-oneclick-form-root><spl-input></spl-input>'
            '<iframe id="x" src="https://a.example/frame"></iframe>'
            '<script src="https://cdn.example/app.js"></script></body></html>')
    signals = fp.signals_from_html(html)
    assert signals["elements"] == ["oc-oneclick-form-root", "spl-input"]
    assert signals["iframe_hosts"] == ["a.example"] and signals["script_hosts"] == ["cdn.example"]
    assert fetch_jd.detect_ats("https://careers.acme.com/apply", html) == "smartrecruiters"


def test_stored_name_is_one_older_apps_can_read():
    assert fp.stored_ats("oracle") == "oracle"
    assert fp.stored_ats("eightfold") is None
    assert fp.stored_ats("avature") is None


def test_identify_prefers_the_known_host_and_an_unreadable_page_is_blank():
    assert fp.identify("https://boards.greenhouse.io/acme/jobs/1", {"elements": ["portal-data"]}) == "greenhouse"

    class Navigating:
        url = "https://careers.acme.com/"

        def evaluate(self, _script):
            raise RuntimeError("Execution context was destroyed")

    assert fp.page_platform(Navigating()) == ""
    assert fp.page_platform(SimpleNamespace(
        url="https://careers.acme.com/jobs", evaluate=lambda _s: {})) in {"other", "unknown"}
