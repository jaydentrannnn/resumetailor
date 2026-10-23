"""Role family and level from a job title (`research/pay_level.py`)."""

from __future__ import annotations

import pytest

from resume_tailor.research import pay_level


@pytest.mark.parametrize(
    ("title", "family", "level"),
    [
        ("Software Engineer Intern - Summer 2027 (Atlanta, GA)", "software", "intern"),
        ("Data Analyst Co-op", "data", "intern"),
        ("R&D Intern - AI Research Engineer", "research", "intern"),
        ("AI Post-Training and Model Alignment Intern", "data", "intern"),
        ("AI Software Intern", "software", "intern"),
        ("Associate Software Development Engineer 1", "software", "new_grad"),
        ("Early Careers Analyst - Data Office", "data", "new_grad"),
        ("Software Engineer II", "software", "mid"),
        ("Senior Data Scientist", "data", "senior"),
        ("Principal Firmware Engineer", "hardware", "staff"),
        ("Engineering Manager", "engineering", "manager"),
        ("Product Manager Intern", "product", "intern"),
        ("Product Manager", "product", "mid"),
        ("Cybersecurity Undergraduate Intern", "security", "intern"),
        ("Motorsports Intern", "other", "intern"),
    ],
)
def test_family_and_level(title, family, level):
    assert (pay_level.family(title), pay_level.level(title)) == (family, level)
