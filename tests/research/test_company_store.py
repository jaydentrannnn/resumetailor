"""Saved company research (`research/company_store.py`) and one run (`company_run.py`)."""

from __future__ import annotations

from datetime import date

import pytest

from resume_tailor.pipeline import company_research
from resume_tailor.research import company_run, company_sources, company_store
from resume_tailor.research.company_store import CompanyResearch, Fact, Source


def _research(**kw):
    return CompanyResearch(company="Acme, Inc.", researched_at="2026-10-01T00:00:00+00:00",
                           **kw)


def test_one_file_per_company_and_removed_facts_are_remembered():
    fact = Fact(id="f1", text="Acme builds dashboards.", kind="about", source_id="s1",
                excerpt="Acme builds dashboards.")
    company_store.save(_research(facts=[fact]))
    assert company_store.slug("Acme") == company_store.slug("ACME, Inc.") == "acme"
    assert company_store.load("acme").facts == [fact]
    assert company_store.remove_fact("Acme", "f1").removed == ["f1"]
    assert company_store.load("Acme").facts == []
    assert company_store.remove_fact("Acme", "f1") is None
    assert company_store.load("Globex") is None


def test_research_is_stale_after_thirty_days():
    research = _research()
    assert not company_store.is_stale(research, date(2026, 10, 31))
    assert company_store.is_stale(research, date(2026, 11, 1))
    assert company_store.is_stale(CompanyResearch(company="X"))


def _src(kind, text, url=None):
    return company_sources._source(kind, text, url=url)


@pytest.fixture
def fake_run(monkeypatch):
    calls = {"automatic": 0, "added": []}

    def automatic(**kw):
        calls["automatic"] += 1
        return company_sources.Gathered([_src("posting", "Acme builds dashboards.")],
                                        searched_with="brave")

    def added(*, urls, notes, fetcher):
        calls["added"].append((list(urls), list(notes)))
        return company_sources.Gathered(
            [*(_src("page", f"Page {u}.", u) for u in urls), *(_src("note", n) for n in notes)]
        )

    def extract(company, sources, *, removed=()):
        return company_research.Extraction([], 0, "fake")

    monkeypatch.setattr(company_sources, "automatic", automatic)
    monkeypatch.setattr(company_sources, "added", added)
    monkeypatch.setattr(company_research, "extract", extract)
    return calls


def test_adding_a_note_keeps_what_was_read_and_refresh_reads_it_all_again(fake_run):
    first = company_run.run(company="Acme", jd_text="x", fetcher=object())
    assert [s.kind for s in first.sources] == ["posting"] and fake_run["automatic"] == 1
    more = company_run.run(company="Acme", urls=["https://acme.example/team"],
                           notes=["Met them at the fair."], fetcher=object())
    assert [s.kind for s in more.sources] == ["posting", "page", "note"]
    assert fake_run["automatic"] == 1 and more.researched_at == first.researched_at
    again = company_run.run(company="Acme", refresh=True, fetcher=object())
    assert fake_run["automatic"] == 2
    assert fake_run["added"][-2] == (["https://acme.example/team"], ["Met them at the fair."])
    assert [s.kind for s in again.sources] == ["posting", "page", "note"]


def test_nothing_to_read_is_an_error(fake_run, monkeypatch):
    monkeypatch.setattr(company_sources, "automatic", lambda **kw: company_sources.Gathered())
    with pytest.raises(company_run.NothingToRead):
        company_run.run(company="Acme", fetcher=object())


def test_long_sources_beyond_the_budget_are_left_out(monkeypatch):
    monkeypatch.setattr(company_run, "PROMPT_CHARS", 10)
    warnings: list[str] = []
    kept = company_run._within_budget(
        [Source(id="a", kind="note", text="12345"), Source(id="b", kind="note", text="x" * 20),
         Source(id="c", kind="note", text="12345")], warnings)
    assert [s.id for s in kept] == ["a", "c"]
    assert warnings == ["1 longer page left out to keep the request short."]
