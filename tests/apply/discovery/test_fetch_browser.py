"""`fetch_browser.read`: custom careers sites that never go quiet or reload mid-read, closed
pages, and pages that hand over to LinkedIn (never loaded)."""

from __future__ import annotations

from contextlib import contextmanager

import httpx
import pytest

from resume_tailor.apply.discovery import fetch_browser, fetch_jd

_BODY = "Design automation for battery cell lines in Python and PLCs. " * 10
_URL = "https://www.tesla.com/careers/search/job/286986"


class _Request:
    def __init__(self, url, frame):
        self.url = url
        self.frame = frame

    def is_navigation_request(self):
        return True


class _Route:
    def __init__(self, request):
        self.request = request
        self.aborted = False

    def abort(self):
        self.aborted = True


class _Page:
    """A tab whose reads return ``reads`` in turn (an exception is raised); ``redirect_to``
    is a navigation the page tries during ``goto``."""

    def __init__(self, reads, *, url=_URL, idle_error=None, redirect_to=None, frames=()):
        self._reads = list(reads)
        self.url = url
        self.main_frame = object()
        self.frames = [self.main_frame, *frames]
        self._idle_error = idle_error
        self._redirect_to = redirect_to
        self.routes = []
        self.aborted = []

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def goto(self, url, **kwargs):
        if self._redirect_to:
            for pattern, handler in self.routes:
                if pattern.search(self._redirect_to):
                    route = _Route(_Request(self._redirect_to, self.main_frame))
                    handler(route)
                    if route.aborted:
                        self.aborted.append(self._redirect_to)
                        raise RuntimeError("Page.goto: net::ERR_FAILED")

    def wait_for_load_state(self, state, **kwargs):
        if state == "networkidle" and self._idle_error:
            raise self._idle_error

    def wait_for_timeout(self, *args):
        pass

    def evaluate(self, script):
        read = self._reads.pop(0)
        if isinstance(read, Exception):
            raise read
        return read

    def close(self):
        pass


def _use(monkeypatch, page):
    class _Context:
        def new_page(self):
            return page

    class _Browser:
        contexts = [_Context()]

    @contextmanager
    def browser():
        yield _Browser()

    monkeypatch.setattr(fetch_browser, "cdp_browser", browser)


def test_a_page_that_never_goes_network_idle_is_still_read(monkeypatch):
    page = _Page([{"text": _BODY}], idle_error=TimeoutError("Timeout 10000ms exceeded."))
    _use(monkeypatch, page)
    result = fetch_browser.read(_URL)
    assert result.method == "browser"
    assert "battery cell lines" in result.text


def test_a_page_that_reloads_mid_read_is_read_again(monkeypatch):
    destroyed = RuntimeError(
        "Execution context was destroyed, most likely because of a navigation"
    )
    page = _Page([destroyed, {"text": _BODY}])
    _use(monkeypatch, page)
    assert fetch_browser.read(_URL).method == "browser"


def test_other_read_errors_still_fail_the_read(monkeypatch):
    _use(monkeypatch, _Page([RuntimeError("Target page, context or browser has been closed")]))
    with pytest.raises(RuntimeError, match="has been closed"):
        fetch_browser.read(_URL)


class _Frame:
    def __init__(self, url, text):
        self.url = url
        self._text = text

    def evaluate(self, script):
        if isinstance(self._text, Exception):
            raise self._text
        return {"text": self._text, "hidden": []}


def test_a_posting_shown_in_an_ats_frame_is_read_with_the_page(monkeypatch):
    """SeatGeek shows the description in a Greenhouse frame; the page's own text is only
    its title and site chrome. Ads and trackers in other frames are not read."""
    chrome = "Sports Music Shows Cities Sign in View all jobs Software Engineer - New Grad"
    frames = [
        _Frame("https://job-boards.greenhouse.io/embed/job_app?for=seatgeek&token=8227548",
               _BODY),
        _Frame("https://insight.adsrvr.org/track/cei?advertiser_id=1", "Ad text"),
        _Frame("https://job-boards.greenhouse.io/embed/detached",
               RuntimeError("Frame was detached")),
    ]
    _use(monkeypatch, _Page([{"text": chrome}], url="https://seatgeek.com/jobs/8227548",
                            frames=frames))
    result = fetch_browser.read("https://seatgeek.com/jobs/8227548")
    assert result.method == "browser"
    assert result.text.startswith(chrome) and "battery cell lines" in result.text
    assert "Ad text" not in result.text


def test_a_page_saying_the_job_is_gone_is_closed(monkeypatch):
    url = "https://jobs.ashbyhq.com/opengov/35c2d853-b6ab-4ba7-a6f7-ffb4cfc22f7b"
    _use(monkeypatch, _Page([{"text": "Job not found\nThe job you requested was not found."}], url=url))
    result = fetch_browser.read(url)
    assert result.closed.startswith("Posting closed")
    assert result.method == "failed"


def test_a_handover_to_linkedin_is_stopped_before_it_loads(monkeypatch):
    target = "https://www.linkedin.com/jobs/view/4481121442/?trk=appcast"
    page = _Page([], url="https://click.appcast.io/t/abc", redirect_to=target)
    _use(monkeypatch, page)
    result = fetch_browser.read("https://www.adzuna.com/land/ad/5938940362")
    assert page.aborted == [target]
    assert result.ats == "linkedin"
    assert result.final_url == target
    assert "LinkedIn" in result.error


@pytest.mark.parametrize(
    ("url", "refused"),
    [
        ("https://www.linkedin.com/jobs/view/1", True),
        ("https://linkedin.com/", True),
        ("https://uk.indeed.com/viewjob?jk=1", True),
        ("https://www.notlinkedin.com/jobs/1", False),
        ("https://boards.greenhouse.io/x/jobs/1?src=linkedin.com", False),
    ],
)
def test_never_visit_matches_only_linkedin_and_indeed_hosts(url, refused):
    assert bool(fetch_browser._NEVER_VISIT.search(url)) is refused


def test_an_adzuna_landing_link_is_read_from_its_details_page(monkeypatch):
    fetched: list[str] = []

    def get(url, **kwargs):
        fetched.append(url)
        return httpx.Response(403, request=httpx.Request("GET", url))

    read_urls: list[str] = []

    def read(url):
        read_urls.append(url)
        return fetch_jd.FetchResult(final_url=url, ats="unknown", text=_BODY, method="browser")

    monkeypatch.setattr(fetch_jd.httpx, "get", get)
    monkeypatch.setattr(fetch_browser, "read", read)
    fetch_jd.fetch_jd("https://www.adzuna.com/land/ad/5938940362?se=abc&utm_medium=api")
    assert fetched == ["https://www.adzuna.com/details/5938940362"]
    assert read_urls == ["https://www.adzuna.com/details/5938940362"]


def test_fetch_errors_keep_only_their_first_line(monkeypatch):
    def get(url, **kwargs):
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed\nmore detail")

    def read(url):
        raise RuntimeError("Page.goto: net::ERR_INTERNET_DISCONNECTED\nCall log:\n  - navigating")

    monkeypatch.setattr(fetch_jd.httpx, "get", get)
    monkeypatch.setattr(fetch_browser, "read", read)
    result = fetch_jd.fetch_jd("https://jobs.example.com/role/1")
    assert result.error == (
        "[Errno 11001] getaddrinfo failed; browser: Page.goto: net::ERR_INTERNET_DISCONNECTED"
    )
