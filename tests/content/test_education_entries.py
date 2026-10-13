"""Structured degree rows preserve legacy readers, manual wording, and exact dates."""

import json

import pytest
from pydantic import ValidationError

from resume_tailor.content import degree_line
from resume_tailor.content.data import (
    Contact,
    Education,
    EducationSection,
    MajorEntry,
    MasterResume,
)


def _edu(**values):
    return Education.model_validate(
        {
            "school": "Synthetic University",
            "degree": "B.S. Computing",
            "dates": "Expected June 2027",
            **values,
        }
    )


def test_legacy_multiple_majors_seed_entries_without_losing_other_fields():
    edu = _edu(
        degree_type="B.S.",
        majors=["Computer Science", "Data Science"],
        minors=["Management"],
        location="Example City",
        coursework=["Algorithms"],
        details=["Honors program"],
        gpa="3.8",
        degree_format="pipe",
        start="2023-09",
        end="2027-06",
    )
    assert [(row.name, row.degree_type) for row in edu.major_entries] == [
        ("Computer Science", "B.S."),
        ("Data Science", "B.S."),
    ]
    payload = edu.model_dump()
    assert payload["majors"] == ["Computer Science", "Data Science"]
    assert payload["degree_type"] == "B.S."
    assert payload["minors"] == ["Management"]
    assert payload["coursework"] == ["Algorithms"] and payload["details"] == ["Honors program"]
    assert payload["location"] == "Example City" and payload["gpa"] == "3.8"
    assert edu.degree == "B.S. Computing" and edu.degree_mode == "manual"


def test_legacy_single_major_migrates_and_does_not_override_existing_majors():
    single = _edu(major="Computing", degree_type="Bachelor of Science")
    assert single.major_entries == [MajorEntry(name="Computing", degree_type="Bachelor of Science")]
    multiple = _edu(major="Old", majors=["New"], degree_type="B.A.")
    assert multiple.major == "New"
    assert "major" not in multiple.model_dump()


@pytest.mark.parametrize("alias", ["BS", "B.S.", "Bachelor of Science"])
def test_equivalent_science_credentials_share_one_printed_degree(alias):
    edu = _edu(
        major_entries=[
            {"name": "Computer Science", "degree_type": "B.S."},
            {"name": "Data Science", "degree_type": alias},
        ],
        minors=["Management"],
    )
    assert degree_line.compose(
        edu.degree_type, edu.majors, edu.minors, major_entries=edu.major_entries
    ) == ("B.S. in Computer Science and Data Science; Minor in Management")


def test_arts_and_science_remain_distinct_credentials_in_order():
    edu = _edu(
        major_entries=[
            {"name": "Computer Science", "degree_type": "B.S."},
            {"name": "Economics", "degree_type": "Bachelor of Arts"},
            {"name": "Data Science", "degree_type": "BS"},
        ]
    )
    assert degree_line.compose(
        edu.degree_type, edu.majors, [], major_entries=edu.major_entries
    ) == ("B.S. in Computer Science and Data Science; Bachelor of Arts in Economics")


def test_nested_major_edit_and_reorder_refresh_legacy_serialized_projections():
    edu = _edu(
        major_entries=[
            {"name": "Computing", "degree_type": "B.S."},
            {"name": "Economics", "degree_type": "B.A."},
        ]
    )
    edu.major_entries[0].name = "Data Science"
    edu.major_entries.reverse()
    assert edu.major == "Economics" and edu.majors == ["Economics", "Data Science"]
    assert edu.degree_type == "B.A."
    payload = json.loads(edu.model_dump_json())
    assert payload["degree_type"] == "B.A." and payload["majors"] == ["Economics", "Data Science"]
    assert payload["major_entries"][1] == {"name": "Data Science", "degree_type": "B.S."}
    restored = Education.model_validate(payload)
    assert restored.major_entries == edu.major_entries


def test_legacy_property_assignments_remain_meaningful():
    edu = _edu(degree_type="B.S.", majors=["Computing", "Mathematics"])
    edu.major = "Data Science"
    assert edu.majors == ["Data Science", "Mathematics"]
    edu.majors = ["Physics", "Mathematics"]
    assert [row.name for row in edu.major_entries] == ["Physics", "Mathematics"]
    edu.degree_type = "B.A."
    assert all(row.degree_type == "B.A." for row in edu.major_entries)
    assert Education.model_validate(edu.model_dump()).major == "Physics"


def test_structured_entries_override_stale_legacy_projections():
    edu = _edu(
        degree_type="B.A.", majors=["Old"], major_entries=[{"name": "New", "degree_type": "B.S."}]
    )
    assert edu.degree_type == "B.S." and edu.majors == ["New"]


@pytest.mark.parametrize("fmt", ["semicolon", "comma", "pipe"])
def test_manual_text_is_preserved_through_save_with_structured_edits(tmp_path, monkeypatch, fmt):
    from resume_tailor.web.routes import resume as routes

    manual_text = "My exact degree wording / Honors — preserve punctuation"
    edu = _edu(
        degree=manual_text,
        degree_mode="manual",
        degree_format=fmt,
        major_entries=[{"name": "Computing", "degree_type": "B.S."}],
    )
    master = MasterResume(
        contact=Contact(name="Test Applicant", email="test@example.test"),
        sections=[EducationSection(id="education", title="Education", entries=[edu])],
    )
    path = tmp_path / "master.json"
    monkeypatch.setattr(routes.config, "MASTER_RESUME_PATH", path)
    monkeypatch.setattr(routes, "_record_version", lambda *args: None)
    monkeypatch.setattr(routes.skill_refresh, "schedule", lambda *args: None)
    edu.major_entries[0].name = "Data Science"
    routes._write_master_resume(master)
    saved = MasterResume.model_validate_json(path.read_text(encoding="utf-8")).education[0]
    assert saved.degree == manual_text and saved.degree_format == fmt
    assert saved.major == "Data Science" and saved.end == "2027-06"


@pytest.mark.parametrize("value", ["", "2024-02", "2024-02-29", "2027-06-09"])
def test_optional_day_accepts_valid_calendar_dates(value):
    edu = _edu(start=value, end=value)
    assert edu.start == edu.end == value
    assert Education.model_validate_json(edu.model_dump_json()).start == value


@pytest.mark.parametrize(
    "value",
    [
        "2023-02-29",
        "2024-02-30",
        "2024-13",
        "2024-00",
        "2024-05-32",
        "2024",
        "2024-2",
        "2024-02-1",
        "Present",
        "January 2024",
    ],
)
def test_invalid_or_incomplete_education_date_is_rejected(value):
    with pytest.raises(ValidationError, match="valid YYYY-MM or YYYY-MM-DD"):
        _edu(start=value)
