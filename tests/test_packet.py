"""Tests for application packet assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor import config
from resume_tailor.apply.packet import (
    DEFAULTS, PacketEducation, _build_education, authorization_mismatch, build_fields,
    build_packet, degree_name, job_country, missing_profile, profile_gaps, write_packet,
)
from resume_tailor.apply.profile import ApplicantProfile, EEOAnswers, LanguageEntry
from tests.fixtures import synthetic_resume


@pytest.fixture
def job_dir(tmp_path, monkeypatch):
    """Isolated job output directory with a minimal successful run."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", tmp_path / "master_resume.json")

    resume = synthetic_resume()
    config.MASTER_RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MASTER_RESUME_PATH.write_text(
        resume.model_dump_json(indent=2),
        encoding="utf-8",
    )

    profile_path = tmp_path / "applicant_profile.json"
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", profile_path)
    profile_path.write_text(
        ApplicantProfile(
            first_name="Jordan",
            last_name="Rivera",
            email="jordan@example.com",
            requires_sponsorship_now=False,
            requires_sponsorship_future=None,
            willing_to_relocate=True,
            work_authorization="citizen",
            eeo=EEOAnswers(gender="decline", race="decline", veteran="No", disability="No"),
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    job_id = "test-job"
    out = config.OUTPUT_DIR / "jobs" / job_id
    out.mkdir(parents=True)

    (out / "run.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "status": "succeeded",
                "metadata": {
                    "posting_url": "https://boards.greenhouse.io/example/jobs/1",
                    "company": "Example Corp",
                    "role": "Software Engineer Intern",
                    "ats": "greenhouse",
                },
                "report": {
                    "title": "Software Engineer Intern",
                    "gaps": [{"canonical": "python", "reason": "near_miss"}],
                },
            }
        ),
        encoding="utf-8",
    )
    (out / "expansion.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "entry_key": "exp:example-corp",
                        "title": "Software Engineer",
                        "company": "Example Corp",
                        "location": "Remote",
                        "start": "2023-01",
                        "end": "present",
                        "bullets": ["Built Python services."],
                        "char_count": 21,
                        "warnings": [],
                        "on_resume": True,
                    }
                ],
                "warnings": [],
                "model": "stub",
                "char_limit": 800,
            }
        ),
        encoding="utf-8",
    )
    (out / "skills.json").write_text(
        json.dumps({"skills": [{"skill": "Python"}, {"skill": "Git"}]}),
        encoding="utf-8",
    )
    (out / "tailored.pdf").write_bytes(b"%PDF-1.4 stub")
    (out / "tailored.docx").write_bytes(b"PK stub")
    return out


def test_build_fields_yes_no_and_omit_none():
    """Booleans become Yes/No; None is omitted; a declined EEO answer stays "decline"."""
    resume = synthetic_resume()
    profile = ApplicantProfile(
        first_name="Jordan",
        last_name="Rivera",
        requires_sponsorship_now=False,
        requires_sponsorship_future=None,
        willing_to_relocate=True,
        work_authorization="citizen",
        eeo=EEOAnswers(gender="decline", race="decline", veteran="No", disability="No"),
    )
    fields = build_fields(profile, resume)
    assert fields["requires_sponsorship"] == "No"
    assert fields["willing_to_relocate"] == "Yes"
    assert fields["work_authorization"] == "U.S. Citizen"
    assert fields["full_name"] == "Jordan Rivera"
    assert "requires_sponsorship_future" not in fields
    assert fields["gender"] == "decline"
    assert "race_detail" not in fields
    assert fields["veteran_status"] == "No"


def test_build_fields_carries_the_source_for_a_please_specify_follow_up():
    fields = build_fields(ApplicantProfile(how_heard="LinkedIn"), synthetic_resume())
    assert fields["how_heard"] == "LinkedIn"
    assert fields["how_heard_detail"] == "LinkedIn"
    assert "how_heard_detail" not in build_fields(ApplicantProfile(how_heard=""), synthetic_resume())


def test_build_fields_falls_back_to_contact():
    """Empty profile identity fields fall back to ``MasterResume.contact``."""
    resume = synthetic_resume()
    profile = ApplicantProfile()
    fields = build_fields(profile, resume)
    assert fields["email"] == "jordan@example.com"
    assert fields["phone"] == "(555) 123-4567"
    assert fields["linkedin_url"] == "https://linkedin.com/in/jordanrivera"
    assert fields["full_name"] == "Jordan Rivera"


def test_phone_device_type_defaults_to_mobile_only_when_blank():
    assert build_fields(ApplicantProfile(), synthetic_resume())["phone_device_type"] == "Mobile"
    assert build_fields(ApplicantProfile(phone_device_type="Home"), synthetic_resume())["phone_device_type"] == "Home"


def test_profile_gaps_skip_resume_fallbacks_and_defaults_but_list_a_blank_legal_fact():
    gaps = profile_gaps(build_fields(ApplicantProfile(), synthetic_resume()))
    assert "authorized_to_work" in gaps
    # Email and phone come from the resume contact; phone device type from DEFAULTS.
    assert not {"email", "phone", "phone_device_type"} & set(gaps)
    # Legal and self-identification answers never get a default.
    assert not {"authorized_to_work", "veteran_status", "disability_status"} & set(DEFAULTS)
    answered = build_fields(ApplicantProfile(authorized_to_work=True), synthetic_resume())
    assert "authorized_to_work" not in profile_gaps(answered)


def test_over_18_comes_from_the_profile_and_is_a_gap_when_blank():
    assert build_fields(ApplicantProfile(over_18=True), synthetic_resume())["over_18"] == "Yes"
    assert build_fields(ApplicantProfile(over_18=False), synthetic_resume())["over_18"] == "No"
    blank = build_fields(ApplicantProfile(), synthetic_resume())
    assert "over_18" not in blank
    assert "over_18" in profile_gaps(blank)


@pytest.mark.parametrize(
    ("location", "country"),
    [
        ("Plymouth, Minnesota, United States", "United States"),
        ("Remote - US", "United States"),
        ("USA - CA - San Jose", "United States"),
        ("San Jose, CA", "United States"),
        ("Toronto, ON, Canada", "Canada"),
        ("London, United Kingdom", "United Kingdom"),
        ("Remote", None),
        ("", None),
        ("Austin, TX or Toronto, Canada", None),  # two countries: unsure
        ("Tell us about yourself", None),  # "us" only counts as a whole part
    ],
)
def test_job_country_reads_only_a_clearly_named_country(location, country):
    assert job_country(location) == country


def test_authorization_mismatch_only_for_a_posting_clearly_elsewhere():
    profile = ApplicantProfile(country="United States", authorized_to_work=True)
    assert authorization_mismatch(profile, "Toronto, ON, Canada") == ("Canada", "United States")
    assert authorization_mismatch(profile, "Plymouth, Minnesota, United States") is None
    assert authorization_mismatch(profile, "Remote") is None
    # The authorization country, when set, wins over the home country.
    abroad = ApplicantProfile(country="United States", authorization_country="Canada")
    assert authorization_mismatch(abroad, "Toronto, ON, Canada") is None


def test_missing_profile_groups_questions_by_fact_and_marks_the_ones_answered_anyway():
    blank = [
        {"key": "authorized_to_work", "label": "Are you legally authorized to work in the US?"},
        {"key": "authorized_to_work", "label": "Are you legally authorized to work in the US?"},
        {"key": "phone_device_type", "label": "Phone Device Type"},
        {"key": "has_preferred_name", "label": "I have a preferred name"},
        {"key": "", "label": "Favourite colour"},
    ]
    entries = missing_profile(blank, filled_labels={"Phone Device Type"})
    by_key = {entry["key"]: entry for entry in entries}
    assert set(by_key) == {"authorized_to_work", "phone_device_type"}
    work = by_key["authorized_to_work"]
    assert work["questions"] == ["Are you legally authorized to work in the US?"]
    assert work["field_label"] == "Authorized to work"
    assert work["path"] == "/profile/application"
    assert work["answered"] is False
    assert by_key["phone_device_type"]["answered"] is True


def test_salary_is_manual_and_declared_eeo_answers_are_distinct():
    profile = ApplicantProfile(
        salary_expectation="$45/hour",
        eeo=EEOAnswers(race="Asian", race_detail="Southeast Asian", hispanic_latino=False),
    )
    fields = build_fields(profile, synthetic_resume())
    assert "salary_expectation" not in fields
    assert fields["race"] == "Asian"
    assert fields["race_detail"] == "Southeast Asian"
    assert fields["hispanic_latino"] == "No"



def test_languages_reach_the_packet_and_a_free_text_answer(job_dir):
    profile = ApplicantProfile(languages=[
        LanguageEntry(language="English", fluent=True, levels={"Overall": "Native"}),
        LanguageEntry(language="Vietnamese", levels={"Reading": "Intermediate", "Writing": ""}),
        LanguageEntry(language="  "),
    ])
    packet = build_packet("test-job", applicant_profile=profile)
    assert [(row.language, row.fluent, row.levels) for row in packet.languages] == [
        ("English", True, {"Overall": "Native"}), ("Vietnamese", False, {"Reading": "Intermediate"}),
    ]
    assert packet.fields["languages"] == "English (Native), Vietnamese"
    assert "languages" not in build_fields(ApplicantProfile(), synthetic_resume())

def test_education_comes_only_from_the_resume_so_a_school_is_never_listed_twice():
    """One packet row per resume entry: no profile row to duplicate it (the Workday bug
    was a profile "University of California - Irvine" beside the resume's comma form)."""
    resume = synthetic_resume()
    edu = resume.education[0]
    edu.school = "University of California, Irvine"
    edu.degree = "Bachelor of Science in Computer Science & Minor in Business Management"
    edu.dates = "Sep 2023 - Jun 2027"
    edu.major = "Computer Science"
    rows = _build_education(resume)
    assert [(row.school, row.major, row.degree_level, row.start, row.end) for row in rows] == [
        ("University of California, Irvine", "Computer Science", "Bachelor of Science", "2023-09", "2027-06"),
    ]
    fields = build_fields(ApplicantProfile(), resume)
    assert (fields["school"], fields["major"], fields["degree_level"]) == (
        "University of California, Irvine", "Computer Science", "Bachelor of Science",
    )
    assert (fields["education_start_month"], fields["graduation_month"]) == ("2023-09", "2027-06")


def test_two_degrees_at_one_school_stay_two_rows():
    raw = synthetic_resume().model_dump()
    education = next(section for section in raw["sections"] if section["kind"] == "education")
    education["entries"].append({**education["entries"][0], "degree": "BA Economics", "major": "Economics"})
    from resume_tailor.data import MasterResume

    rows = _build_education(MasterResume.model_validate(raw))
    assert [(row.degree_level, row.major) for row in rows] == [("Bachelor of Science", ""), ("Bachelor of Arts", "Economics")]


def test_blank_resume_education_is_a_gap_that_links_to_the_resume_editor():
    resume = synthetic_resume()
    resume.education[0].major = ""
    assert "major" in profile_gaps(build_fields(ApplicantProfile(), resume))
    entry = missing_profile([{"key": "major", "label": "Field of study"}], filled_labels=set())[0]
    assert entry["path"] == "/profile/resume"


def test_degree_name_names_the_one_resume_degree_at_the_profile_level():
    rows = [PacketEducation(degree="Bachelors", degree_name="Bachelor of Science in Computer Science & Minor in X")]
    assert degree_name(rows, "Bachelors") == "Bachelor of Science"
    assert degree_name([PacketEducation(degree="BS Computer Science")], "Bachelors") == "Bachelor of Science"
    # A different level, two different degrees, or no name: nothing to add.
    assert degree_name(rows, "Masters") == ""
    two = [*rows, PacketEducation(degree="BA Economics")]
    assert degree_name(two, "Bachelors") == ""
    assert degree_name([PacketEducation(degree="Bachelors")], "Bachelors") == ""


def test_build_packet_adds_the_named_degree(job_dir):
    pkt = build_packet("test-job", applicant_profile=ApplicantProfile())
    assert pkt.fields["degree_level"] == "Bachelor of Science"
    assert pkt.fields["degree_name"] == "Bachelor of Science"


def test_new_eeo_profile_fields_default_for_old_records():
    profile = ApplicantProfile.model_validate({"eeo": {"race": "Asian"}})
    assert profile.eeo.race_detail == ""
    assert profile.eeo.hispanic_latino is None


def test_build_packet_tolerates_missing_cover(job_dir):
    """Missing cover artifacts do not fail packet assembly."""
    packet = build_packet("test-job")
    assert packet.company == "Example Corp"
    assert packet.ats == "greenhouse"
    assert packet.cover_letter == ""
    assert "resume_pdf" in packet.artifacts
    assert "cover_pdf" not in packet.artifacts
    assert packet.skills == ["Python", "Git"]
    assert len(packet.experience) == 1
    assert packet.experience[0].description == "• Built Python services."
    assert packet.experience[0].entry_key == "exp:example-corp"
    assert packet.preparation.expansion_status == "present"
    assert packet.preparation.artifacts
    assert packet.field_hints["#email"] == "email"


def test_build_packet_uses_captured_contact_facts(job_dir):
    snapshot = ApplicantProfile(first_name="Captured", last_name="Applicant", email="captured@example.com")
    packet = build_packet("test-job", applicant_profile=snapshot)
    assert packet.fields["first_name"] == "Captured"
    assert packet.fields["email"] == "captured@example.com"
    assert packet.gaps[0]["canonical"] == "python"


def test_write_packet_persists_json(job_dir):
    """``write_packet`` writes ``packet.json`` beside the run artifacts."""
    packet = write_packet("test-job")
    path = job_dir / "packet.json"
    assert path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["job_id"] == packet.job_id
    assert saved["fields"]["email"] == "jordan@example.com"


def _legacy_profile(job_dir, **education):
    """A profile file saved before education moved to the resume."""
    config.APPLICANT_PROFILE_PATH.write_text(json.dumps({"first_name": "Jordan", **education}), encoding="utf-8")


def test_legacy_profile_education_moves_into_the_matching_resume_entry_once(job_dir):
    from resume_tailor.apply.profile import load_profile
    from resume_tailor.data import load

    _legacy_profile(job_dir, school="State University", major="Computer Science", gpa="4.0",
                    degree_level="Bachelors", graduation_month="2023")
    profile, _seeded = load_profile()
    assert profile.first_name == "Jordan"
    edu = load().education[0]
    # Blanks are filled; the resume's own GPA is kept.
    assert (edu.major, edu.gpa) == ("Computer Science", "3.8")
    saved = json.loads(config.APPLICANT_PROFILE_PATH.read_text(encoding="utf-8"))
    assert not {"school", "major", "gpa", "degree_level", "graduation_month"} & set(saved)
    folder = config.APPLICANT_PROFILE_PATH.parent
    assert list(folder.glob("master_resume.*.bak.json")) and list(folder.glob("applicant_profile.*.bak.json"))
    # Once migrated, a later load touches nothing.
    before = config.MASTER_RESUME_PATH.read_text(encoding="utf-8")
    load_profile()
    assert config.MASTER_RESUME_PATH.read_text(encoding="utf-8") == before


def test_legacy_profile_education_for_another_school_leaves_the_resume_alone(job_dir):
    from resume_tailor.apply.profile import load_profile

    before = config.MASTER_RESUME_PATH.read_text(encoding="utf-8")
    _legacy_profile(job_dir, school="Elsewhere College", major="History")
    load_profile()
    assert config.MASTER_RESUME_PATH.read_text(encoding="utf-8") == before
    assert "major" not in json.loads(config.APPLICANT_PROFILE_PATH.read_text(encoding="utf-8"))
