"""Tests for application packet assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor import config
from resume_tailor.apply.packet import build_fields, build_packet, write_packet
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
    assert packet.experience[0].description == "Built Python services."
    assert packet.field_hints["#email"] == "email"
    assert packet.gaps[0]["canonical"] == "python"


def test_write_packet_persists_json(job_dir):
    """``write_packet`` writes ``packet.json`` beside the run artifacts."""
    packet = write_packet("test-job")
    path = job_dir / "packet.json"
    assert path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["job_id"] == packet.job_id
    assert saved["fields"]["email"] == "jordan@example.com"
