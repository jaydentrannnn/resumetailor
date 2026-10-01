"""Structured education months (`edu_dates`, plan P3-E)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from resume_tailor import config
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.funnel.packet import _build_education, build_fields
from resume_tailor.content import edu_dates
from resume_tailor.content.data import Education, MasterResume
from tests.fixtures import synthetic_resume


@pytest.mark.parametrize(
    ("dates", "expected"),
    [
        ("Sep 2022 – Jun 2026", ("2022-09", "2026-06")),
        ("September 2022 - June 2026", ("2022-09", "2026-06")),
        ("Aug. 2021 — May 2025", ("2021-08", "2025-05")),
        ("09/2022 - 05/2026", ("2022-09", "2026-05")),
        ("2022-09 to 2026-06", ("2022-09", "2026-06")),
        ("Expected June 2027", ("", "2027-06")),
        ("Expected: May 2027", ("", "2027-05")),
        ("Anticipated Graduation May 2027", ("", "2027-05")),
        ("Sep 2023 - Expected May 2027", ("2023-09", "2027-05")),
        ("May 2027", ("", "2027-05")),
        ("May '27", ("", "2027-05")),
        ("Fall 2022 – Spring 2026", ("2022-09", "2026-05")),
        # A bare year or "Present" is not a month, so none is invented.
        ("2023 – Present", ("", "")),
        ("2019 - 2023", ("", "")),
        ("Class of 2027", ("", "")),
        ("", ("", "")),
        ("Smarch 2024", ("", "")),
        ("13/2024", ("", "")),
    ],
)
def test_months(dates, expected):
    assert edu_dates.months(dates) == expected


def test_fill_keeps_what_the_student_set():
    edu = Education(school="S", degree="D", dates="Sep 2022 - Jun 2026", end="2026-08")
    edu_dates.fill(edu)
    assert (edu.start, edu.end) == ("2022-09", "2026-08")


def test_start_and_end_must_be_months():
    with pytest.raises(ValidationError, match="YYYY-MM"):
        Education(school="S", degree="D", dates="", end="June 2027")
    assert Education(school="S", degree="D", dates="", end=" 2027-06 ").end == "2027-06"


def test_saving_the_resume_fills_empty_months(tmp_path, monkeypatch):
    from resume_tailor.web.routes import resume as resume_routes

    monkeypatch.setattr(config, "MASTER_RESUME_PATH", tmp_path / "master_resume.json")
    monkeypatch.setattr(resume_routes, "_record_version", lambda *a, **k: None)
    resume = synthetic_resume()
    resume.education[0].dates = "Sep 2023 - Expected Jun 2027"
    resume_routes._write_master_resume(resume)
    saved = json.loads(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"))
    entry = next(s for s in saved["sections"] if s["kind"] == "education")["entries"][0]
    assert (entry["start"], entry["end"]) == ("2023-09", "2027-06")
    assert entry["dates"] == "Sep 2023 - Expected Jun 2027"


def _two_schools(first_end: str, second_end: str) -> MasterResume:
    raw = synthetic_resume().model_dump()
    section = next(s for s in raw["sections"] if s["kind"] == "education")
    base = section["entries"][0]
    section["entries"] = [
        {**base, "school": "Community College", "dates": "", "start": "2021-09", "end": first_end},
        {**base, "school": "State University", "dates": "", "start": "2023-09", "end": second_end},
    ]
    return MasterResume.model_validate(raw)


def test_packet_answers_single_questions_from_the_school_graduating_last():
    # A transfer student lists the old school first; forms mean the current one.
    fields = build_fields(ApplicantProfile(), _two_schools("2023-06", "2026-06"))
    assert (fields["school"], fields["graduation_month"]) == ("State University", "2026-06")
    fields = build_fields(ApplicantProfile(), _two_schools("2027-06", "2026-06"))
    assert fields["school"] == "Community College"


def test_packet_prefers_the_structured_months_over_the_printed_dates():
    resume = synthetic_resume()
    edu = resume.education[0]
    edu.dates = "Expected Spring 2027"
    assert [(r.start, r.end) for r in _build_education(resume)] == [("", "2027-05")]
    edu.end = "2027-06"
    assert [(r.start, r.end) for r in _build_education(resume)] == [("", "2027-06")]
