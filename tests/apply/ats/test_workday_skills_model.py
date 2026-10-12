"""Workday Skills: an overloaded model is named, and skills fall to review quickly."""

from __future__ import annotations

from resume_tailor.apply.ats import workday_skills
from resume_tailor.infra import llm


class _Page:
    def evaluate(self, _script, *_args):
        return [{"field": "formField-skills", "label": "Type to Add Skills", "input_id": "s1"}]


def _stub_searches(monkeypatch):
    monkeypatch.setattr(workday_skills, "remove_duplicate_chips", lambda *_a: None)
    monkeypatch.setattr(workday_skills, "_chips", lambda *_a: [])
    monkeypatch.setattr(workday_skills, "_entered_chip", lambda *_a: None)
    monkeypatch.setattr(
        workday_skills, "_search_prompt", lambda _p, _i, _skill: ["Container Platforms", "Infrastructure Tools"]
    )


def test_model_overload_names_the_status_and_leaves_skills_for_review(monkeypatch):
    _stub_searches(monkeypatch)
    lines: list[str] = []

    def overloaded(_unmatched):
        raise llm.LLMError("gemini returned HTTP 503: model overloaded")

    committed, review = workday_skills.fill_skills(
        _Page(), ["Kubernetes", "Terraform"], choose_many=overloaded, progress=lines.append,
    )
    assert committed == []
    assert sorted(review) == ["Kubernetes", "Terraform"]
    assert any(
        "model unavailable, HTTP 503" in line and "2 skill(s) left for review" in line
        for line in lines
    )
