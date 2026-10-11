"""Structured degree parts: composing the printed line, detecting parts, migration."""

from __future__ import annotations

import pytest

from resume_tailor.content import degree_line
from resume_tailor.content.data import Education


@pytest.mark.parametrize(
    ("kind", "majors", "minors", "fmt", "expected"),
    [
        ("B.A.", ["Business Administration"], ["Digital Information Systems"], "semicolon",
         "B.A. in Business Administration; Minor in Digital Information Systems"),
        ("B.S.", ["Math", "Physics"], [], "semicolon", "B.S. in Math and Physics"),
        ("B.S.", ["Math", "CS", "Physics"], ["Art", "Music"], "pipe",
         "B.S. in Math, CS and Physics | Minors in Art and Music"),
        ("Bachelor of Arts", ["Economics"], ["Art"], "comma",
         "Bachelor of Arts in Economics, Minor in Art"),
        ("B.A.", [], [], "semicolon", "B.A."),
        ("", ["Economics"], [" "], "semicolon", "Economics"),
        ("", [], ["Art"], "semicolon", "Minor in Art"),
    ],
)
def test_compose(kind, majors, minors, fmt, expected):
    assert degree_line.compose(kind, majors, minors, fmt) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("B.A. in Business Administration; Minor in Digital Information Systems",
         ("B.A.", ["Business Administration"], ["Digital Information Systems"])),
        ("BS Computer Science | GPA: 3.9", ("BS", ["Computer Science"], [])),
        ("Bachelor of Science in Economics and Mathematics, Minors in Art and Music",
         ("Bachelor of Science", ["Economics", "Mathematics"], ["Art", "Music"])),
        ("Liberal Studies", ("", ["Liberal Studies"], [])),
    ],
)
def test_detect(text, expected):
    assert degree_line.detect(text) == expected


def test_compose_detect_round_trip():
    parts = ("B.S.", ["Data Science", "Statistics"], ["Spanish"])
    assert degree_line.detect(degree_line.compose(*parts)) == parts


def test_legacy_major_folds_into_majors():
    edu = Education.model_validate(
        {"school": "S", "degree": "BS CS", "dates": "2024", "major": "Computer Science"}
    )
    assert edu.majors == ["Computer Science"]
    assert edu.major == "Computer Science"
    assert edu.degree_mode == "manual" and edu.degree == "BS CS"
    assert "major" not in edu.model_dump()


def test_legacy_major_never_overrides_majors():
    edu = Education.model_validate(
        {"school": "S", "degree": "d", "dates": "", "major": "Old", "majors": ["New"]}
    )
    assert edu.majors == ["New"]
