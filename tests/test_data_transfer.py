"""Profile export / import / reset (Settings → Data) and the Settings-page routes."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from resume_tailor import config, data_transfer, workspace
from resume_tailor.apply import store
from resume_tailor.workspace import bootstrap
from tests.test_workspace import isolated_roots  # noqa: F401 - pytest fixture


@pytest.fixture
def active(isolated_roots):  # noqa: F811
    bootstrap()
    workspace_id = config.active_workspace_id()
    store.upsert(store.Application(source="s", source_job_id="1", company="Acme", role="Analyst"))
    (config.DATA_DIR / "secrets.enc").write_bytes(b"never exported")
    (config.DATA_DIR / ".session_token").write_text("tok")
    (config.TEMPLATES_DIR / "main_template.docx").write_bytes(b"tagged")
    (config.OUTPUT_DIR / "jobs" / "j1").mkdir(parents=True)
    (config.OUTPUT_DIR / "jobs" / "j1" / "resume.pdf").write_bytes(b"%PDF")
    return workspace_id


def _names(raw: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return set(archive.namelist())


def test_export_includes_content_and_never_secrets(active):
    raw = data_transfer.export_zip(active)
    names = _names(raw)
    assert {"manifest.json", "data/app.db", "data/master_resume.json"} <= names
    assert "templates/main_template.docx" in names and "output/jobs/j1/resume.pdf" in names
    assert not any(n.endswith(("secrets.enc", ".session_token", "-wal", "-shm")) for n in names)
    manifest = data_transfer.read_manifest(raw)
    assert manifest["secrets_included"] is False
    assert "output/jobs/j1/resume.pdf" not in _names(
        data_transfer.export_zip(active, include_output=False)
    )


def test_import_creates_a_new_profile_with_the_same_data(active):
    raw = data_transfer.export_zip(active)
    entry = data_transfer.import_zip(raw)
    assert entry.id != active and "(imported)" in entry.label
    again = data_transfer.import_zip(raw)
    assert again.id not in {entry.id, active} and again.label.endswith("2")

    workspace.activate(entry.id)
    assert store.get("1").company == "Acme"
    assert config.DEFAULT_TEMPLATE_PATH.read_bytes() == b"tagged"
    meta = json.loads((config.DATA_DIR / "workspace.json").read_text())
    assert meta["id"] == entry.id  # the new profile keeps its own identity


def test_import_rejects_unsafe_and_foreign_zips(active):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "resumetailor-export", "format_version": 1}))
        archive.writestr("data/../../evil.txt", "x")
    with pytest.raises(data_transfer.TransferError, match="unsafe path"):
        data_transfer.import_zip(buffer.getvalue())

    with pytest.raises(data_transfer.TransferError, match="not a ResumeTailor export"):
        data_transfer.import_zip(b"not a zip")
    newer = io.BytesIO()
    with zipfile.ZipFile(newer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "resumetailor-export", "format_version": 99}))
    with pytest.raises(data_transfer.TransferError, match="newer"):
        data_transfer.import_zip(newer.getvalue())
    assert len(workspace.list_workspaces()) == 1  # nothing half-created


def test_reset_moves_everything_to_trash_and_starts_fresh(active):
    trash = data_transfer.reset_workspace(active)
    config.set_active_workspace(active, create_dirs=True)
    store._cache = None
    assert store.load_all() == {}
    assert (trash / "data" / "app.db").exists()
    assert (trash / "output" / "jobs" / "j1" / "resume.pdf").exists()
    assert config.MASTER_RESUME_PATH.exists()  # starter placeholder, so the editor works
    assert (config.DATA_DIR / "workspace.json").exists()
    assert not config.DEFAULT_TEMPLATE_PATH.exists()


class _FakeMessages:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.kwargs: dict = {}

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return object()


class _FakeClient:
    def __init__(self, error: Exception | None = None):
        self.messages = _FakeMessages(error)


def test_model_test_route_reports_success_and_failure(monkeypatch):
    from fastapi.testclient import TestClient

    from resume_tailor import llm
    from resume_tailor.web.app import app

    fake = _FakeClient()
    monkeypatch.setattr(llm, "client_for", lambda purpose: fake)
    with TestClient(app) as c:
        ok = c.post("/api/models/test", json={"settings": {"model": "ollama"}}).json()
        assert ok["ok"] is True and ok["model"].startswith("ollama:")
        assert fake.messages.kwargs["max_tokens"] == 256
        monkeypatch.setattr(
            llm, "client_for", lambda purpose: _FakeClient(llm.LLMError("Could not reach x"))
        )
        bad = c.post("/api/models/test", json={"settings": {"model": "ollama"}}).json()
        assert bad == {"ok": False, "model": bad["model"], "detail": "Could not reach x"}


def test_pdf_test_route(monkeypatch):
    from fastapi.testclient import TestClient

    from resume_tailor import convert
    from resume_tailor.web.app import app

    def _fake_convert(src, dst, **_k):
        dst.write_bytes(b"%PDF")
        return dst

    monkeypatch.setattr(convert, "convert", _fake_convert)
    with TestClient(app) as c:
        assert c.post("/api/pdf/test").json()["ok"] is True
        monkeypatch.setattr(
            convert, "convert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no soffice"))
        )
        assert c.post("/api/pdf/test").json() == {
            "ok": False, "backend": config.PDF_BACKEND, "detail": "no soffice"
        }


def test_reset_route_requires_typed_confirmation():
    from fastapi.testclient import TestClient

    from resume_tailor.web.app import app

    with TestClient(app) as c:
        assert c.post("/api/data/reset", json={"confirm": "delete"}).status_code == 400
