"""Editor/backend parity and chronological order at the model/render boundary."""

import json
from pathlib import Path

import pytest
from docx import Document
from docxtpl import DocxTemplate

from resume_tailor.content.data import MasterResume
from resume_tailor.content.entry_order import entry_date_key
from resume_tailor.document import render

CASES = json.loads((Path(__file__).parents[1] / "fixtures/entry_order_cases.json").read_text(encoding="utf-8"))


def _expected_month(text):
    if text == "Present":
        return 999999
    if not text:
        return 0
    year, month = map(int, text.split("-"))
    return year * 12 + month


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_date_cases(case):
    assert entry_date_key(case["entry"]) == tuple(map(_expected_month, case["expected"]))


def _resume():
    def job(id, start, end):
        return {"id": id, "company": id, "title": "Engineer", "start": start, "end": end,
                "bullets": [{"id": f"{id}_b1", "text": f"Built {id} tools", "tags": []}]}

    return MasterResume.model_validate({
        "contact": {"name": "Test User", "email": "test@example.com"},
        "sections": [
            {"id": "jobs", "kind": "experience", "title": "Jobs", "entries": [
                job("old", "2020-01", "2021-01"), job("now", "2024-01", "Present"),
                job("tie", "2024-01", "Present"), job("unknown", "", ""),
            ]},
            {"id": "research", "kind": "experience", "title": "Research", "entries": [job("research", "2019-01", "2020-01")]},
            {"id": "education", "kind": "education", "title": "Education", "entries": [
                {"school": "Old School", "degree": "BS", "dates": "2020–2024"},
                {"school": "New School", "degree": "MS", "dates": "Expected May 2028"},
            ]},
            {"id": "projects", "kind": "project", "title": "Projects", "entries": [
                {"id": "oldp", "name": "Old Project", "date": "2020", "bullets": [{"id": "p1", "text": "Built tools", "tags": []}]},
                {"id": "newp", "name": "New Project", "date": "Spring 2025", "bullets": [{"id": "p2", "text": "Built tools", "tags": []}]},
            ]},
            {"id": "skills", "kind": "skills", "title": "Skills", "entries": [{"label": "Z", "items": []}, {"label": "A", "items": []}]},
        ],
    })


def test_model_sorts_each_dated_section_and_roundtrips_without_changing_facts():
    resume = _resume()
    assert [s.id for s in resume.sections] == ["jobs", "research", "education", "projects", "skills"]
    assert [e.id for e in resume.sections[0].entries] == ["now", "tie", "old", "unknown"]
    assert [e.school for e in resume.education] == ["New School", "Old School"]
    assert [e.id for e in resume.projects] == ["newp", "oldp"]
    assert [e.label for e in resume.skills] == ["Z", "A"]
    assert resume.education[0].dates == "Expected May 2028"
    assert MasterResume.model_validate(resume.model_dump()).model_dump() == resume.model_dump()


def test_generic_and_legacy_render_context_share_chronological_order(built_template):
    context = render.build_context(_resume(), DocxTemplate(built_template), layout={"enabled": {
        "experience": True, "education": True, "projects": True, "skills": True,
    }})
    sections = {s["id"]: s["entries"] for s in context["sections"]}
    assert [e["company"] for e in sections["jobs"]] == ["now", "tie", "old", "unknown"]
    assert [e["company"] for e in context["experience"]] == ["now", "tie", "old", "unknown", "research"]
    assert [e["school"] for e in context["education"]] == ["New School", "Old School"]
    assert [e["name"] for e in context["projects"]] == ["New Project", "Old Project"]


def test_generated_document_keeps_chronological_order(built_template, tmp_path):
    out = tmp_path / "chronological.docx"
    render.render(_resume(), template=built_template, out=out)
    text = "\n".join(p.text for p in Document(out).paragraphs)
    assert text.index("now") < text.index("tie") < text.index("old")
    assert text.index("New School") < text.index("Old School")
    assert text.index("New Project") < text.index("Old Project")
