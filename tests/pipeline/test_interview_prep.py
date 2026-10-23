"""Interview prep (`interview_prep`): guarded stories, probe points and the request."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.pipeline import interview_prep
from resume_tailor.pipeline.interview_prep import PrepLLM, PrepQuestion, PrepStory
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from tests.fixtures import synthetic_resume

SENT = {
    "exp_b1": "Improved reliability & throughput for production services.",
    "proj_b1": "Indexed 1,200 research notes with embeddings.",
}


class _Reply:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _Client:
    def __init__(self, queue, calls):
        self.messages = self
        self._queue, self._calls = queue, calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        return _Reply(self._queue.pop(0))


@pytest.fixture
def prep_calls(monkeypatch):
    calls: list[dict] = []
    queue: list = []
    monkeypatch.setattr(interview_prep.llm, "client_for", lambda purpose: _Client(queue, calls))
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")

    def enqueue(*replies):
        queue.extend(replies)
        return calls

    return enqueue


def _story(ids, **parts):
    fields = dict(situation="", task="", action="", result="")
    return PrepStory(question="Tell me about a project.", bullet_ids=ids, **{**fields, **parts})


def _prepare(**extra):
    # The master resume says "Indexed research notes"; the sent text with "1,200" counts.
    kwargs = dict(
        resume=synthetic_resume(), role="Data Analyst", company="Acme",
        requirements=JobRequirements(
            title="Data Analyst", seniority="entry", domain_notes=["Fraud analytics"],
            keywords=[Keyword(phrase="SQL", canonical="sql", importance="must_have")],
        ),
        bullets=SENT, cover_letter="I am writing to apply.", gaps=["Tableau"],
        notes=["2026-10-01 interview completed: asked about dashboards"],
        based_on="Submitted copy (attempt 1)",
    )
    return interview_prep.prepare("technical", **{**kwargs, **extra})


def test_stories_that_add_facts_are_left_out_and_known_ones_kept(prep_calls):
    calls = prep_calls(PrepLLM(
        questions=[PrepQuestion(question="How did you index notes?", source="requirement",
                                about="SQL"),
                   PrepQuestion(question="  ")],
        stories=[
            _story(["proj_b1", "made-up"], action="I indexed 1,200 research notes."),
            _story(["proj_b1"], action="I indexed notes with Kubernetes."),
            _story(["exp_b1"], result="Throughput went up 40%."),
            _story(["nope"], action="I did it."),
        ],
        ask=["What does the team own?", ""],
    ))
    prep = _prepare()
    assert [s.bullet_ids for s in prep.stories] == [["proj_b1"]]
    assert prep.warnings == [
        "A story was left out: it added Kubernetes, which its bullets don't say.",
        "A story was left out: it added 40, which its bullets don't say.",
        "A story was left out: it cited no bullet from this resume.",
    ]
    assert [q.question for q in prep.questions] == ["How did you index notes?"]
    assert prep.ask == ["What does the team own?"]
    assert (prep.stage, prep.based_on, prep.prompt_version) == (
        "technical", "Submitted copy (attempt 1)", interview_prep._PREP_PROMPT_VERSION)
    [call] = calls
    user = call["messages"][0]["content"]
    for piece in ("<round>Technical interview", "[REQUIRED] SQL", "Fraud analytics",
                  "  - Tableau", "<bullet id='proj_b1'>", "<cover_letter_sent>",
                  "asked about dashboards"):
        assert piece in user
    assert "<job_posting_excerpt>" not in user


def test_without_requirements_the_cleaned_posting_is_sent(prep_calls):
    calls = prep_calls(PrepLLM())
    _prepare(requirements=None, jd_text="Analyst role​. We use SQL.")
    user = calls[0]["messages"][0]["content"]
    assert "<job_posting_excerpt>\nAnalyst role. We use SQL.\n</job_posting_excerpt>" in user
    assert "<role>Data Analyst at Acme</role>" in user


def test_a_sent_story_survives_removal_from_the_master_with_a_warning(prep_calls):
    resume = synthetic_resume()
    resume.projects[0].bullets.clear()
    prep_calls(PrepLLM(stories=[
        _story(["proj_b1"], action="I indexed 1,200 research notes with embeddings."),
    ]))
    prep = _prepare(resume=resume)
    assert [s.bullet_ids for s in prep.stories] == [["proj_b1"]]
    assert any("no longer" in w and "master resume" in w for w in prep.warnings)


def test_current_master_skills_and_tags_cannot_support_a_sent_story(prep_calls):
    resume = synthetic_resume()
    resume.skills[0].items.append("Kubernetes")
    resume.projects[0].bullets[0].tags.append("Kubernetes")
    prep_calls(PrepLLM(stories=[
        _story(["proj_b1"], action="I indexed notes with Kubernetes."),
    ]))
    prep = _prepare(resume=resume)
    assert prep.stories == []
    assert any("added Kubernetes" in w for w in prep.warnings)


def test_an_unparseable_reply_raises(prep_calls):
    prep_calls(None)
    with pytest.raises(RuntimeError, match="interview prep"):
        _prepare()


def test_probe_points_list_numbers_first_then_ownership():
    points = interview_prep.probe_points({
        "a": "Led the migration to a new queue.",
        "b": "Cut latency by 30%.",
        "c": "Attended weekly standups.",
    })
    assert [(p.bullet_id, p.reasons) for p in points] == [
        ("b", ["number"]), ("a", ["ownership"])]
