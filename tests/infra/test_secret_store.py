"""Secrets: backends, the plaintext-to-store migrations, API keys, and the routes."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.ats import workday_auth
from resume_tailor.infra import secret_store


def _file_backend(tmp_path):
    return secret_store._FileBackend(tmp_path / "secrets.enc", tmp_path / ".secret_key")


def test_file_backend_round_trip_is_encrypted(tmp_path, monkeypatch):
    monkeypatch.delenv("RESUME_TAILOR_SECRET_KEY", raising=False)
    store = _file_backend(tmp_path)
    store.set("api_key:X", "sk-very-secret")
    assert store.get("api_key:X") == "sk-very-secret"
    assert b"sk-very-secret" not in (tmp_path / "secrets.enc").read_bytes()
    store.delete("api_key:X")
    assert store.get("api_key:X") is None
    if sys.platform != "win32":
        mode = stat.S_IMODE(os.stat(tmp_path / ".secret_key").st_mode)
        assert mode == 0o600


def test_file_backend_wrong_key_is_an_error_not_empty(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.delenv("RESUME_TAILOR_SECRET_KEY", raising=False)
    _file_backend(tmp_path).set("a", "b")
    monkeypatch.setenv("RESUME_TAILOR_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(secret_store.SecretStoreError):
        _file_backend(tmp_path).get("a")


def test_chooses_file_backend_without_a_keychain(tmp_path, monkeypatch):
    import keyring
    from keyring.backends import fail

    monkeypatch.delenv("RESUME_TAILOR_SECRETS_BACKEND", raising=False)
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    secret_store.reset_backend()
    assert secret_store.backend().name == "file"


def test_empty_value_deletes():
    secret_store.set("k", "v")
    secret_store.set("k", "")
    assert secret_store.get("k") is None


# --- applicant profile ------------------------------------------------------------


def test_profile_password_never_written_to_json():
    profile_mod.save_profile(profile_mod.ApplicantProfile(workday_password="Secret!42"))
    on_disk = json.loads(config.APPLICANT_PROFILE_PATH.read_text(encoding="utf-8"))
    assert on_disk["workday_password"] == ""
    loaded, _seeded = profile_mod.load_profile()
    assert loaded.workday_password == "Secret!42"


def test_plaintext_profile_password_is_migrated_once():
    path = config.APPLICANT_PROFILE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"first_name": "Ada", "workday_password": "Old!pw1"}), "utf-8")
    loaded, _seeded = profile_mod.load_profile()
    assert loaded.workday_password == "Old!pw1"
    assert json.loads(path.read_text(encoding="utf-8"))["workday_password"] == ""
    assert list(path.parent.glob("*.bak.json"))  # backed up before rewriting
    assert profile_mod.load_profile()[0].workday_password == "Old!pw1"


def test_saving_a_profile_without_password_keeps_the_stored_one():
    profile_mod.save_profile(profile_mod.ApplicantProfile(workday_password="Keep!me1"))
    profile_mod.save_profile(profile_mod.ApplicantProfile(first_name="Ada"))
    assert profile_mod.load_profile()[0].workday_password == "Keep!me1"
    profile_mod.clear_workday_password()
    assert profile_mod.load_profile()[0].workday_password == ""


def test_locked_store_keeps_password_in_file(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise secret_store.SecretStoreError("locked")

    monkeypatch.setattr(secret_store, "set", refuse)
    profile_mod.save_profile(profile_mod.ApplicantProfile(workday_password="Kept!1x"))
    on_disk = json.loads(config.APPLICANT_PROFILE_PATH.read_text(encoding="utf-8"))
    assert on_disk["workday_password"] == "Kept!1x"


# --- Workday vault ------------------------------------------------------------------


def test_vault_passwords_move_to_the_store():
    path = workday_auth._vault_path()
    path.write_text(json.dumps({"acme.wd5.myworkdayjobs.com": {
        "email": "a@example.com", "password": "Gen!pw12", "created": True,
    }}), encoding="utf-8")
    vault = workday_auth._load_vault()
    assert vault["acme.wd5.myworkdayjobs.com"]["password"] == "Gen!pw12"
    workday_auth._save_vault(vault)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "password" not in on_disk["acme.wd5.myworkdayjobs.com"]
    assert on_disk["acme.wd5.myworkdayjobs.com"]["created"] is True
    assert workday_auth._load_vault()["acme.wd5.myworkdayjobs.com"]["password"] == "Gen!pw12"


# --- API keys -----------------------------------------------------------------------


def test_environment_key_wins_over_saved(monkeypatch):
    secret_store.set("api_key:GEMINI_API_KEY", "saved-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert config.credential("GEMINI_API_KEY") == "saved-key"
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    assert config.credential("GEMINI_API_KEY") == "env-key"


def test_unknown_names_are_never_read_from_the_store(monkeypatch):
    monkeypatch.delenv("PATH_TO_SOMETHING", raising=False)
    secret_store.set("api_key:PATH_TO_SOMETHING", "x")
    assert config.credential("PATH_TO_SOMETHING") == ""


def test_secret_routes_are_write_only(monkeypatch):
    from resume_tailor.web.app import app

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as client:
        put = client.put("/api/secrets/GEMINI_API_KEY", json={"value": "AIza-secret-value-123"})
        assert put.status_code == 200
        assert put.json() == {"name": "GEMINI_API_KEY", "set": True, "source": "saved"}
        listing = client.get("/api/secrets").json()
        assert "AIza-secret-value-123" not in json.dumps(listing)
        assert listing["backend"] == "memory"
        gemini = next(s for s in listing["secrets"] if s["name"] == "GEMINI_API_KEY")
        assert gemini["set"] is True
        assert client.put("/api/secrets/HOME", json={"value": "x"}).status_code == 404
        assert client.delete("/api/secrets/GEMINI_API_KEY").json()["set"] is False
