"""Cache and run-directory pruning (S5)."""

from __future__ import annotations

import os
import time

from resume_tailor import config, housekeeping
from resume_tailor.apply import store


def _file(path, size: int, age: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def test_prune_cache_drops_least_recently_used_first(tmp_path):
    old = _file(tmp_path / "old.scores.json", 100, age=300)
    mid = _file(tmp_path / "mid.jd.json", 100, age=200)
    new = _file(tmp_path / "new.cover.json", 100, age=10)
    result = housekeeping.prune_cache(tmp_path, max_bytes=150)
    assert result == {"removed": 2, "freed": 200}
    assert not old.exists() and not mid.exists() and new.exists()
    assert housekeeping.cache_usage(tmp_path) == {"files": 1, "bytes": 100}
    assert housekeeping.clear_cache(tmp_path)["removed"] == 1
    assert housekeeping.prune_cache(tmp_path / "missing") == {"removed": 0, "freed": 0}


def test_prune_jobs_keeps_newest_referenced_and_recent(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    for name, age in (("a", 9000), ("b", 8000), ("c", 7000), ("d", 60), ("e", 10)):
        (jobs / name).mkdir(parents=True)
        stamp = time.time() - age
        os.utime(jobs / name, (stamp, stamp))
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    store.upsert(store.Application(source="s", source_job_id="1", company="A", role="R", job_id="a"))
    result = housekeeping.prune_jobs(keep=1, jobs_dir=jobs)
    # e is newest (kept); d is recent (maybe running); a is referenced; b and c go.
    assert result == {"removed": 2}
    assert sorted(p.name for p in jobs.iterdir()) == ["a", "d", "e"]


def test_dedupe_run_templates_moves_legacy_copies_and_drops_unused(tmp_path):
    import json

    from resume_tailor import rerender

    jobs = tmp_path / "jobs"
    for name in ("a", "b"):
        (jobs / name).mkdir(parents=True)
        (jobs / name / rerender.TEMPLATE).write_bytes(b"same template")
        (jobs / name / rerender.SNAPSHOT).write_text(json.dumps({"version": 1}))
    store = tmp_path / rerender.TEMPLATE_STORE
    orphan = _file(store / "deadbeef.docx", 10, age=9000)
    fresh = _file(store / "cafef00d.docx", 10, age=10)  # a snapshot may still be on its way

    result = housekeeping.dedupe_run_templates(jobs)

    assert result == {"moved": 2, "removed": 1}
    assert not orphan.exists() and fresh.exists()
    shas = {json.loads((jobs / n / rerender.SNAPSHOT).read_text())["template_sha"] for n in "ab"}
    assert len(shas) == 1
    assert (store / f"{shas.pop()}.docx").read_bytes() == b"same template"
    assert not (jobs / "a" / rerender.TEMPLATE).exists()
    assert housekeeping.dedupe_run_templates(tmp_path / "missing") == {"moved": 0, "removed": 0}


def test_run_never_raises(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(housekeeping, "prune_cache", _boom)
    housekeeping.run()


def test_cache_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from resume_tailor.web import jobs as jobs_mod
    from resume_tailor.web.app import app

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    _file(config.CACHE_DIR / "x.jd.json", 10, age=0)
    with TestClient(app) as c:
        assert c.get("/api/cache").json()["files"] == 1
        monkeypatch.setattr(jobs_mod.JobQueue, "busy", lambda self: True)
        assert c.delete("/api/cache").status_code == 409
        monkeypatch.setattr(jobs_mod.JobQueue, "busy", lambda self: False)
        assert c.delete("/api/cache").json()["removed"] == 1
