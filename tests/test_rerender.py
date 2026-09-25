"""Bullet review and re-render (`rerender.py`, `/api/jobs/{id}/bullets|rerender`).

Real docx renders through the session's `built_template`; PDF measurement is stubbed
at `render.measure_detail`, as elsewhere in the suite.
"""

from __future__ import annotations

import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config, render, rerender
from resume_tailor.data import Bullet
from resume_tailor.merge import MergeGroup
from resume_tailor.template_profile import active_layout
from resume_tailor.web.app import app
from tests.fixtures import synthetic_resume


def _resume_with_second_bullet():
    resume = synthetic_resume()
    entry = resume.entry_sections[0].entries[0]
    entry.bullets.append(Bullet(id="exp_b2", text="Cut deploy time by 40% with caching.", tags=["ci"]))
    return resume


@pytest.fixture
def measure(monkeypatch):
    """Stub measurement: writes the PDF a real conversion would, returns set numbers."""
    result = {"value": (1, 40)}
    calls: list = []

    def _measure(docx_path, keep_active=False):
        calls.append(docx_path)
        docx_path.with_suffix(".pdf").write_bytes(b"%PDF-stub")
        return result["value"]

    monkeypatch.setattr(render, "measure_detail", _measure)
    return result, calls


@pytest.fixture
def run_dir(tmp_path, built_template):
    out = tmp_path / "jobs" / "job-1"
    out.mkdir(parents=True)
    resume = _resume_with_second_bullet()
    ai = {"exp_b1": "Raised service throughput 2x.", "proj_b1": "Indexed notes with embeddings."}
    (out / "bullets.json").write_text(json.dumps(ai))
    render.render(resume, bullets=ai, template=built_template, out=out / "tailored.docx")
    (out / "tailored.pdf").write_bytes(b"%PDF-original")
    rerender.save_snapshot(
        out,
        resume,
        target_pages=1,
        include_project_links=True,
        contact_fields=None,
        layout=active_layout(),
        merges=[],
        template=built_template,
    )
    return out


def _docx_text(path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_rows_pair_each_rendered_bullet_with_its_source(run_dir):
    rows = rerender.bullet_rows(run_dir)
    assert [r["bullet_id"] for r in rows] == ["exp_b1", "proj_b1"]  # exp_b2 was not rendered
    first = rows[0]
    assert first["source_text"].startswith("Improved reliability")
    assert first["ai_text"] == first["current_text"] == "Raised service throughput 2x."
    assert first["entry_label"] == "Software Engineer · Example Corp"


def test_edit_renders_saves_and_keeps_the_ai_version(run_dir, measure):
    result = rerender.rerender(
        run_dir, edits={"proj_b1": "Indexed research notes."}, reverted=["exp_b1"],
        removed=[], confirmed=[],
    )
    assert result["status"] == "saved" and result["pages"] == 1
    text = _docx_text(run_dir / "tailored.docx")
    assert "Indexed research notes." in text and "Improved reliability" in text
    assert "Raised service throughput" not in text
    assert (run_dir / "tailored.pdf").read_bytes() == b"%PDF-stub"
    assert (run_dir / "tailored.v1.pdf").read_bytes() == b"%PDF-original"
    assert json.loads((run_dir / "bullets.v1.json").read_text())["exp_b1"].startswith("Raised")
    rows = {r["bullet_id"]: r for r in rerender.bullet_rows(run_dir)}
    assert rows["proj_b1"]["current_text"] == "Indexed research notes."
    assert rows["proj_b1"]["ai_text"] == "Indexed notes with embeddings."
    assert not list(run_dir.glob("rerender.tmp*"))

    # An empty request is "reset to AI version".
    assert rerender.rerender(run_dir, edits={}, reverted=[], removed=[], confirmed=[])["status"] == "saved"
    assert "Raised service throughput" in _docx_text(run_dir / "tailored.docx")


def test_overflow_is_never_saved(run_dir, measure):
    result, _ = measure
    result["value"] = (2, config.LINES_PER_PAGE + 3)
    before = (run_dir / "tailored.docx").read_bytes()
    out = rerender.rerender(run_dir, edits={}, reverted=["exp_b1"], removed=[], confirmed=[])
    assert out == {"status": "over", "pages": 2, "target_pages": 1, "over_by_lines": 3}
    assert (run_dir / "tailored.docx").read_bytes() == before
    assert not (run_dir / "bullets.v1.json").exists()
    assert not list(run_dir.glob("rerender.tmp*"))


def test_invented_terms_need_confirmation(run_dir, measure):
    _, calls = measure
    edit = {"exp_b1": "Migrated production services to Kubernetes on AWS."}
    out = rerender.rerender(run_dir, edits=edit, reverted=[], removed=[], confirmed=[])
    assert out["status"] == "needs_confirmation" and "exp_b1" in out["flagged"]
    assert calls == []  # nothing rendered before the student confirms
    out = rerender.rerender(run_dir, edits=edit, reverted=[], removed=[], confirmed=["exp_b1"])
    assert out["status"] == "saved" and "exp_b1" in out["flagged"]


def test_remove_and_reject_bad_requests(run_dir, measure):
    out = rerender.rerender(run_dir, edits={}, reverted=[], removed=["proj_b1"], confirmed=[])
    assert out["status"] == "saved"
    assert "proj_b1" not in json.loads((run_dir / "bullets.json").read_text())
    for kwargs, message in (
        ({"removed": ["exp_b1", "proj_b1"]}, "keep at least one"),
        ({"edits": {"nope": "x"}}, "Unknown bullet"),
        ({"edits": {"exp_b1": "   "}}, "empty"),
        ({"edits": {"exp_b1": "x" * 1001}}, "over 1000"),
    ):
        args = {"edits": {}, "reverted": [], "removed": [], "confirmed": []} | kwargs
        with pytest.raises(rerender.RerenderError, match=message):
            rerender.rerender(run_dir, **args)


def test_use_original_on_a_merged_bullet_restores_every_member(run_dir, measure, built_template):
    resume = _resume_with_second_bullet()
    rerender.save_snapshot(
        run_dir, resume, target_pages=1, include_project_links=True, contact_fields=None,
        layout=active_layout(),
        merges=[MergeGroup("exp_b1", ("exp_b1", "exp_b2"), 0.9, "same work")],
        template=built_template,
    )
    row = rerender.bullet_rows(run_dir)[0]
    assert row["merged_from"] == ["exp_b1", "exp_b2"] and " / " in row["source_text"]
    rerender.rerender(run_dir, edits={}, reverted=["exp_b1"], removed=[], confirmed=[])
    saved = json.loads((run_dir / "bullets.json").read_text())
    assert saved["exp_b1"].startswith("Improved") and saved["exp_b2"].startswith("Cut deploy")


def test_runs_without_a_snapshot_say_so(tmp_path):
    (tmp_path / "bullets.json").write_text("{}")
    with pytest.raises(rerender.NoSnapshot):
        rerender.bullet_rows(tmp_path)


def test_routes(run_dir, measure, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", run_dir.parent.parent)
    with TestClient(app) as c:
        assert c.get("/api/jobs/job-1/bullets").status_code == 404  # no run.json yet
        (run_dir / "run.json").write_text(json.dumps({"job_id": "job-1", "status": "running"}))
        assert c.get("/api/jobs/job-1/bullets").status_code == 409
        (run_dir / "run.json").write_text(json.dumps({"job_id": "job-1", "status": "succeeded"}))
        rows = c.get("/api/jobs/job-1/bullets").json()["bullets"]
        assert len(rows) == 2
        body = {"edits": {"proj_b1": "Indexed research notes."}}
        assert c.post("/api/jobs/job-1/rerender", json=body).json()["status"] == "saved"
        bad = c.post("/api/jobs/job-1/rerender", json={"edits": {"zzz": "x"}})
        assert bad.status_code == 422
        (run_dir / rerender.SNAPSHOT).unlink()
        assert c.get("/api/jobs/job-1/bullets").status_code == 409
