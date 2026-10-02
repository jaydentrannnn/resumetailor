"""Workspaces (profiles): list, create, activate, and per-profile state."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from resume_tailor import config
from resume_tailor.content.data import load
from resume_tailor.document import template_profile
from resume_tailor.pipeline.fit_types import FitResult
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web import template_ops
from resume_tailor.web.schemas import JobSettings

# `bootstrap` is imported directly (not via `resume_tailor.workspace.bootstrap`) because
# the autouse fixture in conftest.py stubs the module attribute to a no-op for every
# other test in this file; these tests want the real implementation.
from resume_tailor.workspace import bootstrap as real_bootstrap
from tests.web.helpers import _point_workspaces_at, _resume_docx_bytes, _write_test_resume


def test_get_workspaces_lists_registered_profiles(client, tmp_path, monkeypatch):
    """GET /api/workspaces reports the registry after a real bootstrap."""
    c, _ = client
    _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()

    res = c.get("/api/workspaces")
    assert res.status_code == 200
    body = res.json()
    assert body["active_id"] == "default"
    assert [e["id"] for e in body["entries"]] == ["default"]
    assert body["entries"][0]["is_active"] is True


def test_create_rename_and_delete_workspace(client, tmp_path, monkeypatch):
    """The CRUD routes round-trip through the registry."""
    c, _ = client
    _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()

    created = c.post("/api/workspaces", json={"label": "Data Science"})
    assert created.status_code == 200
    ids = {e["id"] for e in created.json()["entries"]}
    assert ids == {"default", "data-science"}

    renamed = c.patch("/api/workspaces/data-science", json={"label": "Machine Learning"})
    assert renamed.status_code == 200
    labels = {e["id"]: e["label"] for e in renamed.json()["entries"]}
    assert labels["data-science"] == "Machine Learning"

    dup_label = c.post("/api/workspaces", json={"label": "default"})
    assert dup_label.status_code == 400

    deleted = c.delete("/api/workspaces/data-science")
    assert deleted.status_code == 200
    assert [e["id"] for e in deleted.json()["entries"]] == ["default"]

    refuse_last = c.delete("/api/workspaces/default")
    assert refuse_last.status_code == 400


def test_activate_workspace_returns_full_reseed_payload(client, tmp_path, monkeypatch):
    """Activating swaps config/settings/template in one response and rebinds config."""
    c, _ = client
    _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()
    c.post("/api/workspaces", json={"label": "Second"})

    res = c.post("/api/workspaces/second/activate")
    assert res.status_code == 200
    body = res.json()
    assert body["active_id"] == "second"
    assert body["config"]["active_workspace_id"] == "second"
    assert body["config"]["active_workspace_label"] == "Second"
    assert body["settings"]["pages"] == 1
    assert config.active_workspace_id() == "second"

    unknown = c.post("/api/workspaces/does-not-exist/activate")
    assert unknown.status_code == 400


def test_activate_workspace_409_when_queue_busy(client, tmp_path, monkeypatch):
    """POST /api/workspaces/{id}/activate returns 409 while a job is queued or running."""
    c, q = client
    _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()
    c.post("/api/workspaces", json={"label": "Second"})

    # Insert a "running" job directly rather than through submit(), which would start
    # the background worker and race this test — there is no master resume in the
    # isolated tmp workspace for it to load, so it would fail (and un-busy the queue)
    # before this request lands.
    job = jobs_mod.Job(job_id="fake-busy", jd_text="x", settings=JobSettings(), status="running")
    q._jobs[job.job_id] = job

    res = c.post("/api/workspaces/second/activate")
    assert res.status_code == 409
    assert "progress" in res.json()["detail"].lower() or "job" in res.json()["detail"].lower()
    # Refused, so the active profile must not have changed.
    assert config.active_workspace_id() == "default"


def test_create_job_and_activate_workspace_share_one_lock(client, tmp_path, monkeypatch):
    """`create_job` and `activate_workspace` both hold `template_ops.LOCK` across their
    validate-then-submit / busy-check-then-activate sequences (see both routes'
    docstrings). Without this, a job could be validated against workspace A, then
    executed by the worker against workspace B if a switch landed in the gap between
    validation and `submit()` — and `activate_workspace`'s own `busy()` check has to
    run *inside* the same lock, not before acquiring it, or a job submitted in that
    gap would still slip through.

    Proven directly rather than by racing real timing: hold `template_ops.LOCK` from a
    background thread and confirm `POST /api/jobs` cannot complete until it's
    released, then confirm `POST /api/workspaces/{id}/activate` is blocked by it too.
    A flaky sleep-based race would only sometimes catch a regression; this doesn't
    depend on timing at all.
    """
    c, _q = client
    _write_test_resume(monkeypatch, tmp_path, bullet_text="Did a thing.", bullet_tags=["python"])
    # The route only needs to reach `submit()` and return — it doesn't matter that the
    # job goes on to fail once the background worker picks it up, only that it never
    # reaches the network doing so. Failing the very first pipeline stage, locally and
    # immediately, is simpler than replicating a full success stub chain and is just
    # as safe: nothing downstream ever runs.
    def failing_extract_consensus(*a, **k):
        raise RuntimeError("test stub — pipeline must not reach the network")

    monkeypatch.setattr(jobs_mod.jd, "extract_consensus", failing_extract_consensus)

    acquired = threading.Event()
    release = threading.Event()

    def hold_lock():
        with template_ops.LOCK:
            acquired.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    try:
        assert acquired.wait(timeout=2), "background thread never acquired the lock"

        result: dict = {}

        def try_create_job():
            result["response"] = c.post("/api/jobs", json={"jd_text": "placeholder jd"})

        caller = threading.Thread(target=try_create_job, daemon=True)
        caller.start()
        caller.join(timeout=0.5)
        assert caller.is_alive(), (
            "create_job returned without waiting for template_ops.LOCK — the two "
            "routes are no longer mutually exclusive"
        )

        release.set()
        caller.join(timeout=5)
        assert not caller.is_alive()
        assert result["response"].status_code == 200
    finally:
        release.set()
        holder.join(timeout=5)

    # Same proof, for the other side of the pairing: activate_workspace must also
    # block on the lock, not just create_job.
    acquired.clear()
    release.clear()
    holder2 = threading.Thread(target=hold_lock, daemon=True)
    holder2.start()
    try:
        assert acquired.wait(timeout=2), "background thread never acquired the lock"

        result2: dict = {}

        def try_activate():
            result2["response"] = c.post("/api/workspaces/default/activate")

        caller2 = threading.Thread(target=try_activate, daemon=True)
        caller2.start()
        caller2.join(timeout=0.5)
        assert caller2.is_alive(), (
            "activate_workspace returned without waiting for template_ops.LOCK"
        )

        release.set()
        caller2.join(timeout=5)
        assert not caller2.is_alive()
    finally:
        release.set()
        holder2.join(timeout=5)


def test_library_selection_is_per_profile_and_activate_reloads_it(client, tmp_path, monkeypatch):
    """Each profile has its own pack selection, and switching profiles must rebind
    config.TAG_ALIASES to the newly active one's — the web-layer companion to
    test_workspace.py::test_activate_reloads_the_effective_library."""
    c, _ = client
    _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()
    c.post("/api/workspaces", json={"label": "Nursing"})

    c.post("/api/workspaces/nursing/activate")
    created = c.post(
        "/api/libraries/packs",
        json={"label": "Nursing", "tag_aliases": {"bls": "basic life support"}},
    )
    nursing_pack_id = created.json()["packs"][-1]["id"]
    c.put("/api/libraries/selection", json={"enabled_packs": [nursing_pack_id]})
    assert config.TAG_ALIASES.get("bls") == "basic life support"
    assert "py" not in config.TAG_ALIASES  # core-tech is not enabled for this profile

    c.post("/api/workspaces/default/activate")

    assert config.TAG_ALIASES.get("py") == "python"
    assert "bls" not in config.TAG_ALIASES

    # Switching back must restore the nursing profile's own selection, not the default's.
    c.post("/api/workspaces/nursing/activate")
    assert c.get("/api/libraries").json()["enabled_packs"] == [nursing_pack_id]
    assert config.TAG_ALIASES.get("bls") == "basic life support"


def test_settings_round_trip_is_per_workspace(client, tmp_path, monkeypatch):
    """Each profile keeps its own settings.json; switching swaps which one is live."""
    c, _ = client
    _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()

    put_res = c.put("/api/settings", json={"settings": {"pages": 4, "model": "ollama"}})
    assert put_res.status_code == 200

    c.post("/api/workspaces", json={"label": "Second"})
    c.post("/api/workspaces/second/activate")
    fresh = c.get("/api/settings")
    assert fresh.json()["settings"]["pages"] == 1
    assert fresh.json()["seeded"] is True

    c.post("/api/workspaces/default/activate")
    restored = c.get("/api/settings")
    assert restored.json()["settings"]["pages"] == 4
    assert restored.json()["settings"]["model"] == "ollama"


def test_switch_workspace_swaps_master_resume(client, tmp_path, monkeypatch):
    """Activating a different profile serves that profile's own master resume."""
    c, _ = client
    real_resume_json = config.MASTER_RESUME_PATH.read_text(encoding="utf-8")
    _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()  # empty "default": nothing to migrate under the isolated roots

    payload = json.loads(real_resume_json)
    payload["contact"]["name"] = "Default Person"
    config.MASTER_RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MASTER_RESUME_PATH.write_text(json.dumps(payload), encoding="utf-8")

    c.post("/api/workspaces", json={"label": "Second"})
    second_paths = config.workspace_paths("second")
    second_paths["MASTER_RESUME_PATH"].parent.mkdir(parents=True, exist_ok=True)
    payload["contact"]["name"] = "Second Person"
    second_paths["MASTER_RESUME_PATH"].write_text(json.dumps(payload), encoding="utf-8")

    assert c.get("/api/master-resume").json()["contact"]["name"] == "Default Person"

    activate_res = c.post("/api/workspaces/second/activate")
    assert activate_res.status_code == 200
    assert activate_res.json()["config"]["contact_name"] == "Second Person"
    assert c.get("/api/master-resume").json()["contact"]["name"] == "Second Person"

    c.post("/api/workspaces/default/activate")
    assert c.get("/api/master-resume").json()["contact"]["name"] == "Default Person"


def test_job_artifacts_land_under_active_workspace(client, tmp_path, monkeypatch):
    """A finished job's out_dir sits under the active profile's output/workspaces/<id>/."""
    c, q = client
    real_resume_json = config.MASTER_RESUME_PATH.read_text(encoding="utf-8")
    roots = _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()
    config.MASTER_RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MASTER_RESUME_PATH.write_text(real_resume_json, encoding="utf-8")

    load()  # confirms the copied-over resume file is loadable before the job reads it

    def fake_extract(text, *, known_tags=None, use_cache=True, on_event=None):
        from resume_tailor.pipeline.jd import JobRequirements, Keyword

        return JobRequirements(
            title="Stub Role",
            seniority="intern",
            keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
        )

    def fake_score(bullets, requirements, *, use_cache=True, on_event=None):
        return {b.id: 5.0 for b in bullets}

    def fake_fit(resume, requirements, *, out=None, on_event=None, **kwargs):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK")
        out.with_suffix(".pdf").write_bytes(b"%PDF-1.4 stub")
        bullet = resume.all_bullets()[0]
        return FitResult(
            out_path=out,
            pages=1,
            pages_are_estimated=False,
            iterations=1,
            bullets_selected=1,
            bullets_total=1,
            bullets={bullet.id: bullet.text},
            semantic_used=False,
        )

    def fake_facets(resume, requirements, **kwargs):
        from resume_tailor.pipeline import facets as facets_mod

        return facets_mod.budget_only(
            resume, requirements, include_project_links=kwargs.get("include_project_links", True)
        )

    from resume_tailor.pipeline.expand import Expansion

    monkeypatch.setattr(jobs_mod.jd, "extract", fake_extract)
    monkeypatch.setattr(jobs_mod.relevance, "score_table", fake_score)
    monkeypatch.setattr(jobs_mod.fit, "fit", fake_fit)
    monkeypatch.setattr(jobs_mod.jd, "verify_verbatim", lambda *a, **k: [])
    monkeypatch.setattr(jobs_mod.facets, "select_facets", fake_facets)
    monkeypatch.setattr(
        jobs_mod.expand, "expand_experience", lambda *a, **k: Expansion(entries=[], model="stub")
    )

    res = c.post("/api/jobs", json={"jd_text": "Looking for a Python intern."})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        status = c.get(f"/api/jobs/{job_id}").json()
        if status["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    else:
        pytest.fail("job did not finish in time")
    assert status["status"] == "succeeded", status

    job = q.get(job_id)
    expected_root = roots["output"] / "workspaces" / "default" / "jobs" / job_id
    assert job.out_dir == expected_root


def test_profile_template_install_works_on_a_freshly_created_profile(
    client, tmp_path, monkeypatch
):
    """Wizard (profile) install into a profile created *without* duplicating.

    Regression, reported from Docker: such a profile had no master_resume.json, so
    `_install_with_profile`'s smoke render raised
    "Staged build or smoke render failed: Master resume not found at
    .../workspaces/<id>/master_resume.json" and no template could ever be installed.

    Must exercise the **profile** path specifically — `_install_legacy` never calls
    `_smoke_render`, so a legacy-path install passes even with the bug present.
    Only the `_run_build` subprocess spawn is stubbed here — it builds in-process
    instead — so the smoke render and build verification that follow it both see an
    actually-tagged template, not a placeholder, and stay real regression checks
    rather than passing on unverified output.
    """
    from resume_tailor.document import template_build as tb_mod

    c, _ = client
    _point_workspaces_at(tmp_path, monkeypatch)
    real_bootstrap()

    c.post("/api/workspaces", json={"label": "Nina"})  # no copy_from
    assert c.post("/api/workspaces/nina/activate").status_code == 200

    def fake_build(*, source=None, output=None, profile_path=None, legacy=False):
        """Skip the subprocess spawn but still run the real build in-process."""
        out = Path(output) if output else config.DEFAULT_TEMPLATE_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        loaded_profile = template_profile.load_profile(Path(profile_path))
        tb_mod.build_from_profile(Path(source), out, loaded_profile)
        return 0, "stub build ok"

    monkeypatch.setattr(template_ops, "_run_build", fake_build)

    upload = _resume_docx_bytes()
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    analyzed = c.post("/api/template/analyze", files={"file": ("nina.docx", upload, mime)})
    assert analyzed.status_code == 200
    profile = analyzed.json()["suggested_profile"]
    assert profile, analyzed.json()["issues"]

    res = c.post(
        "/api/template",
        data={"label": "Nina Template", "profile": json.dumps(profile)},
        files={"file": ("nina.docx", upload, mime)},
    )
    assert res.status_code == 200, res.json()
    assert res.json()["ok"] is True
