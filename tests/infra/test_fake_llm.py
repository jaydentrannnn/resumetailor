"""The e2e fake model: off by default, guard-clean replies read off the real prompts."""

from __future__ import annotations

import asyncio

import pytest

from resume_tailor.infra import fake_llm, llm
from resume_tailor.pipeline import (
    coverletter,
    facets,
    jd,
    relevance,
    review,
    rewrite_prompts,
    skills,
)
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


@pytest.mark.parametrize(
    "model",
    [
        facets.FacetSelection,
        skills.SkillsSelectionLLM,
        coverletter.CoverLetterLLM,
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
