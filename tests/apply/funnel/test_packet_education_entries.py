"""Structured education credentials stay truthful through packet/form projections."""

from resume_tailor.apply.funnel import packet_fields
from resume_tailor.apply.funnel.packet_models import PacketEducation
from resume_tailor.apply.answers.profile import ApplicantProfile
from tests.fixtures import synthetic_resume


def test_legacy_month_override_does_not_erase_education_day():
    resume = synthetic_resume()
    resume.education[0].start, resume.education[0].end = "2023-09-18", "2027-06-14"
    fields = packet_fields.build_fields(ApplicantProfile(graduation_date="2027-06"), resume)
    assert fields["graduation_date"] == "2027-06-14"
    assert fields["graduation_month"] == "2027-06"


def test_packet_preserves_distinct_major_credentials_and_day_dates():
    resume = synthetic_resume()
    edu = resume.education[0]
    edu.major_entries = [
        {"name": "Computer Science", "degree_type": "B.S."},
        {"name": "Economics", "degree_type": "B.A."},
    ]
    edu.start, edu.end = "2023-09-18", "2027-06-14"
    [packet_row] = packet_fields._build_education(resume)
    saved = PacketEducation.model_validate_json(packet_row.model_dump_json())
    rows = packet_fields.education_rows([saved])
    assert [(row.major, row.degree_level, row.degree_name) for row in rows] == [
        ("Computer Science", "Bachelor of Science", "B.S."),
        ("Economics", "Bachelor of Arts", "B.A."),
    ]
    assert all((row.start, row.end) == ("2023-09-18", "2027-06-14") for row in rows)
    assert packet_fields.degree_name([saved], "Bachelors") == ""
    assert len({row.entry_key for row in rows}) == 2
    assert saved.majors == ["Computer Science", "Economics"]
    assert saved.major_entries[1].degree_type == "B.A."


def test_packet_shared_degree_aliases_name_one_credential():
    row = PacketEducation(
        school="University",
        major_entries=[
            {"name": "Computer Science", "degree_type": "B.S."},
            {"name": "Data Science", "degree_type": "Bachelor of Science"},
        ],
    )
    assert packet_fields.degree_name([row], "Bachelors") == "Bachelor of Science"
    assert [item.degree_level for item in packet_fields.education_rows([row])] == [
        "Bachelor of Science",
        "Bachelor of Science",
    ]


def test_missing_major_credential_never_borrows_a_siblings_type():
    row = PacketEducation(
        school="University",
        degree="B.S. in Computer Science",
        major_entries=[
            {"name": "Computer Science", "degree_type": "B.S."},
            {"name": "Economics", "degree_type": ""},
        ],
    )
    science, unknown = packet_fields.education_rows([row])
    assert science.degree_level == "Bachelor of Science"
    assert unknown.major == "Economics"
    assert (unknown.degree, unknown.degree_name, unknown.degree_level) == ("", "", "")
    assert packet_fields.degree_name([row], "Bachelors") == ""


def test_legacy_packet_double_major_retains_recorded_credential():
    legacy = PacketEducation(
        school="University",
        degree="B.A. in Economics and Mathematics",
        major="Economics",
        majors=["Economics", "Mathematics"],
        degree_level="Bachelor of Arts",
        end="2027-06",
    )
    rows = packet_fields.education_rows([legacy])
    assert [row.major for row in rows] == ["Economics", "Mathematics"]
    assert all(row.degree_level == "Bachelor of Arts" for row in rows)
    assert legacy.majors == ["Economics", "Mathematics"]


def test_primary_education_compares_supplied_days_and_whole_month_bounds():
    early = PacketEducation(school="Early", end="2027-06-14")
    later = PacketEducation(school="Later", end="2027-06-28")
    full_month = PacketEducation(school="Month", end="2027-06")
    assert packet_fields.current_education([early, later]) is later
    assert packet_fields.current_education([early, full_month, later]) is full_month
