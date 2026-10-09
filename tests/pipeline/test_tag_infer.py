"""Inferred bullet skills: one batched call for uncached texts, a per-text cache, and a
failure that degrades to "no inferred skills" instead of failing the run."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.content import bullet_tags
from resume_tailor.content.data import MasterResume
from resume_tailor.pipeline import tag_infer
from resume_tailor.pipeline.tag_infer import infer as _real_infer


class _Response:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, replies, calls):
        self._replies, self._calls = replies, calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        reply = self._replies(kwargs["messages"][0]["content"])
        if isinstance(reply, Exception):
            raise reply
        return _Response(reply)


class _FakeClient:
    def __init__(self, replies, calls):
        self.messages = _FakeMessages(replies, calls)


def _resume(*texts: str) -> MasterResume:
    return MasterResume.model_validate(
        {
            "contact": {"name": "T", "email": "t@example.com"},
            "experience": [
                {"company": "Acme", "title": "Analyst", "start": "2020", "end": "2021",
                 "bullets": [{"id": f"b{i}", "text": t} for i, t in enumerate(texts, 1)]}
            ],
        }
    )


@pytest.fixture
def model(monkeypatch, tmp_path):
    """Real `infer` behind a fake client that tags every bullet `data visualization`."""
    calls: list[dict] = []
    state = {"fail": False}

    def replies(user: str):
        if state["fail"]:
            return RuntimeError("model unreachable")
        ids = [part.split("'")[0] for part in user.split("<bullet id='")[1:]]
        return tag_infer._SkillTable(
            bullets=[
                tag_infer._BulletSkills(id=i, skills=["Data Visualization", "  ", "a b c d e"])
                for i in ids
            ]
        )

    monkeypatch.setattr(tag_infer, "infer", _real_infer)
    monkeypatch.setattr(tag_infer.llm, "client_for", lambda purpose: _FakeClient(replies, calls))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return calls, state


def test_infers_once_then_reuses_the_cache(model):
    calls, _ = model
    resume = _resume("Built Tableau dashboards", "Ran weekly reviews")
    first = tag_infer.ensure(resume)
    assert first.error is None
    assert first.skills == {
        "Built Tableau dashboards": ["data visualization"],
        "Ran weekly reviews": ["data visualization"],
    }
    assert len(calls) == 1

    again = tag_infer.ensure(resume)
    assert again.skills == first.skills and len(calls) == 1


def test_only_new_text_goes_to_the_model(model):
    calls, _ = model
    tag_infer.ensure(_resume("Built Tableau dashboards"))
    tag_infer.ensure(_resume("Built Tableau dashboards", "Wrote SQL reports"))
    assert len(calls) == 2
    assert "Wrote SQL reports" in calls[1]["messages"][0]["content"]
    assert "Built Tableau dashboards" not in calls[1]["messages"][0]["content"]


def test_a_failed_call_is_reported_not_raised(model):
    _, state = model
    state["fail"] = True
    result = tag_infer.ensure(_resume("Built Tableau dashboards"))
    assert result.skills == {}
    assert result.error and "model unreachable" in result.error


def test_prepare_run_makes_inferred_skills_match(model):
    resume = _resume("Built Tableau dashboards")
    tag_infer.prepare_run(resume)
    bullet = resume.all_bullets()[0]
    assert "data visualization" in bullet_tags.match_tags(bullet)
    assert "data visualization" in bullet_tags.known_terms(resume)
    assert "data visualization" not in bullet_tags.skill_evidence(bullet)


def test_a_different_model_infers_afresh(model, monkeypatch):
    calls, _ = model
    resume = _resume("Built Tableau dashboards")
    tag_infer.ensure(resume)
    monkeypatch.setattr(config, "fingerprint", lambda purpose: "another-model")
    assert tag_infer.cached(resume).skills == {}
    tag_infer.ensure(resume)
    assert len(calls) == 2
