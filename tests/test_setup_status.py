"""Setup checklist (UI4): no network, no paid calls."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.web.app import app
from resume_tailor.web.routes import setup as setup_routes
from tests.fixtures import synthetic_resume


def _status(c) -> dict[str, dict]:
    body = c.get("/api/setup-status").json()
    return body, {item["id"]: item for item in body["items"]}


def test_checklist_reports_each_prerequisite(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", tmp_path / "none.docx")
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "profile.json")
    probed: list[str] = []

    def _probe(url):
        probed.append(url)
        return "ConnectError"

    monkeypatch.setattr(setup_routes, "probe_local_server", _probe)
    monkeypatch.setattr(
        setup_routes.workspace, "load_settings", lambda *a: {"defaults": {"model": "ollama"}}
    )
    with TestClient(app) as c:
        body, items = _status(c)
        assert items["model"]["ok"] is False and "not answering" in items["model"]["detail"]
        assert probed
        assert items["template"]["ok"] is False and items["resume"]["ok"] is False
        assert items["profile"]["optional"] is True
        assert body["ready"] is False and body["remaining"] == 3

        path = tmp_path / "resume.json"
        path.write_text(json.dumps(synthetic_resume().model_dump(mode="json", by_alias=True)))
        monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
        (tmp_path / "t.docx").write_bytes(b"x")
        monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", tmp_path / "t.docx")
        monkeypatch.setattr(setup_routes, "probe_local_server", lambda url: None)
        body, items = _status(c)
        assert items["model"]["ok"] and items["resume"]["ok"] and items["template"]["ok"]
        assert body["ready"] is True


def test_missing_api_key_is_a_gap_without_any_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "credential", lambda name: None)
    monkeypatch.setattr(
        setup_routes, "probe_local_server", lambda url: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(
        setup_routes.workspace, "load_settings", lambda *a: {"defaults": {"model": "claude"}}
    )
    with TestClient(app) as c:
        _body, items = _status(c)
        assert items["model"]["ok"] is False and "API key" in items["model"]["detail"]


def test_ollama_cloud_is_probed_with_the_key_not_as_a_local_server(monkeypatch):
    """https://ollama.com/v1 is hosted: never "start it"; the key goes along."""
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "https://ollama.com/v1")
    monkeypatch.setattr(config, "credential", lambda name: "sk-test" if name == "OLLAMA_API_KEY" else "")
    monkeypatch.setattr(
        setup_routes, "probe_local_server", lambda url: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(
        setup_routes.workspace, "load_settings", lambda *a: {"defaults": {"model": "ollama"}}
    )
    calls: list[dict] = []

    class _Response:
        def __init__(self, status):
            self.status_code = status

    status = {"code": 401}

    def _get(url, headers=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "timeout": timeout})
        return _Response(status["code"])

    monkeypatch.setattr(setup_routes.httpx, "get", _get)
    setup_routes.clear_probe_cache()
    with TestClient(app) as c:
        _body, items = _status(c)
        assert items["model"]["ok"] is False
        assert "rejected the API key" in items["model"]["detail"]
        assert "Start it" not in items["model"]["detail"]
        assert calls[0]["url"] == "https://ollama.com/v1/models"
        assert calls[0]["headers"] == {"Authorization": "Bearer sk-test"}
        # Cached until a successful "Test connection" clears it.
        status["code"] = 200
        assert _status(c)[1]["model"]["ok"] is False
        setup_routes.clear_probe_cache()
        assert _status(c)[1]["model"]["ok"] is True
