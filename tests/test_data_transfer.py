"""Profile export / import / reset (Settings → Data) and the Settings-page routes."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

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


def _names(source: bytes | Path) -> set[str]:
    if isinstance(source, Path):
        with zipfile.ZipFile(source) as archive:
            return set(archive.namelist())
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        return set(archive.namelist())


def test_export_includes_content_and_never_secrets(active):
    raw = data_transfer.export_zip(active)
    try:
        names = _names(raw)
        assert {"manifest.json", "data/app.db", "data/master_resume.json"} <= names
        assert "templates/main_template.docx" in names and "output/jobs/j1/resume.pdf" in names
        assert not any(n.endswith(("secrets.enc", ".session_token", "-wal", "-shm")) for n in names)
        manifest = data_transfer.read_manifest(raw)
        assert manifest["secrets_included"] is False
    finally:
        raw.unlink(missing_ok=True)

    no_output = data_transfer.export_zip(active, include_output=False)
    try:
        assert "output/jobs/j1/resume.pdf" not in _names(no_output)
    finally:
        no_output.unlink(missing_ok=True)

    # export_zip_bytes wrapper returns valid bytes
    raw_bytes = data_transfer.export_zip_bytes(active)
    assert isinstance(raw_bytes, bytes)
    assert "manifest.json" in _names(raw_bytes)


def test_import_creates_a_new_profile_with_the_same_data(active):
    raw = data_transfer.export_zip(active)
    try:
        entry = data_transfer.import_zip(raw)
        assert entry.id != active and "(imported)" in entry.label
        raw_bytes = raw.read_bytes()
        again = data_transfer.import_zip(raw_bytes)
        assert again.id not in {entry.id, active} and again.label.endswith("2")
    finally:
        raw.unlink(missing_ok=True)

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


def test_import_route_accepts_upload_larger_than_10mb(active):
    """(a) POST /api/data/import with a valid export larger than 10 MB succeeds and creates a profile."""
    from fastapi.testclient import TestClient

    from resume_tailor.web.app import app

    export_path = data_transfer.export_zip(active)
    try:
        # Build an incompressible random payload over 10 MB (11 MB) stored uncompressed
        large_payload = os.urandom(11 * 1024 * 1024)
        buffer = io.BytesIO()
        with zipfile.ZipFile(export_path, "r") as src_zip:
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as dst_zip:
                for item in src_zip.infolist():
                    dst_zip.writestr(item, src_zip.read(item.filename))
                dst_zip.writestr("data/large_payload.bin", large_payload)
    finally:
        export_path.unlink(missing_ok=True)

    zip_bytes = buffer.getvalue()
    assert len(zip_bytes) > 10 * 1024 * 1024

    with TestClient(app) as c:
        response = c.post(
            "/api/data/import",
            files={"file": ("export.zip", zip_bytes, "application/zip")},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "id" in data and "label" in data
        assert workspace.resolve(data["id"]) is not None


def test_request_content_length_exceeding_import_limit_gets_413():
    """(b) A request whose Content-Length exceeds the import limit gets 413 without body read."""
    from fastapi.testclient import TestClient

    from resume_tailor.web.app import _RequestSizeLimitMiddleware, app

    limit = data_transfer.MAX_IMPORT_BYTES + _RequestSizeLimitMiddleware._MULTIPART_OVERHEAD
    with TestClient(app) as c:
        response = c.post(
            "/api/data/import",
            headers={"Content-Length": str(limit + 1024)},
            content=b"",
        )
        assert response.status_code == 413
        assert f"maximum is {limit}" in response.json()["detail"]


def test_non_import_route_over_10mb_gets_413():
    """(c) A non-import route over 10 MB still gets 413."""
    from fastapi.testclient import TestClient

    from resume_tailor.web import template_ops
    from resume_tailor.web.app import app

    over_10mb = template_ops._MAX_UPLOAD_BYTES + 1
    with TestClient(app) as c:
        response = c.post(
            "/api/models/test",
            headers={"Content-Length": str(over_10mb)},
            content=b"",
        )
        assert response.status_code == 413
        assert f"maximum is {template_ops._MAX_UPLOAD_BYTES}" in response.json()["detail"]


def test_import_zip_exceeding_declared_uncompressed_total_refused(monkeypatch):
    """(d) A zip whose declared uncompressed total exceeds MAX_IMPORT_BYTES is refused."""
    monkeypatch.setattr(data_transfer, "MAX_IMPORT_BYTES", 500)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"format": data_transfer.FORMAT, "format_version": data_transfer.FORMAT_VERSION}),
        )
        archive.writestr("data/large.txt", b"x" * 1000)

    with pytest.raises(data_transfer.TransferError, match="larger than 2 GB"):
        data_transfer.import_zip(buffer.getvalue())


def test_export_round_trips_through_import(active):
    """(e) Export round-trips through import."""
    from fastapi.testclient import TestClient

    from resume_tailor.web.app import app

    with TestClient(app) as c:
        export_res = c.get("/api/data/export.zip")
        assert export_res.status_code == 200
        assert export_res.headers["content-type"] == "application/zip"
        assert "Content-Disposition" in export_res.headers
        zip_bytes = export_res.content
        assert len(zip_bytes) > 0

        import_res = c.post(
            "/api/data/import",
            files={"file": ("export.zip", zip_bytes, "application/zip")},
        )
        assert import_res.status_code == 200, import_res.text
        created = import_res.json()
        assert created["id"] != active
        imported_ws = workspace.resolve(created["id"])
        assert imported_ws is not None
