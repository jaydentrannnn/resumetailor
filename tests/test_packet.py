"""Tests for application packet assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor import config
from resume_tailor.apply.packet import _build_education, build_fields, build_packet, write_packet
from resume_tailor.apply.profile import ApplicantProfile, EEOAnswers
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
    """Booleans become Yes/No; None and declined EEO values are omitted."""
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
    assert "gender" not in fields
    assert fields["veteran_status"] == "No"


def test_build_fields_falls_back_to_contact():
    """Empty profile identity fields fall back to ``MasterResume.contact``."""
    resume = synthetic_resume()
    profile = ApplicantProfile()
    fields = build_fields(profile, resume)
    assert fields["email"] == "jordan@example.com"
    assert fields["phone"] == "(555) 123-4567"
    assert fields["linkedin_url"] == "https://linkedin.com/in/jordanrivera"
    assert fields["full_name"] == "Jordan Rivera"


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


def test_uc_irvine_school_alias_deduplicates_only_that_school():
    resume = synthetic_resume()
    resume.education[0].school = "University of California, Irvine"
    profile = ApplicantProfile(school="University of California - Irvine", degree_level="Bachelors")
    rows = _build_education(profile, resume)
    assert len(rows) == 1
    assert rows[0].degree == "Bachelors"
    assert rows[0].degree_name == resume.education[0].degree


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


def test_profile_education_start_month_reaches_fields_and_education_row():
    profile = ApplicantProfile(school="Test University", education_start_month="2023-09", graduation_month="2027-06")
    resume = synthetic_resume()
    assert build_fields(profile, resume)["education_start_month"] == "2023-09"
    row = _build_education(profile, resume)[0]
    assert (row.start, row.end) == ("2023-09", "2027-06")


def test_missing_profile_start_date_is_inherited_from_unique_resume_row(job_dir):
    profile = ApplicantProfile(school="State University", degree_level="Bachelors", graduation_month="2023")
    pkt = build_packet("test-job", applicant_profile=profile)
    assert pkt.education[0].start == "2019"
    assert pkt.fields["education_start_month"] == "2019"


def test_explicit_profile_start_date_overrides_resume_row(job_dir):
    profile = ApplicantProfile(school="State University", degree_level="Bachelors", education_start_month="2020-09")
    pkt = build_packet("test-job", applicant_profile=profile)
    assert pkt.education[0].start == "2020-09"
    assert pkt.fields["education_start_month"] == "2020-09"


def test_ambiguous_resume_dates_do_not_fill_profile_start():
    raw = synthetic_resume().model_dump()
    education = next(section for section in raw["sections"] if section["kind"] == "education")
    duplicate = dict(education["entries"][0])
    duplicate["dates"] = "2020 - 2024"
    education["entries"].append(duplicate)
    from resume_tailor.data import MasterResume

    resume = MasterResume.model_validate(raw)
    profile = ApplicantProfile(school="State University", degree_level="Bachelors")
    rows = _build_education(profile, resume)
    assert rows[0].start == ""
