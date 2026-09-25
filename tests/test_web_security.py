"""The request gate: Host allow-list, cross-site writes, and the opt-in session token."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config, logs
from resume_tailor.web import security
from resume_tailor.web.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def test_foreign_host_is_refused(client):
    response = client.get("/api/config", headers={"host": "evil.example"})
    assert response.status_code == 400
    assert "RESUME_TAILOR_ALLOWED_HOSTS" in response.json()["detail"]


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost", "[::1]:8000", "LOCALHOST:5173"])
def test_loopback_hosts_pass(client, host):
    assert client.get("/api/config", headers={"host": host}).status_code == 200


def test_allowed_hosts_env_adds_names(client, monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_ALLOWED_HOSTS", "testserver,resume.example.com")
    ok = client.get("/api/config", headers={"host": "resume.example.com"})
    assert ok.status_code == 200


def test_cross_site_write_is_refused(client):
    response = client.put(
        "/api/secrets/GEMINI_API_KEY",
        json={"value": "x"},
        headers={"origin": "https://evil.example"},
    )
    assert response.status_code == 403
    fetch_site = client.put(
        "/api/secrets/GEMINI_API_KEY",
        json={"value": "x"},
        headers={"sec-fetch-site": "cross-site"},
    )
    assert fetch_site.status_code == 403


def test_same_origin_write_passes(client):
    response = client.put(
        "/api/secrets/GEMINI_API_KEY",
        json={"value": "x"},
        headers={"origin": "http://localhost:5173", "sec-fetch-site": "same-origin"},
    )
    assert response.status_code == 200


def test_token_off_by_default(client):
    assert security.session_token() is None
    assert client.get("/api/config").status_code == 200


def test_token_required_when_set(client, monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "tok-123456789")
    missing = client.get("/api/config")
    assert missing.status_code == 401
    assert missing.json()["error"] == "auth"
    assert client.get("/api/config", headers={"x-rt-token": "wrong"}).status_code == 401
    assert client.get("/api/config", headers={"x-rt-token": "tok-123456789"}).status_code == 200
    assert client.get("/api/health").json()["app"] == "resumetailor"


def test_sign_in_link_sets_cookie(client, monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "tok-123456789")
    response = client.get("/?t=tok-123456789", follow_redirects=False)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "rt_session=tok-123456789" in cookie and "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert client.get("/api/config").status_code == 200  # TestClient kept the cookie


def test_auto_token_is_written_for_local_clients(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "auto")
    monkeypatch.setattr(security, "_auto_token", None)
    with TestClient(app) as test_client:
        token = security.session_token()
        assert token and security.token_file().read_text(encoding="utf-8") == token
        assert security.read_client_token() == token
        ok = test_client.get("/api/config", headers={"x-rt-token": token})
        assert ok.status_code == 200


def test_token_is_redacted_from_logs():
    assert "abcdef123456" not in logs.redact("GET /?t=abcdef123456 HTTP/1.1")
