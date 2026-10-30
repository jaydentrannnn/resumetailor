"""Prepare writes the experience expansion only for sites whose fill pastes it."""

import json

import pytest

from resume_tailor import config
from resume_tailor.apply.funnel import daily_rows, preparation, store, store_models
from resume_tailor.pipeline import resume_quality
from resume_tailor.web.schemas import JobSettings


@pytest.fixture
def finished_run(tmp_path, monkeypatch):
    """A succeeded run with a verified resume and no expansion."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    out = config.OUTPUT_DIR / "jobs" / "run1"
    out.mkdir(parents=True)
    (out / "tailored.docx").write_bytes(b"resume")
    (out / "run.json").write_text(json.dumps({"status": "succeeded"}), "utf-8")
    resume_quality.save(out, resume_quality.ResumeQuality(fill_ratio=0.94, fill_target=0.93))
    return out


def _row(ats: str) -> store_models.Application:
    return store.upsert(
        store_models.Application(
            source="test", source_job_id=ats, company="Acme", role="Engineer",
            status="ready", job_id="run1", ats=ats,
        )
    )


def test_only_expansion_sites_wait_for_the_expansion(finished_run):
    assert preparation.check(_row("greenhouse")).eligible
    assert preparation.check(_row("workday")).reasons == ["missing_expansion"]
    assert preparation.check(_row("smartrecruiters")).reasons == ["missing_expansion"]
    (finished_run / "expansion.json").write_text(
        json.dumps({"entries": [], "source_experience_count": 0}), "utf-8"
    )
    assert preparation.check(_row("workday")).eligible


@pytest.mark.parametrize(
    ("ats", "no_expand"),
    [("workday", False), ("SmartRecruiters", False), ("greenhouse", True), ("", True), (None, False)],
)
def test_prepare_skips_the_expand_stage_where_no_fill_uses_it(ats, no_expand):
    defaults = JobSettings()
    settings = daily_rows._job_settings(defaults, defaults.apply, ats=ats)  # noqa: SLF001
    assert settings.no_expand is no_expand


def test_a_short_linked_row_takes_its_site_from_its_requisition_key(finished_run):
    # AbbVie / Intuitive Mfg (2026-10-30): found through zapply, stored "unknown".
    row = store.upsert(
        store_models.Application(
            source="test", source_job_id="zapply-1", company="AbbVie", role="Intern",
            status="ready", job_id="run1", ats="unknown",
            canonical_key="smartrecruiters:abbvie:744000",
        )
    )
    assert preparation.expansion_ats(row) == "smartrecruiters"
    assert preparation.check(row).reasons == ["missing_expansion"]
    other = row.model_copy(update={"canonical_key": "other:unknown:x"})
    assert preparation.expansion_ats(other) == "unknown"
    assert preparation.check(other).eligible
    stored = row.model_copy(update={"ats": "greenhouse"})
    assert preparation.expansion_ats(stored) == "greenhouse"
