"""Company facts (`pipeline/company_research.py`): every fact must quote its source."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.pipeline import company_research
from resume_tailor.pipeline.company_research import FactLLM, FactsLLM
from resume_tailor.research.company_store import Source, fact_id

SITE = Source(
    id="s1", kind="site", url="https://acme.example/about", fetched_at="2026-10-20T10:00:00+00:00",
    sha="a1",
    text="Acme Analytics builds dashboards for hospitals.\nFounded in 2012, Acme employs "
         "about 1,200 people in Austin and Boston.\nWe partner with Mayo Clinic.",
)
SOURCES = {"s1": SITE}


def _fact(text, excerpt, *, kind="about", source_id="s1"):
    return FactLLM(text=text, kind=kind, source_id=source_id, excerpt=excerpt)


@pytest.mark.parametrize(("fact", "reason"), [
    (_fact("Acme builds dashboards for hospitals.",
           "Acme Analytics builds dashboards for hospitals."), ""),
    (_fact("Founded in 2012, it has about 1,200 employees.",
           "Founded in 2012, Acme employs about 1,200 people in Austin and Boston."), ""),
    (_fact("Acme builds dashboards for clinics.", "Acme builds dashboards for clinics."),
     "excerpt not in source"),
    (_fact("Acme has about 1,500 employees.",
           "Acme employs about 1,200 people in Austin and Boston."), "number not in excerpt"),
    (_fact("Acme partners with Cleveland Clinic.", "We partner with Mayo Clinic."),
     "'Cleveland' not in excerpt"),
    (_fact("Acme partners with Mayo Clinic.", "We partner with Mayo Clinic.", source_id="s9"),
     "unknown source"),
    (_fact("Acme partners with Mayo Clinic.", "We partner with Mayo Clinic.", kind="pay"),
     "unknown kind"),
])
def test_the_guard_checks_the_excerpt_numbers_and_names(fact, reason):
    assert company_research.check_fact(fact, SOURCES, "Acme Analytics, Inc.") == reason


def test_curly_quotes_and_spacing_do_not_break_the_excerpt_match():
    fact = _fact("It was founded in 2012.", "Founded  in 2012, Acme employs about 1,200")
    assert company_research.check_fact(fact, SOURCES, "Acme Analytics") == ""


class _Reply:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


@pytest.fixture
def research_calls(monkeypatch, tmp_path):
    calls: list[dict] = []
    queue: list = []

    class _Client:
        messages = None

        def __init__(self):
            self.messages = self

        def parse(self, **kwargs):
            calls.append(kwargs)
            return _Reply(queue.pop(0))

    monkeypatch.setattr(company_research.llm, "client_for", lambda purpose: _Client())
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")

    def enqueue(*replies):
        queue.extend(replies)
        return calls

    return enqueue


def test_failing_facts_are_dropped_counted_and_the_reply_is_cached(research_calls):
    reply = FactsLLM(facts=[
        _fact("Acme builds dashboards for hospitals.",
              "Acme Analytics builds dashboards for hospitals."),
        _fact("Acme has 5,000 employees.", "Acme employs about 1,200 people"),
        _fact("Acme builds dashboards for hospitals.",
              "Acme Analytics builds dashboards for hospitals."),
    ])
    calls = research_calls(reply)
    found = company_research.extract("Acme Analytics", [SITE])
    assert [f.text for f in found.facts] == ["Acme builds dashboards for hospitals."]
    assert (found.dropped, found.facts[0].as_of) == (1, "2026-10-20")
    assert calls[0]["model"] == config.model_for("research")
    user = calls[0]["messages"][0]["content"]
    assert "untrusted text" in user and '<source id="s1" kind="site"' in user
    again = company_research.extract("Acme Analytics", [SITE])  # cached: no second call
    assert len(calls) == 1 and [f.id for f in again.facts] == [f.id for f in found.facts]


def test_removed_facts_stay_removed(research_calls):
    text = "Acme builds dashboards for hospitals."
    research_calls(FactsLLM(facts=[_fact(text, "Acme Analytics builds dashboards for hospitals.")]))
    found = company_research.extract("Acme Analytics", [SITE], removed=[fact_id(text)])
    assert found.facts == [] and found.dropped == 0


def test_an_unparseable_reply_raises(research_calls):
    research_calls(None)
    with pytest.raises(RuntimeError, match="parseable"):
        company_research.extract("Acme Analytics", [SITE])
