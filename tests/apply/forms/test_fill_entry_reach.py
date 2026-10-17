"""Reaching the form from a careers page, reporting when it was not reached, and replacing
an application's old tab (2026-10 reruns: Capgemini, Royal Caribbean, Qualtrics)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.driver import browser, clicks
from resume_tailor.apply.forms import fill, fill_buttons, fill_finish, fill_outcomes, fill_page
from resume_tailor.apply.funnel import packet, preparation, store, store_models
from resume_tailor.apply.funnel.packet_models import Packet
from resume_tailor.content import data

_FORMS = Path(__file__).parents[2] / "fixtures" / "forms"
JOB = "https://careers.example.com/job/1443172033/"


class _Loc:
    """An entry control: its ``href`` and what clicking it does to the page."""

    def __init__(self, page, href, on_click):
        self.page, self.href, self.on_click = page, href, on_click

    def get_attribute(self, name, **kwargs):
        return self.href if name == "href" else None

    def click(self, **kwargs):
        self.on_click(self.page)


class _Page:
    def __init__(self, url=JOB, menu_item=None, redirects=None):
        self.url = url
        self.visited: list[str] = []
        self.menu_item, self.redirects = menu_item, redirects or {}

    def goto(self, url, **kwargs):
        self.visited.append(url)
        self.url = self.redirects.get(url, url)

    def get_by_role(self, role, **kwargs):
        assert role == "menuitem"
        return self.menu_item or _Absent()

    def wait_for_timeout(self, _ms):
        return None


class _Absent:
    first = property(lambda self: self)

    def count(self):
        return 0


class _MenuItem(_Absent):
    def __init__(self, page):
        self.page = page

    def count(self):
        return 1

    def is_visible(self):
        return True

    def click(self, **kwargs):
        self.page.url = "https://career5.successfactors.eu/careers?company=synthetic"


def _intercepted(_page):
    raise RuntimeError("<div id=phenomChatbotWrapper> intercepts pointer events")


def _navigates(page):
    page.url = "https://careers.example.com/apply/form"


@pytest.fixture(autouse=True)
def _plain_clicks(monkeypatch):
    monkeypatch.setattr(clicks, "is_submit_like", lambda _loc: False)


@pytest.mark.parametrize("on_click", [lambda _page: None, _intercepted])
def test_entry_link_is_followed_when_the_click_goes_nowhere(on_click):
    page = _Page()
    loc = _Loc(page, "/talentcommunity/apply/1443172033/?locale=en_GB", on_click)
    assert fill_buttons._enter(page, None, loc) is page  # noqa: SLF001
    assert page.visited == ["https://careers.example.com/talentcommunity/apply/1443172033/?locale=en_GB"]


@pytest.mark.parametrize(
    ("href", "on_click"),
    [
        ("/apply", _navigates),  # the click worked
        ("#", lambda _page: None),  # a menu toggle with no link of its own
        ("javascript:void(0)", lambda _page: None),
        ("https://tracker.example.net/apply", lambda _page: None),  # another site
        (JOB + "#apply", lambda _page: None),  # the page itself
    ],
)
def test_entry_link_is_not_followed_otherwise(href, on_click):
    page = _Page()
    fill_buttons._enter(page, None, _Loc(page, href, on_click))  # noqa: SLF001
    assert page.visited == []


def test_the_menu_an_entry_click_opened_is_followed_before_the_link():
    page = _Page()
    page.menu_item = _MenuItem(page)
    fill_buttons._enter(page, None, _Loc(page, "/talentcommunity/apply/1/", lambda _page: None))  # noqa: SLF001
    assert page.url == "https://career5.successfactors.eu/careers?company=synthetic"
    assert page.visited == []


def test_a_link_that_bounces_to_the_home_page_hands_back_the_posting():
    link = "https://careers.example.com/talentcommunity/apply/1443172033/?locale=en_GB"
    page = _Page(redirects={link: "https://careers.example.com/"})
    fill_buttons._enter(page, None, _Loc(page, link, lambda _page: None))  # noqa: SLF001
    assert page.visited == [link, JOB]
    assert page.url == JOB


def test_a_refused_entry_click_is_never_bypassed_by_its_link(monkeypatch):
    monkeypatch.setattr(clicks, "is_submit_like", lambda _loc: True)
    page = _Page()
    with pytest.raises(clicks.SubmitRefused):
        fill_buttons._enter(page, None, _Loc(page, "/submit", lambda _page: None))  # noqa: SLF001
    assert page.visited == []


@pytest.mark.parametrize(
    ("merged", "expected"),
    [
        ({"leftovers": [{"label": "Search by Keyword", "reason": "Unrecognized field"},
                        {"label": "Save job", "reason": "Unrecognized field"}]}, True),
        ({"leftovers": [{"label": "Degree", "reason": "No unique matching option"},
                        {"label": "Save job", "reason": "Unrecognized field"}]}, False),
        ({"filled": [{"label": "First Name"}],
          "leftovers": [{"label": "Save job", "reason": "Unrecognized field"}]}, False),
        ({"leftovers": []}, False),
    ],
)
def test_only_unrecognized_controls_is_a_careers_page(merged, expected):
    assert fill_page._only_unrecognized(merged) is expected  # noqa: SLF001


# -- through fill_application ---------------------------------------------------------------


@pytest.fixture
def fill_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    job_dir = tmp_path / "output" / "jobs" / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "run.json").write_text(json.dumps(
        {"job_id": "job-1", "status": "succeeded", "metadata": {"company": "Acme"}}
    ), encoding="utf-8")
    (job_dir / "jd.txt").write_text("Need Python.", encoding="utf-8")
    monkeypatch.setattr(packet, "build_packet", lambda job_id: Packet(
        job_id="job-1", built_at="2026-01-01T00:00:00+00:00", ats="other",
        fields={}, field_hints={},
    ))
    monkeypatch.setattr(profile_mod, "load_profile", lambda: (ApplicantProfile(), False))
    monkeypatch.setattr(preparation, "check", lambda _app: preparation.PreparationEligibility(eligible=True))
    monkeypatch.setattr(data, "load", lambda: MagicMock(all_bullets=lambda: []))
    closed: list[str] = []
    monkeypatch.setattr(browser, "close_target", lambda target: closed.append(target) or True)
    monkeypatch.setattr(browser, "target_id", lambda _context, _page: "new-tab")
    return closed


def _page(url, leftovers=()):
    filler_result = {"filled": [], "leftovers": list(leftovers), "long_text": [],
                     "file_inputs": [], "required_empty": [], "frames_skipped": 0}
    page = MagicMock()
    page.url = url
    page.frames = [page]
    page.evaluate.side_effect = [{"questions": []}, filler_result, []] + [[]] * 20
    none = MagicMock()
    none.count.return_value = 0
    none.first = none
    page.locator.return_value = none
    page.get_by_role.return_value = none
    return page


def _run(monkeypatch, leftovers, *, previous_tab="", fill_mode="initial", posting=JOB):
    app = store_models.Application(
        source="simplify", source_job_id="src-1", company="Acme", role="Intern",
        posting_url=posting, final_url=posting, ats="other", status="ready", job_id="job-1",
        fill={"browser_target_id": previous_tab} if previous_tab else None,
    )
    store.upsert(app)
    page = _page(posting, leftovers)

    @contextmanager
    def _fake_browser():
        connected = MagicMock()
        connected.contexts = [MagicMock()]
        connected.contexts[0].new_page.return_value = page
        yield connected

    monkeypatch.setattr(browser, "cdp_browser", _fake_browser)
    fill.fill_application("src-1", fill_mode=fill_mode)
    return page


def _guard(merged, required_empty=(), is_workday=False):
    run = object.__new__(fill_finish._FillFinish)  # noqa: SLF001 - isolated finish guard
    run.barrier_hit, run.is_workday, run.final_step_reached, run.merged = "", is_workday, False, merged
    run.page = SimpleNamespace(evaluate=lambda _js: {}, inner_text=lambda _sel: "", url=JOB)
    handoffs: list[str] = []
    run._handoff = lambda message, **_kw: handoffs.append(message) or message  # noqa: SLF001
    total = len(merged.get("filled") or []) + len(merged.get("leftovers") or [])
    run._readiness_guard(total, None, list(required_empty))  # noqa: SLF001
    return handoffs


CAREERS_PAGE = {"leftovers": [{"label": "Search by Keyword", "reason": "Unrecognized field"},
                              {"label": "Search by Location", "reason": "Unrecognized field"}]}


def test_a_careers_page_scan_is_reported_as_form_not_reached():
    assert _guard(CAREERS_PAGE) == [fill_outcomes.NO_FORM_MSG]


@pytest.mark.parametrize(
    ("merged", "required_empty", "is_workday"),
    [
        (CAREERS_PAGE, ["Enter verification code digit 1 of six."], False),  # a real step
        (CAREERS_PAGE, (), True),  # Workday steps have their own checks
        ({"filled": [{"label": "First Name"}], **CAREERS_PAGE}, (), False),
    ],
)
def test_a_real_form_step_is_not_mistaken_for_a_careers_page(merged, required_empty, is_workday):
    assert _guard(merged, required_empty, is_workday) == []


def test_a_fresh_fill_closes_the_applications_previous_tab(fill_env, monkeypatch):
    _run(monkeypatch, [{"label": "Save job", "reason": "Unrecognized field"}],
         previous_tab="old-tab", fill_mode="reopen")
    assert fill_env == ["old-tab"]


def test_a_first_fill_has_no_tab_to_close(fill_env, monkeypatch):
    _run(monkeypatch, [{"label": "Save job", "reason": "Unrecognized field"}])
    assert fill_env == []


GREENHOUSE_JOB = "https://boards.greenhouse.io/acme/jobs/111"


@pytest.mark.parametrize(
    ("retained_url", "continued"),
    [
        (GREENHOUSE_JOB + "#app", True),  # still this application
        ("https://boards.greenhouse.io/acme/jobs/222", False),  # another of Acme's jobs
        ("https://mail.google.com/mail/u/0/#inbox", False),  # left the site altogether
        ("https://boards.greenhouse.io/acme", True),  # names no job, stays on the site
    ],
)
def test_continue_checks_the_kept_tab_still_shows_this_application(
    fill_env, monkeypatch, retained_url, continued
):
    retained = _page(retained_url)
    monkeypatch.setattr(browser, "find_target", lambda _context, _target: retained)
    fresh = _run(monkeypatch, [], previous_tab="old-tab", fill_mode="continue",
                 posting=GREENHOUSE_JOB)
    assert fill_env == []  # the applicant's tab is never closed
    assert retained.goto.called is False
    assert fresh.goto.called is not continued
    if not continued:
        assert fresh.goto.call_args.args[0] == GREENHOUSE_JOB
        assert store.get("src-1").fill.browser_target_id == "new-tab"


# -- the captured pages in a real browser (opt-in) -----------------------------------------


def _browser(playwright):
    try:
        return playwright.chromium.launch(headless=True, channel="msedge")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Local Chromium unavailable: {exc}")


@pytest.mark.browser
@pytest.mark.parametrize(
    ("fixture", "posting", "form"),
    [
        ("capgemini_apply_dropdown.html", JOB,
         "https://career5.successfactors.eu/careers?company=capgemitecP3"),
        ("qualtrics_apply_chatbot.html", "https://www.qualtrics.com/careers/us/en/job/8264811/Software-Engineer-I",
         "https://www.qualtrics.com/careers/us/en/apply?jobSeqNo=QUALUS8264811EXTERNALENUS"),
    ],
)
def test_captured_careers_pages_reach_their_form(fixture, posting, form):
    from playwright.sync_api import sync_playwright

    html = (_FORMS / fixture).read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        launched = _browser(playwright)
        try:
            page = launched.new_page()
            page.route(posting, lambda route: route.fulfill(body=html, content_type="text/html"))
            page.route(form, lambda route: route.fulfill(body="<h1>Form</h1>", content_type="text/html"))
            page.goto(posting)
            landed = fill_buttons.find_and_click_apply(page, "other")
            assert landed.url == form
            assert landed.locator("h1").inner_text() == "Form"
        finally:
            launched.close()
