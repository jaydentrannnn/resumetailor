"""Brave and Tavily search (`research/web_search.py`), with httpx stubbed."""

from __future__ import annotations

import httpx
import pytest

from resume_tailor import config
from resume_tailor.research import web_search

_REQUEST = httpx.Request("GET", "https://api.example")


@pytest.fixture
def keys(monkeypatch):
    saved: dict[str, str] = {}
    monkeypatch.setattr(config, "credential", lambda name: saved.get(name, ""))
    return saved


def test_queries_carry_only_the_company_name():
    assert web_search.company_queries(' Acme "Analytics" ') == [
        '"Acme Analytics" official site', '"Acme Analytics" news']
    assert web_search.company_queries("") == []


def test_no_key_means_no_search(keys, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("searched without a key"))
    assert web_search.provider() is None
    assert web_search.search('"Acme" news') == []


def test_brave_is_preferred_and_its_results_are_read(keys, monkeypatch):
    keys.update(BRAVE_SEARCH_API_KEY="b-secret", TAVILY_API_KEY="t-secret")
    seen = {}

    def get(url, *, params, headers, timeout):
        seen.update(url=url, params=params, token=headers["X-Subscription-Token"])
        return httpx.Response(200, request=_REQUEST, json={"web": {"results": [
            {"title": "Acme", "url": "https://acme.example/", "description": "Home"},
            {"title": "Bad", "url": "javascript:alert(1)", "description": ""},
        ]}})

    monkeypatch.setattr(httpx, "get", get)
    assert web_search.search('"Acme" official site', 3) == [
        web_search.Hit("Acme", "https://acme.example/", "Home")]
    assert seen == {"url": web_search._BRAVE, "params": {"q": '"Acme" official site', "count": 3},
                    "token": "b-secret"}


def test_tavily_results_are_read(keys, monkeypatch):
    keys.update(TAVILY_API_KEY="t-secret")

    def post(url, *, json, headers, timeout):
        assert headers["Authorization"] == "Bearer t-secret" and json["max_results"] == 5
        return httpx.Response(200, request=_REQUEST, json={"results": [
            {"title": "News", "url": "https://news.example/a", "content": "Snippet"}]})

    monkeypatch.setattr(httpx, "post", post)
    assert web_search.search('"Acme" news') == [
        web_search.Hit("News", "https://news.example/a", "Snippet")]


def test_a_rejected_key_is_an_error_that_never_shows_the_key(keys, monkeypatch):
    keys.update(BRAVE_SEARCH_API_KEY="b-secret")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(401, request=_REQUEST))
    with pytest.raises(web_search.SearchError) as raised:
        web_search.search('"Acme" news')
    assert str(raised.value) == "Brave search rejected the key."
    assert raised.value.__cause__ is None and "b-secret" not in repr(raised.value)
