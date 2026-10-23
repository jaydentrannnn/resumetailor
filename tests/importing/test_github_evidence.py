"""GitHub repositories as evidence sources (`importing/github_evidence.py`), offline."""

from __future__ import annotations

import json

import httpx
import pytest

from resume_tailor import config
from resume_tailor.importing import evidence_sources, github_evidence
from resume_tailor.infra import polite_fetch

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"


@pytest.fixture(autouse=True)
def _dns(monkeypatch):
    monkeypatch.setattr(polite_fetch, "_resolve", lambda host, port: ["140.82.112.6"])


def _repo(name: str, *, fork: bool = False) -> dict:
    return {"name": name, "owner": {"login": "jordan"}, "fork": fork,
            "html_url": f"https://github.com/jordan/{name}", "description": f"{name}  app",
            "pushed_at": "2026-09-01T10:00:00Z"}


def _fetcher(routes: dict[str, object], seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = routes.get(str(request.url))
        if body is None:
            return httpx.Response(404)
        if isinstance(body, int):
            return httpx.Response(body)
        if isinstance(body, str):
            return httpx.Response(200, headers={"content-type": "text/plain"}, text=body)
        return httpx.Response(200, headers={"content-type": "application/json"},
                              text=json.dumps(body))

    return polite_fetch.Fetcher(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(("text", "expected"), [
    ("octocat", ("octocat", None)),
    ("@octocat", ("octocat", None)),
    ("https://github.com/octocat/", ("octocat", None)),
    ("github.com/octocat/Hello-World.git", ("octocat", "Hello-World")),
    ("https://github.com/octocat/my.repo/tree/main/src", ("octocat", "my.repo")),
])
def test_a_username_or_repository_link_is_read(text, expected):
    assert github_evidence.parse_target(text) == expected


def test_anything_else_is_refused():
    with pytest.raises(github_evidence.GitHubError):
        github_evidence.parse_target("https://gitlab.com/octocat")
    assert github_evidence.username("not a github field!") == ""


@pytest.mark.parametrize(("fork", "rows", "expected"), [
    (True, [], ("fork", None)),
    (False, [{"login": "Jordan", "contributions": 9}, {"login": "x", "contributions": 1}], ("own", 0.9)),
    (False, [{"login": "jordan", "contributions": 3}, {"login": "x", "contributions": 7}], ("contributed", 0.3)),
    (False, [{"login": "x", "contributions": 7}], ("unknown", None)),
    (False, [], ("unknown", None)),
])
def test_attribution_comes_from_the_students_share_of_commits(fork, rows, expected):
    assert github_evidence.attribution(fork, rows, "jordan") == expected


def test_a_user_lists_owned_repos_and_forks_cost_no_further_reads(monkeypatch):
    monkeypatch.setattr(config, "credential", lambda name: "tok-123" if name == "GITHUB_TOKEN" else "")
    seen: list[httpx.Request] = []
    routes = {
        f"{API}/users/jordan/repos?type=owner&sort=pushed&per_page=20": [_repo("chef"), _repo("lib", fork=True)],
        f"{API}/repos/jordan/chef/languages": {"Python": 900, "HTML": 100},
        f"{API}/repos/jordan/chef/contributors?per_page=100": [{"login": "jordan", "contributions": 12}],
        f"{RAW}/jordan/chef/HEAD/readme.md": "# Chef\n![badge](x.svg)\nA [Flask](https://f) app.\n```\npip install\n```",
    }
    with _fetcher(routes, seen) as fetcher:
        repos, warnings = github_evidence.read("jordan", fetcher)

    chef, lib = repos
    assert (chef.attribution, chef.commit_share, chef.languages) == ("own", 1.0, ["Python", "HTML"])
    assert chef.readme == "# Chef\nA Flask app."
    assert lib.attribution == "fork" and not any("/lib/" in str(r.url) for r in seen)
    assert warnings == []
    api = [r for r in seen if r.url.host == "api.github.com" and r.url.path != "/robots.txt"]
    raw = [r for r in seen if r.url.host == "raw.githubusercontent.com"]
    assert all(r.headers["authorization"] == "Bearer tok-123" for r in api)
    assert all("authorization" not in r.headers for r in raw)

    source = evidence_sources.from_repo(chef)
    assert source.text.splitlines()[:3] == [
        "Repository: jordan/chef", "Description: chef app",
        "Languages (detected by GitHub): Python, HTML",
    ]


def test_hitting_the_hourly_limit_keeps_what_was_read_and_says_why():
    routes = {
        f"{API}/users/jordan/repos?type=owner&sort=pushed&per_page=20": [_repo("a"), _repo("b")],
        f"{API}/repos/jordan/a/languages": {},
        f"{API}/repos/jordan/a/contributors?per_page=100": [],
        f"{API}/repos/jordan/b/languages": 403,
    }
    with _fetcher(routes, []) as fetcher:
        repos, warnings = github_evidence.read("jordan", fetcher)
    assert [r.name for r in repos] == ["a"]
    assert "Stopped after 1 repositories" in warnings[0] and "GitHub token" in warnings[0]


def test_an_unknown_account_is_a_plain_error():
    with _fetcher({}, []) as fetcher, pytest.raises(github_evidence.GitHubError, match="no public account"):
        github_evidence.read("nobody", fetcher)


def test_one_repository_link_reads_that_repository_for_the_resume_owner():
    routes = {
        f"{API}/repos/acme/tool": {**_repo("tool"), "owner": {"login": "acme"}},
        f"{API}/repos/acme/tool/languages": {"Go": 1},
        f"{API}/repos/acme/tool/contributors?per_page=100": [
            {"login": "jordan", "contributions": 2}, {"login": "pat", "contributions": 8}],
    }
    with _fetcher(routes, []) as fetcher:
        (repo,), _ = github_evidence.read("github.com/acme/tool", fetcher, user="jordan")
    assert (repo.full_name, repo.attribution, repo.commit_share) == ("acme/tool", "contributed", 0.2)
