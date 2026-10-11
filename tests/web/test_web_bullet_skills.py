"""Computed bullet skills over the web: the read-only skills endpoint and the background
refresh every save schedules, its failure note and retry, and a run joining it."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from resume_tailor import config
from resume_tailor.content.data import load
from resume_tailor.pipeline import tag_infer
from resume_tailor.web import job_tailor_run, skill_refresh
from tests.fixtures import synthetic_resume


def _one_bullet_resume(text: str, *tags: str) -> dict:
    payload = load().model_dump(by_alias=True)
    for section in payload["sections"]:
        if section["kind"] == "experience":
            section["entries"] = section["entries"][:1]
            section["entries"][0]["bullets"] = [{"id": "b1", "text": text, "tags": list(tags)}]
        elif section["kind"] == "project":
            section["entries"] = []
    return payload


def test_saving_schedules_a_refresh_with_the_saved_resume(client, tmp_path, monkeypatch):
    c, _ = client
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    seen = []
    monkeypatch.setattr(skill_refresh, "schedule", seen.append)
    res = c.put("/api/master-resume", json=_one_bullet_resume("Built DCF models in Excel"))
    assert res.status_code == 200
    assert [b.text for b in seen[0].all_bullets()] == ["Built DCF models in Excel"]


def test_skills_endpoint_shows_detected_and_inferred_minus_extra_skills(
    client, tmp_path, monkeypatch
):
    c, _ = client
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert c.put(
        "/api/master-resume", json=_one_bullet_resume("Built DCF models in Excel", "excel")
    ).status_code == 200
    monkeypatch.setattr(
        tag_infer,
        "infer",
        lambda texts, preferred=(): {t: ["financial modeling", "excel"] for t in texts},
    )
    # Cached under the Tailor routing, exactly as the background refresh writes it.
    with skill_refresh.pinned_tailor():
        tag_infer.ensure(load())

    body = c.get("/api/master-resume/skills").json()
    assert body["bullets"]["b1"] == ["DCF", "financial modeling"]
    assert body["waiting"] == 0
    assert body["running"] is False and body["error"] is None


def test_refresh_runs_under_the_workspace_it_was_scheduled_for(tmp_path, monkeypatch):
    """A refresh records its error against its own profile and writes nothing on failure."""
    resume = synthetic_resume()

    def boom(texts, preferred=()):
        raise RuntimeError("model unreachable")

    monkeypatch.setattr(tag_infer, "infer", boom)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    job = skill_refresh._Job(None, resume, ("ollama", None, None))
    skill_refresh._run(job)
    running, error = skill_refresh.status()
    assert running is False
    assert error and "model unreachable" in error
    assert not (tmp_path / "inferred_tags.json").exists()
    skill_refresh._errors.clear()


def test_a_failed_refresh_is_reported_only_while_bullets_still_wait(
    client, tmp_path, monkeypatch
):
    c, _ = client
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert c.put(
        "/api/master-resume", json=_one_bullet_resume("Built DCF models in Excel")
    ).status_code == 200
    monkeypatch.setitem(
        skill_refresh._errors,
        skill_refresh._slot(config.active_workspace_id()),
        "Skill detection skipped (model unreachable)",
    )
    body = c.get("/api/master-resume/skills").json()
    assert body["waiting"] == 1
    assert "model unreachable" in body["error"]

    monkeypatch.setattr(tag_infer, "infer", lambda texts, preferred=(): {t: [] for t in texts})
    with skill_refresh.pinned_tailor():
        tag_infer.ensure(load())
    body = c.get("/api/master-resume/skills").json()
    assert body["waiting"] == 0 and body["error"] is None


def test_refresh_endpoint_schedules_the_saved_resume(client, tmp_path, monkeypatch):
    c, _ = client
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert c.put(
        "/api/master-resume", json=_one_bullet_resume("Built DCF models in Excel")
    ).status_code == 200
    seen = []
    monkeypatch.setattr(skill_refresh, "schedule", seen.append)
    res = c.post("/api/master-resume/skills/refresh")
    assert res.status_code == 200
    assert [b.text for b in seen[0].all_bullets()] == ["Built DCF models in Excel"]


def test_wait_idle_returns_once_the_refresh_in_flight_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    started, release = threading.Event(), threading.Event()

    def slow(resume, preferred=()):
        started.set()
        release.wait(5)
        return tag_infer.Inference(skills={})

    monkeypatch.setattr(tag_infer, "ensure", slow)
    with skill_refresh._LOCK:
        skill_refresh._pending = skill_refresh._Job(None, synthetic_resume(), ("ollama", None, None))
    worker = threading.Thread(target=skill_refresh._worker, daemon=True)
    worker.start()
    try:
        assert started.wait(5)
        assert skill_refresh.wait_idle(None, timeout=0.05) is False
    finally:
        release.set()
    assert skill_refresh.wait_idle(None, timeout=5) is True
    worker.join(5)
    assert not worker.is_alive()


def test_a_run_joins_the_refresh_in_flight_before_inferring(monkeypatch):
    calls: list[str] = []
    events: list[object] = []
    monkeypatch.setattr(job_tailor_run.skill_refresh, "status", lambda: (True, None))

    def wait_idle(workspace_id, timeout):
        calls.append("wait")
        return len(calls) >= 2  # idle on the second poll

    monkeypatch.setattr(job_tailor_run.skill_refresh, "wait_idle", wait_idle)
    job = SimpleNamespace(
        settings=None, emit=events.append, check_cancelled=lambda: calls.append("cancel?")
    )
    job_tailor_run._TailorJobRun(job)._join_skill_refresh()
    assert calls == ["wait", "cancel?", "wait"]
    assert [e.message for e in events] == ["Waiting for skill detection to finish"]


def test_a_run_skips_the_join_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr(job_tailor_run.skill_refresh, "status", lambda: (False, None))
    monkeypatch.setattr(
        job_tailor_run.skill_refresh, "wait_idle", lambda *a, **k: pytest.fail("no join")
    )
    events: list[object] = []
    job = SimpleNamespace(settings=None, emit=events.append, check_cancelled=lambda: None)
    job_tailor_run._TailorJobRun(job)._join_skill_refresh()
    assert events == []
