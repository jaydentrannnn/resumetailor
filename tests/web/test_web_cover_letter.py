"""`/api/cover-letter/settings` and `/api/cover-letter/preview`."""

from __future__ import annotations

import zipfile

from resume_tailor import config
from resume_tailor.document import render, template_analyze, thumbnails
from tests.fixtures import _docx_bytes, _table_resume
from tests.web.helpers import _point_templates_at


def _install_table_template(tmp_path, monkeypatch):
    templates = _point_templates_at(tmp_path, monkeypatch)
    raw = _docx_bytes(_table_resume)
    profile = template_analyze.analyze_docx(raw=raw).suggested_profile
    (templates / "original_export.docx").write_bytes(raw)
    (templates / "template_profile.json").write_text(profile.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    return templates


def test_settings_default_then_round_trip(client, tmp_path, monkeypatch):
    c, _ = client
    _install_table_template(tmp_path, monkeypatch)
    body = c.get("/api/cover-letter/settings").json()
    assert body["settings"]["letterhead"] == "same_as_resume"
    assert body["settings"]["blocks"]["subject"] is False
    ids = [f["id"] for f in body["fields"]]
    assert ids[:5] == ["location", "email", "phone", "linkedin", "github"]
    assert "custom:street_address" in ids

    chosen = {
        **body["settings"],
        "letterhead": "custom",
        "letterhead_fields": ["email", "custom:street_address"],
        "closing_text": "Best,",
    }
    assert c.put("/api/cover-letter/settings", json=chosen).status_code == 200
    again = c.get("/api/cover-letter/settings").json()["settings"]
    assert again["letterhead_fields"] == ["email", "custom:street_address"]
    assert again["closing_text"] == "Best,"


def test_settings_reject_an_unknown_field(client, tmp_path, monkeypatch):
    c, _ = client
    _install_table_template(tmp_path, monkeypatch)
    res = c.put("/api/cover-letter/settings", json={"letterhead_fields": ["fax"]})
    assert res.status_code == 422


def test_preview_renders_unsaved_settings(client, tmp_path, monkeypatch):
    c, _ = client
    _install_table_template(tmp_path, monkeypatch)
    rendered: list = []

    def fake_to_pdf(docx_path, pdf_path=None, **_kwargs):
        rendered.append(zipfile.ZipFile(docx_path).read("word/document.xml").decode("utf-8"))
        target = pdf_path or docx_path.with_suffix(".pdf")
        target.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return target

    def fake_png(pdf_path, out, **_kwargs):
        out.write_bytes(b"PNG fake")
        return out

    monkeypatch.setattr(render, "to_pdf", fake_to_pdf)
    monkeypatch.setattr(thumbnails, "pdf_first_page_png", fake_png)
    res = c.post("/api/cover-letter/preview", json={"closing_text": "Warmly,"})
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert "Warmly," in rendered[0]  # rendered from the unsaved draft
    assert not config.COVER_SETTINGS_PATH.exists()  # a preview never saves

    # Same settings again: served from cache, no second render.
    assert c.post("/api/cover-letter/preview", json={"closing_text": "Warmly,"}).status_code == 200
    assert len(rendered) == 1


def test_preview_without_a_template_is_404(client, tmp_path, monkeypatch):
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    assert c.post("/api/cover-letter/preview", json={}).status_code == 404
