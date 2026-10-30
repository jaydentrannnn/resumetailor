"""A fill on a form with Experience rows writes the entries Prepare did not (2026-10-30:
short-linked rows were "unknown" at Prepare, so their packets had no experience)."""

from __future__ import annotations

import json

import pytest

from resume_tailor import config
from resume_tailor.apply.forms import fill_ats_steps
from resume_tailor.apply.funnel.packet_models import Packet, PacketExperience
from resume_tailor.infra import wait_clock
from resume_tailor.web import job_followups
from tests.fixtures import synthetic_resume


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    (tmp_path / "jobs" / "job1").mkdir(parents=True)
    state = fill_ats_steps._FillAtsSteps.__new__(fill_ats_steps._FillAtsSteps)
    state.pkt = Packet(job_id="job1", built_at="now", ats="smartrecruiters")
    state.resume = synthetic_resume()
    state.waits = wait_clock.Tally()
    state.messages = []
    state.progress = state.messages.append
    return state


def test_the_expansion_is_written_and_its_entries_used(run, tmp_path, monkeypatch):
    calls: list[str] = []

    def generate(job_id: str):
        calls.append(job_id)
        (tmp_path / "jobs" / job_id / "expansion.json").write_text(json.dumps({"entries": [{
            "entry_key": "exp:e1", "title": "Data Intern", "company": "Acme Corp",
            "start": "2025-06", "end": "2025-09", "bullets": ["Built dashboards."],
        }]}), encoding="utf-8")

    monkeypatch.setattr(job_followups, "generate_expansion", generate)
    run._ensure_experience()  # noqa: SLF001
    run._ensure_experience()  # noqa: SLF001 - once per fill
    assert calls == ["job1"]
    assert [(row.title, row.description) for row in run.pkt.experience] == [
        ("Data Intern", "• Built dashboards.")
    ]
    assert run.messages == ["writing experience entries for this form"]


def test_without_an_expansion_the_resumes_entries_go_in_bare(run, monkeypatch):
    def fail(_job_id: str):
        raise FileNotFoundError("This job has no saved requirements.")

    monkeypatch.setattr(job_followups, "generate_expansion", fail)
    run._ensure_experience()  # noqa: SLF001
    titles = [entry.title for entry in run.resume.experience]
    assert [row.title for row in run.pkt.experience] == titles
    assert all(row.description == "" for row in run.pkt.experience)
    assert run.messages[-1] == "experience entries added without descriptions"


def test_a_packet_with_entries_is_left_as_it_is(run, monkeypatch):
    monkeypatch.setattr(job_followups, "generate_expansion", pytest.fail)
    entries = [PacketExperience(title="Tutor", employer="Library")]
    run.pkt = run.pkt.model_copy(update={"experience": entries})
    run._ensure_experience()  # noqa: SLF001
    assert run.pkt.experience == entries
    assert run.messages == []
