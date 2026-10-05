"""Experience expansion on demand: generated for a finished run, not on every run."""

from __future__ import annotations

import json

from resume_tailor import config
from resume_tailor.pipeline import expand, jd, relevance
from resume_tailor.web.schemas import JobSettings
from tests.fixtures import synthetic_resume
from tests.web.helpers import _disk_only_run


def _seed_finished_run(job_id: str = "exp01"):
    out_dir = _disk_only_run(job_id)
    resume = synthetic_resume()
    on_page = [b.id for b in resume.experience[0].bullets]
    (out_dir / "bullets.json").write_text(
        json.dumps({bid: "text" for bid in on_page}), encoding="utf-8"
    )
    (out_dir / "requirements.json").write_text(
        jd.JobRequirements(title="Stub Role", seniority="intern").model_dump_json(),
        encoding="utf-8",
    )
    (out_dir / "backends.json").write_text(
        json.dumps(config.backend_specs_snapshot()), encoding="utf-8"
    )
    return out_dir, set(on_page)


def _stub_expand(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_expand(resume, requirements, **kwargs):
        calls.append(kwargs)
        entry = resume.experience[0]
        return expand.Expansion(
            entries=[
                expand.ExpandedEntry(
                    entry_key="exp:0", title=entry.title, company=entry.company,
                    location=entry.location, start=entry.start, end=entry.end,
                    bullets=["Expanded."], char_count=9, on_resume=True,
                )
            ],
            model="stub",
            char_limit=config.EXPAND_CHAR_LIMIT,
        )

    monkeypatch.setattr(expand, "expand_experience", fake_expand)
    monkeypatch.setattr(relevance, "score_table", lambda bullets, req, **k: {})
    return calls


def test_runs_skip_expansion_by_default():
    assert JobSettings().no_expand is True


def test_generate_expansion_writes_the_run_files_from_saved_inputs(client, monkeypatch):
    c, _ = client
    out_dir, on_page = _seed_finished_run()
    calls = _stub_expand(monkeypatch)

    res = c.post("/api/jobs/exp01/expansion")

    assert res.status_code == 200, res.text
    assert res.json()["entries"][0]["bullets"] == ["Expanded."]
    assert calls[0]["resume_bullet_ids"] == on_page
    record = json.loads((out_dir / "expansion.json").read_text(encoding="utf-8"))
    assert record["source_experience_count"] == len(synthetic_resume().experience)
    assert (out_dir / "expansion.md").read_text(encoding="utf-8")
    status = c.get("/api/jobs/exp01").json()
    assert status["expansion"]["entries"][0]["company"] == record["entries"][0]["company"]


def test_generate_expansion_404s_for_unknown_or_incomplete_runs(client, monkeypatch):
    c, _ = client
    _stub_expand(monkeypatch)
    assert c.post("/api/jobs/nope/expansion").status_code == 404

    out_dir, _ = _seed_finished_run("exp02")
    (out_dir / "bullets.json").unlink()
    res = c.post("/api/jobs/exp02/expansion")
    assert res.status_code == 404 and "bullets" in res.json()["detail"]


def test_apply_prepare_heals_a_run_missing_only_its_expansion(monkeypatch):
    from resume_tailor.apply.funnel import daily, preparation
    from resume_tailor.web import job_followups

    generated: list[str] = []
    checks = iter([
        preparation.PreparationEligibility(eligible=True, reasons=[]),
    ])
    monkeypatch.setattr(job_followups, "generate_expansion", generated.append)
    monkeypatch.setattr(preparation, "check", lambda app, **k: next(checks))
    app = type("App", (), {"job_id": "run7"})()

    healed = daily._heal_missing_expansion(app, JobSettings().apply)

    assert generated == ["run7"]
    assert healed.eligible


def test_apply_prepare_heal_failure_falls_back_to_a_full_prepare(monkeypatch):
    from resume_tailor.apply.funnel import daily, preparation
    from resume_tailor.web import job_followups

    def boom(job_id):
        raise FileNotFoundError("no bullets")

    still_missing = preparation.PreparationEligibility(
        eligible=False, reasons=["missing_expansion"]
    )
    monkeypatch.setattr(job_followups, "generate_expansion", boom)
    monkeypatch.setattr(preparation, "check", lambda app, **k: still_missing)
    app = type("App", (), {"job_id": "run8"})()

    assert daily._heal_missing_expansion(app, JobSettings().apply) is still_missing
