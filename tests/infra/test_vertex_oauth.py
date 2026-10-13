"""OAuth state, PKCE, timeout and callback lifecycle without listening or networking."""

import io
import json
import threading
from types import SimpleNamespace

import pytest

from resume_tailor.infra import vertex_auth, vertex_oauth


@pytest.fixture
def authorization(monkeypatch):
    from google_auth_oauthlib.flow import Flow

    captured = {}
    credentials = SimpleNamespace(
        granted_scopes=vertex_oauth.SCOPES,
        scopes=vertex_oauth.SCOPES,
        token="access-secret",
        to_json=lambda: json.dumps(
            {
                "refresh_token": "refresh-secret",
                "token": "access-secret",
                "client_id": "id",
                "client_secret": "config",
            }
        ),
    )
    fake_flow = SimpleNamespace(credentials=credentials, oauth2session=SimpleNamespace(token={}))
    fake_flow.authorization_url = lambda **kwargs: (
        captured.update(kwargs) or ("https://accounts.google.com/auth", "expected-state")
    )
    fake_flow.fetch_token = lambda **kwargs: captured.update(kwargs)

    def create(_config, **kwargs):
        captured.update(kwargs)
        return fake_flow

    class Server:
        server_port = 12345

        def __init__(self, address, handler):
            captured["address"], captured["handler"] = address, handler
            self.closed = False

        def handle_request(self):
            pass

        def server_close(self):
            self.closed = True

    monkeypatch.setattr(Flow, "from_client_config", create)
    monkeypatch.setattr(vertex_oauth, "HTTPServer", Server)
    auth = vertex_oauth.Authorization({"installed": {}})
    yield auth, captured
    auth.cancel()


def callback(auth, captured, query):
    handler = captured["handler"].__new__(captured["handler"])
    handler.path = f"/callback?{query}"
    handler.wfile = io.BytesIO()
    handler.send_error = lambda *args: captured.update(error=args)
    handler.send_response = lambda *args: captured.update(response=args)
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    handler.do_GET()


def test_pkce_loopback_and_invalid_state_do_not_exchange_tokens(authorization):
    auth, captured = authorization
    assert captured["autogenerate_code_verifier"]
    assert captured["access_type"] == "offline"
    assert captured["address"] == ("127.0.0.1", 0)
    assert auth.flow.redirect_uri == "http://127.0.0.1:12345/callback"
    callback(auth, captured, "state=wrong&code=private-code")
    assert captured["error"][0] == 400
    assert "code" not in captured
    assert auth.status == "pending"


def test_success_removes_access_token_from_storage_and_replay_is_ignored(
    authorization, monkeypatch
):
    import requests

    auth, captured = authorization
    seen = []
    monkeypatch.setattr(
        requests,
        "get",
        lambda *_a, **_k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"email": "user@example.test"},
        ),
    )
    monkeypatch.setattr(
        vertex_auth, "save", lambda creds, email, epoch: seen.append((creds, email))
    )
    callback(auth, captured, "state=expected-state&code=private-code")
    assert auth.status == "connected"
    assert "token" not in seen[0][0]
    assert seen[0][0]["type"] == "authorized_user"
    callback(auth, captured, "state=expected-state&code=replay")
    assert len(seen) == 1
    assert captured["code"] == "private-code"


@pytest.mark.parametrize("action", ["denied", "cancelled", "timeout"])
def test_terminal_states_close_listener_without_auth_exchange(authorization, monkeypatch, action):
    auth, captured = authorization
    if action == "denied":
        callback(auth, captured, "state=expected-state&error=access_denied")
    elif action == "cancelled":
        auth.cancel()
        callback(auth, captured, "state=expected-state&code=late")
    else:
        monkeypatch.setattr(vertex_oauth.time, "monotonic", lambda: auth.started + 301)
    auth.listen()
    assert auth.status in {"cancelled", "expired"}
    assert auth.server.closed
    assert "code" not in captured


def test_missing_configuration_is_actionable(monkeypatch):
    monkeypatch.setattr(vertex_oauth, "client_config", lambda: None)
    with pytest.raises(vertex_auth.ConnectionError, match="Desktop OAuth client"):
        vertex_oauth.start()


def test_release_client_configuration_comes_from_owner_environment(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_GOOGLE_CLIENT_ID", "desktop-client")
    monkeypatch.setenv("RESUME_TAILOR_GOOGLE_CLIENT_SECRET", "installed-app-config")
    configured = vertex_oauth.client_config()["installed"]
    assert configured["client_id"] == "desktop-client"
    assert configured["token_uri"] == "https://oauth2.googleapis.com/token"


def test_exchange_failure_is_redacted(authorization):
    auth, captured = authorization

    def fail(**_kwargs):
        raise RuntimeError("private-refresh-token")

    auth.flow.fetch_token = fail
    callback(auth, captured, "state=expected-state&code=private-code")
    assert auth.status == "failed"
    assert "private" not in auth.detail


def test_cancel_during_token_exchange_cannot_save_late_credentials(authorization, monkeypatch):
    auth, _captured = authorization
    entered, release = threading.Event(), threading.Event()
    saved = []

    def exchange(_code):
        entered.set()
        assert release.wait(2)
        return {"refresh_token": "late-secret"}, "late@example.test"

    monkeypatch.setattr(auth, "exchange", exchange)
    monkeypatch.setattr(vertex_auth, "save", lambda *_args: saved.append(True))
    worker = threading.Thread(target=auth.complete, args=({"code": ["code"]},))
    worker.start()
    try:
        assert entered.wait(1)
        auth.cancel()
    finally:
        release.set()
        worker.join(2)
    assert auth.status == "cancelled"
    assert not saved
