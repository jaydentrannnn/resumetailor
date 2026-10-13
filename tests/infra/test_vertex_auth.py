"""Google connection lifecycle; never reads ADC, the keychain or the network."""

import json
import sys
import threading
from types import SimpleNamespace

import pytest

from resume_tailor.infra import secret_store, vertex_auth, vertex_oauth


def connect(email="first@example.test"):
    vertex_auth.save(
        {
            "type": "authorized_user",
            "refresh_token": "private-refresh",
            "client_id": "desktop-id",
            "client_secret": "desktop-config",
            "scopes": vertex_oauth.SCOPES,
        },
        email,
        vertex_auth.epoch(),
    )
    return vertex_auth.state()["revision"]


def test_connection_is_write_only_and_replacement_invalidates_captured_clients():
    first = connect()
    state = vertex_auth.state()
    assert state["email"] == "first@example.test"
    assert "private-refresh" not in json.dumps(state)
    assert vertex_auth.credentials(first, "test-project")["quota_project_id"] == "test-project"
    second = connect("second@example.test")
    assert second != first
    with pytest.raises(vertex_auth.ConnectionError, match="changed or was removed"):
        vertex_auth.credentials(first, "test-project")
    vertex_auth.disconnect()
    assert vertex_auth.state()["connected"] is False
    assert secret_store.get(vertex_auth.SECRET) is None
    with pytest.raises(vertex_auth.ConnectionError):
        vertex_auth.credentials(second, "test-project")


def test_stale_oauth_completion_cannot_restore_disconnected_credentials():
    before = vertex_auth.epoch()
    vertex_auth.disconnect()
    with pytest.raises(vertex_auth.ConnectionError, match="superseded"):
        vertex_auth.save({"refresh_token": "late-token"}, "late@example.test", before)
    assert not vertex_auth.state()["connected"]


def test_access_tokens_are_never_persisted():
    vertex_auth.save(
        {
            "refresh_token": "offline",
            "token": "ephemeral",
            "id_token": "identity",
            "expiry": "tomorrow",
        },
        "user@example.test",
        vertex_auth.epoch(),
    )
    saved = json.loads(secret_store.get(vertex_auth.SECRET))
    assert saved["credentials"] == {"refresh_token": "offline"}


def test_missing_offline_access_preserves_existing_connection():
    revision = connect()
    with pytest.raises(vertex_auth.ConnectionError, match="offline access"):
        vertex_auth.save({}, "next@example.test", vertex_auth.epoch())
    assert vertex_auth.state()["revision"] == revision


def test_keychain_failure_does_not_expose_backend_details(monkeypatch):
    def fail(_name):
        raise secret_store.SecretStoreError("private-secret-value")

    monkeypatch.setattr(secret_store, "get", fail)
    with pytest.raises(vertex_auth.ConnectionError, match="Unlock your keychain") as error:
        vertex_auth.state()
    assert "private-secret-value" not in str(error.value)


def test_metadata_refresh_is_cached_and_revoked_signin_is_actionable(monkeypatch):
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials

    revision = connect()
    calls = []
    creds = SimpleNamespace(valid=False, token=None)

    def refresh(_request):
        calls.append(True)
        creds.valid, creds.token = True, "access-token"

    creds.refresh = refresh
    monkeypatch.setattr(Credentials, "from_authorized_user_info", lambda _info: creds)
    assert vertex_auth.access_token(revision, "test-project") == "access-token"
    assert vertex_auth.access_token(revision, "test-project") == "access-token"
    assert len(calls) == 1
    creds.valid = False

    def denied(_request):
        raise RefreshError("private-token")

    creds.refresh = denied
    with pytest.raises(vertex_auth.ConnectionError, match="expired or was revoked"):
        vertex_auth.access_token(revision, "test-project")


def test_disconnect_clears_sdk_credentials_without_loading_it(monkeypatch):
    handler = SimpleNamespace(
        _credentials_project_mapping={"old": "token"},
        _sync_refresh_lock=threading.RLock(),
        access_token="private-access",
        refresh_token="private-refresh",
        _credentials="private-credentials",
    )
    monkeypatch.setitem(sys.modules, "litellm.main", SimpleNamespace(vertex_handler=handler))
    vertex_auth.disconnect()
    assert not handler._credentials_project_mapping
    assert handler.access_token is handler.refresh_token is handler._credentials is None
