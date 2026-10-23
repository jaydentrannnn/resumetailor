"""Polite, guarded GETs (`infra/polite_fetch.py`), offline through `httpx.MockTransport`."""

from __future__ import annotations

import httpcore
import httpx
import pytest

from resume_tailor.infra import polite_fetch

_DNS = {
    "example.com": ["93.184.216.34"],
    "www.example.com": ["93.184.216.34"],
    "127.0.0.1.nip.io": ["127.0.0.1"],
    "localhost": ["127.0.0.1", "::1"],
    "metadata.example.org": ["169.254.169.254"],
    "split.example.net": ["93.184.216.35", "10.0.0.7"],
}


@pytest.fixture(autouse=True)
def _dns(monkeypatch):
    # IP literals resolve to themselves, as getaddrinfo does.
    monkeypatch.setattr(polite_fetch, "_resolve", lambda host, port: _DNS.get(host, [host]))


def _fetcher(routes: dict[str, httpx.Response], seen: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        return routes.get(url, httpx.Response(404))

    return polite_fetch.Fetcher(transport=httpx.MockTransport(handler))


def _page(text="<p>Hello</p>", media="text/html; charset=utf-8"):
    return httpx.Response(200, headers={"content-type": media}, text=text)


def test_a_page_is_fetched_with_an_honest_user_agent_and_robots_read_once():
    seen: list[str] = []
    agents: list[str] = []
    routes = {"https://example.com/about": _page(), "https://example.com/news": _page("<p>N</p>")}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        agents.append(request.headers["user-agent"])
        return routes.get(str(request.url), httpx.Response(404))

    with polite_fetch.Fetcher(transport=httpx.MockTransport(handler)) as fetcher:
        assert fetcher.get("https://example.com/about").text == "<p>Hello</p>"
        fetcher.get("https://example.com/news")
    assert seen.count("https://example.com/robots.txt") == 1
    assert all(a.startswith("ResumeTailor/") for a in agents)


def test_robots_rules_and_an_unreadable_robots_txt_block_the_page():
    disallow = httpx.Response(200, text="User-agent: *\nDisallow: /careers\n")
    blocked = _fetcher({"https://example.com/robots.txt": disallow,
                        "https://example.com/careers": _page()})
    with blocked, pytest.raises(polite_fetch.FetchError, match="robots.txt"):
        blocked.get("https://example.com/careers")
    unreadable = _fetcher({"https://example.com/robots.txt": httpx.Response(503),
                           "https://example.com/about": _page()})
    with unreadable, pytest.raises(polite_fetch.FetchError, match="robots.txt"):
        unreadable.get("https://example.com/about")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1.nip.io/",
    "http://localhost/",
    "http://[::ffff:127.0.0.1]/",
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.example.org/",
    "http://192.168.1.1/",
    "http://split.example.net/",  # one private answer is enough to refuse
])
def test_hosts_that_are_not_public_are_refused(url):
    with _fetcher({}) as fetcher, pytest.raises(polite_fetch.FetchError, match="not a public"):
        fetcher.get(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x",
                                 "https://user:pw@example.com/"])
def test_other_schemes_and_credentials_in_the_address_are_refused(url):
    with _fetcher({}) as fetcher, pytest.raises(polite_fetch.FetchError):
        fetcher.get(url)


def test_each_redirect_hop_is_checked_again():
    hop = httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
    fetcher = _fetcher({"https://example.com/go": hop})
    with fetcher, pytest.raises(polite_fetch.FetchError, match="not a public"):
        fetcher.get("https://example.com/go")


def test_redirects_are_followed_up_to_five_times():
    routes = {f"https://example.com/{i}": httpx.Response(
        301, headers={"location": f"/{i + 1}"}) for i in range(6)}
    routes["https://example.com/3"] = httpx.Response(301, headers={"location": "https://www.example.com/x"})
    routes["https://www.example.com/x"] = _page("<p>Moved</p>")
    with _fetcher(routes) as fetcher:
        fetched = fetcher.get("https://example.com/0")
        assert (fetched.url, fetched.text) == ("https://www.example.com/x", "<p>Moved</p>")
        routes["https://example.com/3"] = httpx.Response(301, headers={"location": "/4"})
        with pytest.raises(polite_fetch.FetchError, match="too many"):
            fetcher.get("https://example.com/0")


def test_the_body_is_capped_and_only_pages_are_read(monkeypatch):
    monkeypatch.setattr(polite_fetch, "MAX_BYTES", 1000)
    with _fetcher({"https://example.com/big": _page("x" * 1001),
                   "https://example.com/file.pdf": _page("%PDF", "application/pdf")}) as fetcher:
        with pytest.raises(polite_fetch.FetchError, match="more than"):
            fetcher.get("https://example.com/big")
        with pytest.raises(polite_fetch.FetchError, match="not a page"):
            fetcher.get("https://example.com/file.pdf")


def test_json_is_parsed_and_bad_json_is_an_error():
    good = httpx.Response(200, json={"name": "Acme"})
    bad = httpx.Response(200, headers={"content-type": "application/json"}, text="{oops")
    with _fetcher({"https://example.com/a.json": good, "https://example.com/b.json": bad}) as f:
        assert f.get_json("https://example.com/a.json") == {"name": "Acme"}
        with pytest.raises(polite_fetch.FetchError, match="parse"):
            f.get_json("https://example.com/b.json")


def test_the_real_transport_checks_the_address_again_when_it_connects():
    transport = polite_fetch._transport()
    backend = transport._pool._network_backend
    assert isinstance(backend, polite_fetch._GuardedBackend)
    with pytest.raises(httpcore.ConnectError, match="not a public"):
        backend.connect_tcp("127.0.0.1.nip.io", 80)
