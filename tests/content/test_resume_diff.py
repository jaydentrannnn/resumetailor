"""`resume_diff.changes`: deterministic "what changed" lines for resume history."""

from __future__ import annotations

import copy
import json

import pytest

from resume_tailor.content import resume_diff

BASE = {
    "contact": {"name": "Ada", "email": "a@x.com", "phone": ""},
    "sections": [
        {"id": "exp", "kind": "experience", "title": "Experience", "entries": [
            {"id": "acme", "company": "Acme", "title": "Engineer", "start": "2022", "end": "2023",
             "bullets": [{"id": "b1", "text": "Built X"}, {"id": "b2", "text": "Shipped Y"}]},
            {"id": "init", "company": "Initech", "title": "Intern", "start": "2021", "end": "2021",
             "bullets": []},
        ]},
        {"id": "edu", "kind": "education", "title": "Education", "entries": [
            {"school": "UCI", "degree": "BS", "dates": "2024", "gpa": "3.5"},
        ]},
    ],
}


def _diff(mutate) -> list[str]:
    new = copy.deepcopy(BASE)
    mutate(new)
    return resume_diff.changes(json.dumps(BASE), json.dumps(new))


def _exp(doc):
    return doc["sections"][0]["entries"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: None, []),
        (lambda d: d["contact"].update(email="b@x.com", phone="555"),
         ["Changed email and phone in contact details"]),
        (lambda d: _exp(d)[0]["bullets"].append({"id": "b3", "text": "New"}),
         ["Acme (Experience): added a bullet"]),
        (lambda d: _exp(d)[0]["bullets"][0].update(text="Built Z") or
         _exp(d)[0]["bullets"][1].update(text="Shipped W"),
         ["Acme (Experience): edited 2 bullets"]),
        (lambda d: _exp(d)[0].update(end="2024"), ["Acme (Experience): changed dates"]),
        (lambda d: d["sections"][1]["entries"][0].update(gpa="3.9"),
         ["UCI (Education): changed GPA"]),
        (lambda d: _exp(d).pop(1), ["Removed 'Initech' from Experience"]),
        (lambda d: _exp(d).append({"id": "new", "company": "Globex", "bullets": []}),
         ["Added 'Globex' to Experience"]),
        (lambda d: _exp(d).reverse(), ["Reordered Experience"]),
        (lambda d: d["sections"].reverse(), ["Reordered sections"]),
        (lambda d: d["sections"][1].update(title="Schooling"),
         ["Renamed section 'Education' to 'Schooling'"]),
        (lambda d: d["sections"].append({"id": "p", "title": "Projects", "entries": []}),
         ["Added section 'Projects'"]),
    ],
)
def test_changes(mutate, expected):
    assert _diff(mutate) == expected


def test_unreadable_text_is_reported_not_raised():
    assert resume_diff.changes("{bad", json.dumps(BASE)) == [
        "Edited outside the app (not readable as a resume)"
    ]


def test_the_same_edit_on_many_entries_is_one_line():
    def mutate(doc):
        for entry in _exp(doc):
            entry["end"] = "2030"
        doc["sections"][1]["entries"][0]["dates"] = "2030"
    assert _diff(mutate) == ["Changed dates in 3 entries"]
