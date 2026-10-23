"""The e2e fake model: off by default, guard-clean replies read off the real prompts."""

from __future__ import annotations

import asyncio

import pytest

from resume_tailor.infra import fake_llm, llm
from resume_tailor.pipeline import (
    company_research,
    coverletter_models,
    facets_models,
    followup_note,
    interview_prep,
    jd,
    relevance,
    review,
    rewrite_prompts,
    skills,
)
from resume_tailor.research.company_store import Source
from tests.fixtures import synthetic_resume


def test_off_unless_the_variable_is_set(monkeypatch):
    monkeypatch.delenv(fake_llm.ENV, raising=False)
    assert not fake_llm.enabled()
    monkeypatch.setenv(fake_llm.ENV, "1")
    assert isinstance(llm.client_for("rewrite"), fake_llm.FakeClient)
    assert isinstance(llm.async_client_for("answer"), fake_llm.AsyncFakeClient)


def test_rewrite_echoes_each_bullet_from_the_real_prompt_format():
    resume = synthetic_resume()
    bullets = [b for exp in resume.experience for b in exp.bullets]
    prompt = rewrite_prompts._format_bullets(bullets, 180)
    result = fake_llm.reply(rewrite_prompts.RewriteResult, prompt)
    assert [(b.id, b.text) for b in result.bullets] == [(b.id, b.text) for b in bullets]
    scores = fake_llm.reply(relevance.ScoreTable, prompt)
    assert [s.id for s in scores.scores] == [b.id for b in bullets]


def test_extraction_keeps_known_tags_named_in_the_posting():
    prompt = jd._build_user_message(
        "Data Analyst Intern\nWe use Python and SQL.", ["python", "sql", "rust"]
    )
    parsed = fake_llm.reply(jd.JobRequirements, prompt)
    assert [k.canonical for k in parsed.keywords] == ["python", "sql"]
    assert parsed.title == "Data Analyst Intern"


def test_prep_retells_a_sent_bullet_and_the_note_passes_its_guard():
    resume = synthetic_resume()
    bullets = {b.id: b.text for exp in resume.experience for b in exp.bullets}
    prompt = interview_prep._request(
        "technical", role="Analyst", company="Acme", requirements=None, bullets=bullets,
        cover_letter="", jd_text="", gaps=(), notes=(),
    )
    prep = fake_llm.reply(interview_prep.PrepLLM, prompt)
    [story] = prep.stories
    assert (story.bullet_ids, story.action) == (list(bullets)[:1], next(iter(bullets.values())))
    note = fake_llm.reply(followup_note.FollowupLLM, "")
    assert followup_note._offenders(resume, bullets, "", note.body, []) == []


def test_company_facts_quote_each_source_and_pass_their_guard():
    sources = [
        Source(id="s1", kind="site", text="Acme builds dashboards. It was founded in 2012."),
        Source(id="s2", kind="note", text="Acme partners with Mayo Clinic!"),
    ]
    reply = fake_llm.reply(company_research.FactsLLM, company_research.prompt("Acme", sources))
    assert [(f.source_id, f.text) for f in reply.facts] == [
        ("s1", "Acme builds dashboards."), ("s2", "Acme partners with Mayo Clinic!")]
    by_id = {s.id: s for s in sources}
    assert all(company_research.check_fact(f, by_id, "Acme") == "" for f in reply.facts)


@pytest.mark.parametrize(
    "model",
    [
        facets_models.FacetSelection,
        skills.SkillsSelectionLLM,
        coverletter_models.CoverLetterLLM,
        review.ReviewLLM,
    ],
)
def test_other_stages_get_a_valid_minimal_answer(model):
    assert isinstance(fake_llm.reply(model, "<bullet id='a'>x</bullet>"), model)


def test_async_client_parses():
    async def go():
        async with fake_llm.AsyncFakeClient("answer") as client:
            response = await client.messages.parse(
                output_format=rewrite_prompts.RewriteResult,
                messages=[{"content": "<bullet id='b1'>\n  <current>Did it</current>\n</bullet>"}],
            )
        return response.parsed_output

    assert asyncio.run(go()).bullets[0].text == "Did it"
