"""``POST /api/jobs/{id}/answer``: context, full-resume and regenerate options."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from resume_tailor import config
from resume_tailor.apply.answers.answer import AnswerExtras, AnswerResult
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.pipeline.jd import JobRequirements
from resume_tailor.web.routes import applications
from tests.fixtures import synthetic_resume


@pytest.fixture
def answer_route(client, monkeypatch):
    http, _queue = client
    """A succeeded run on disk with ``answer_question`` stubbed to record its kwargs."""
    out_dir = config.OUTPUT_DIR / "jobs" / "ask01"
    out_dir.mkdir(parents=True, exist_ok=True)
    resume = synthetic_resume()
    tailored = {resume.all_bullets()[0].id: "Tailored text."}
    (out_dir / "bullets.json").write_text(json.dumps(tailored), encoding="utf-8")
    (out_dir / "requirements.json").write_text(
        JobRequirements(title="Engineer", seniority="entry", keywords=[]).model_dump_json(),
        encoding="utf-8",
    )
    (out_dir / "jd.txt").write_text("Engineer role.", encoding="utf-8")
    profile = ApplicantProfile(city="Irvine", email="me@example.com", salary_expectation="$50")
    seen: dict = {}

    def fake_answer(question, **kwargs):
        seen.update(kwargs, question=question)
        return AnswerResult(answer="Drafted.", source="llm", model="fake")

    monkeypatch.setattr(applications, "_resolve_run", lambda _id: SimpleNamespace(
            status="succeeded", metadata=SimpleNamespace(company="Acme Robotics")
        ))
    monkeypatch.setattr(applications.data, "load", lambda: resume)
    monkeypatch.setattr(applications.apply_profile, "load_profile", lambda: (profile, False))
    monkeypatch.setattr(applications, "answer_question", fake_answer)
    return http, seen, resume, tailored


def test_defaults_keep_run_bullets_and_send_no_extras(answer_route):
    """The MCP shape (question + max_chars only) is unchanged."""
    client, seen, _resume, tailored = answer_route
    res = client.post("/api/jobs/ask01/answer", json={"question": "Why us?"})
    assert res.status_code == 200 and res.json()["answer"] == "Drafted."
    assert seen["bullets"] == tailored
    assert seen["extras"] == AnswerExtras(company="Acme Robotics")
    assert seen["use_cache"] is True


def test_full_resume_sends_every_bullet_and_only_safe_profile_facts(answer_route):
    """``full_resume`` swaps in the whole resume; contact and salary stay out."""
    client, seen, resume, _tailored = answer_route
    res = client.post(
        "/api/jobs/ask01/answer",
        json={"question": "Why us?", "context": "I led a club.", "full_resume": True,
              "regenerate": True},
    )
    assert res.status_code == 200
    assert set(seen["bullets"]) == {b.id for b in resume.all_bullets()}
    assert seen["extras"] == AnswerExtras(
        company="Acme Robotics",
        facts=("City: Irvine", "Country: United States"),
        context="I led a club.",
    )
    assert seen["use_cache"] is False


def test_cli_run_without_backends_uses_the_one_off_profile(answer_route, monkeypatch):
    """No ``backends.json`` means the one-off profile, never the claude fallback."""
    client, _seen, _resume, _tailored = answer_route
    pinned: list[str] = []
    real = config.pinned

    def spy(spec, *args, **kwargs):
        pinned.append(spec)
        return real(spec, *args, **kwargs)

    monkeypatch.setattr(config, "pinned", spy)
    assert client.post("/api/jobs/ask01/answer", json={"question": "Why?"}).status_code == 200
    assert pinned == [config.ONE_OFF_PROFILE]
