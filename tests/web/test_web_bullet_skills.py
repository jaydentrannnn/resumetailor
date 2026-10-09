"""Computed bullet skills over the web: the read-only skills endpoint and the background
refresh every save schedules."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.content.data import load
from resume_tailor.pipeline import tag_infer
from resume_tailor.web import skill_refresh
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
