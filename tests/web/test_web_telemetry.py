"""Consumption is recorded only for available artifacts and successful delivery."""

from types import SimpleNamespace

from resume_tailor.infra import usage_report
from resume_tailor.web.routes import jobs


def resolved(client, monkeypatch, tmp_path):
    directory = tmp_path / "output/jobs/job"
    directory.mkdir(parents=True)
    (directory / "skills.json").write_text('{"skills": []}')
    (directory / "skills.md").write_text("Python")
    value = SimpleNamespace(status="succeeded", out_dir=directory)
    monkeypatch.setattr(
        jobs.run_lookup, "_resolve_run", lambda jid: value if jid == "job" else None
    )
    monkeypatch.setattr(jobs.run_lookup, "_export_download_name", lambda *a, **k: "skills.md")
    return value, tmp_path / "output"


def test_copy_and_completed_download_are_recorded(client, monkeypatch, tmp_path):
    c, _ = client
    _, output = resolved(client, monkeypatch, tmp_path)
    assert (
        c.post(
            "/api/jobs/job/artifact-usage", json={"artifact": "skills", "action": "copy"}
        ).status_code
        == 204
    )
    assert c.get("/api/jobs/job/skills.md").content == b"Python"
    events = usage_report.read_consumption(output)
    assert [e["action"] for e in events] == ["copy", "download"]
    assert all(e["archive_id"] == "job" for e in events)
    assert "Python" not in (output / "telemetry/artifact_usage.jsonl").read_text()


def test_usage_validation_and_missing_artifacts_do_not_record(client, monkeypatch, tmp_path):
    c, _ = client
    value, output = resolved(client, monkeypatch, tmp_path)
    for body in (
        {"artifact": "resume", "action": "copy"},
        {"artifact": "skills", "action": "autofill"},
        {"artifact": "skills", "action": "copy", "text": "private"},
    ):
        assert c.post("/api/jobs/job/artifact-usage", json=body).status_code == 422
    body = {"artifact": "skills", "action": "copy"}
    assert c.post("/api/jobs/missing/artifact-usage", json=body).status_code == 404
    value.status = "running"
    assert c.post("/api/jobs/job/artifact-usage", json=body).status_code == 409
    value.status = "succeeded"
    (value.out_dir / "skills.json").unlink()
    assert c.post("/api/jobs/job/artifact-usage", json=body).status_code == 409
    assert usage_report.read_consumption(output) == []


def test_failed_telemetry_does_not_block_copy_endpoint(client, monkeypatch, tmp_path):
    c, _ = client
    resolved(client, monkeypatch, tmp_path)
    monkeypatch.setattr(type(tmp_path), "open", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert (
        c.post(
            "/api/jobs/job/artifact-usage", json={"artifact": "skills", "action": "copy"}
        ).status_code
        == 204
    )
