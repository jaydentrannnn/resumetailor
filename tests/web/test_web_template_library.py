"""Template library entries, thumbnails, calibration, and starter templates."""

from __future__ import annotations

import hashlib

from resume_tailor import config
from resume_tailor.document import calibrate, default_templates
from resume_tailor.web import (
    template_defaults,
    template_install,
    template_library_store,
    template_ops,
)
from tests.web.helpers import _minimal_docx_bytes, _point_templates_at, _resume_upload_with_profile


def test_get_template_includes_profile_summary(client, tmp_path, monkeypatch):
    """GET /api/template always includes a profile summary object."""
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)
    res = c.get("/api/template")
    assert res.status_code == 200
    body = res.json()
    assert "profile" in body
    assert body["profile"]["exists"] is False


def test_upload_template_with_calibrate_flag(client, tmp_path, monkeypatch):
    """calibrate=true runs calibration after a successful build and reloads config."""
    from resume_tailor.document.calibrate import CalibrationResult

    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    baseline = templates / "original_export.docx"
    baseline.write_bytes(_minimal_docx_bytes())

    def stub_run_build(**_kwargs):
        return 1, "stub: subprocess skipped"

    cal_calls: list[dict] = []

    def fake_calibrate(*, verify_anchors=True):
        """Record the calibrate call without touching Word/LibreOffice."""
        cal_calls.append({"verify_anchors": verify_anchors})
        path = tmp_path / "calibration.json"
        path.write_text("{}", encoding="utf-8")
        return CalibrationResult(
            chars_per_line=99,
            lines_per_page=48,
            path=path,
            log="CHARS_PER_LINE = 99\nLINES_PER_PAGE = 48",
        )

    monkeypatch.setattr(template_install, "_run_build", stub_run_build)
    monkeypatch.setattr(calibrate, "run", fake_calibrate)
    monkeypatch.setattr(config, "reload_calibration", lambda: (99, 48, "test"))

    upload, profile = _resume_upload_with_profile()
    res = c.post(
        "/api/template",
        data={"calibrate": "true", "profile": profile},
        files={
            "file": (
                "resume.docx",
                upload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert cal_calls == [{"verify_anchors": True}]
    assert "CHARS_PER_LINE = 99" in body["log"]


def test_library_seeds_default_from_live(client, tmp_path, monkeypatch):
    """GET /api/template/library registers live baseline+tagged as Default when empty."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    payload = _minimal_docx_bytes()
    (templates / "original_export.docx").write_bytes(payload)
    (templates / "main_template.docx").write_bytes(payload)

    res = c.get("/api/template/library")
    assert res.status_code == 200
    body = res.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["label"] == "Default"
    assert body["entries"][0]["is_active"] is True
    assert body["active_id"] == body["entries"][0]["id"]

    info = c.get("/api/template").json()
    assert info["active_label"] == "Default"
    assert info["active_library_id"] == body["active_id"]


def test_upload_with_label_creates_library_entry(client, tmp_path, monkeypatch):
    """POST /api/template with label snapshots the install into the named library."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    old = _minimal_docx_bytes()
    (templates / "original_export.docx").write_bytes(old)
    # A prior tagged file alongside the baseline is what makes the live install look
    # like a genuine prior install worth preserving as "Default" before this one
    # overwrites it — without it there is no orphan live template to seed.
    (templates / "main_template.docx").write_bytes(old)

    def stub_run_build(**_kwargs):
        return 1, "stub: subprocess skipped"

    monkeypatch.setattr(template_install, "_run_build", stub_run_build)

    upload, profile = _resume_upload_with_profile()
    res = c.post(
        "/api/template",
        data={"label": "Campus CV", "profile": profile},
        files={
            "file": (
                "campus.docx",
                upload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 200, res.text
    info = res.json()["info"]
    assert info["active_label"] == "Campus CV"

    lib = c.get("/api/template/library").json()
    labels = {e["label"] for e in lib["entries"]}
    # Prior live was seeded/preserved as Default; new install is Campus CV.
    assert "Campus CV" in labels
    assert "Default" in labels
    active = next(e for e in lib["entries"] if e["is_active"])
    assert active["label"] == "Campus CV"


def test_activate_library_switches_live_baseline(client, tmp_path, monkeypatch):
    """Activating another library entry restores its baseline bytes into the live slot."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    tagged = templates / "main_template.docx"
    first = _minimal_docx_bytes()
    (templates / "original_export.docx").write_bytes(first)
    tagged.write_bytes(first)

    # Seed Default.
    assert c.get("/api/template/library").status_code == 200
    default_id = c.get("/api/template/library").json()["active_id"]

    def stub_run_build(**_kwargs):
        return 1, "stub: subprocess skipped"

    monkeypatch.setattr(template_install, "_run_build", stub_run_build)
    second, profile = _resume_upload_with_profile()
    assert second != first
    res = c.post(
        "/api/template",
        data={"label": "Second", "profile": profile},
        files={
            "file": (
                "second.docx",
                second,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 200
    assert (templates / "original_export.docx").read_bytes() == second

    act = c.post(f"/api/template/library/{default_id}/activate")
    assert act.status_code == 200, act.text
    assert (templates / "original_export.docx").read_bytes() == first
    body = act.json()
    assert body["ok"] is True
    assert body["info"]["active_library_id"] == default_id
    assert body["info"]["active_label"] == "Default"


def test_api_reads_are_never_cached_by_the_browser(client, tmp_path, monkeypatch):
    """A cached GET kept the old "In use" badge until a hard refresh."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    payload = _minimal_docx_bytes()
    (templates / "original_export.docx").write_bytes(payload)
    (templates / "main_template.docx").write_bytes(payload)
    res = c.get("/api/template/library")
    assert res.headers["cache-control"] == "no-store"
    # Routes that choose their own caching keep it.
    assert c.get("/api/applications").headers["cache-control"] == "no-cache"


def test_starter_card_marks_the_copy_that_is_in_use(monkeypatch):
    """Two saved copies of one starter: the card follows the active copy, else the copy
    `install_default` would reactivate (the newest), never an arbitrary one."""
    from resume_tailor.document import default_templates

    name = default_templates.names()[0]
    sha = hashlib.sha256(default_templates.build(name)).hexdigest()
    metas = [{"id": "newer", "sha256": sha}, {"id": "older", "sha256": sha}]
    monkeypatch.setattr(template_library_store, "_iter_library_metas", lambda: metas)
    monkeypatch.setattr(template_library_store, "_library_active_meta", lambda: ("newer", "x"))
    card = next(t for t in template_defaults.list_defaults().templates if t.name == name)
    assert (card.library_id, card.is_active) == ("newer", True)
    monkeypatch.setattr(template_library_store, "_library_active_meta", lambda: ("older", "x"))
    card = next(t for t in template_defaults.list_defaults().templates if t.name == name)
    assert (card.library_id, card.is_active) == ("older", True)
    monkeypatch.setattr(template_library_store, "_library_active_meta", lambda: (None, None))
    card = next(t for t in template_defaults.list_defaults().templates if t.name == name)
    assert (card.library_id, card.is_active) == ("newer", False)


def test_rename_library_rejects_duplicate_label(client, tmp_path, monkeypatch):
    """PATCH rename fails when the new label collides case-insensitively."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    tagged = templates / "main_template.docx"
    payload = _minimal_docx_bytes()
    (templates / "original_export.docx").write_bytes(payload)
    tagged.write_bytes(payload)
    c.get("/api/template/library")

    def stub_run_build(**_kwargs):
        return 1, "stub: subprocess skipped"

    monkeypatch.setattr(template_install, "_run_build", stub_run_build)
    upload, profile = _resume_upload_with_profile()
    c.post(
        "/api/template",
        data={"label": "Alpha", "profile": profile},
        files={
            "file": (
                "a.docx",
                upload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    lib = c.get("/api/template/library").json()
    default = next(e for e in lib["entries"] if e["label"] == "Default")
    res = c.patch(
        f"/api/template/library/{default['id']}",
        json={"label": "alpha"},
    )
    assert res.status_code == 400
    assert "already exists" in res.json()["detail"].lower()


def test_delete_library_refuses_active(client, tmp_path, monkeypatch):
    """DELETE on the active entry returns 400; non-active deletes succeed."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    tagged = templates / "main_template.docx"
    payload = _minimal_docx_bytes()
    (templates / "original_export.docx").write_bytes(payload)
    tagged.write_bytes(payload)
    c.get("/api/template/library")

    def stub_run_build(**_kwargs):
        return 1, "stub: subprocess skipped"

    monkeypatch.setattr(template_install, "_run_build", stub_run_build)
    upload, profile = _resume_upload_with_profile()
    c.post(
        "/api/template",
        data={"label": "Spare", "profile": profile},
        files={
            "file": (
                "s.docx",
                upload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    lib = c.get("/api/template/library").json()
    active = next(e for e in lib["entries"] if e["is_active"])
    other = next(e for e in lib["entries"] if not e["is_active"])

    bad = c.delete(f"/api/template/library/{active['id']}")
    assert bad.status_code == 400
    assert "active" in bad.json()["detail"].lower()

    ok = c.delete(f"/api/template/library/{other['id']}")
    assert ok.status_code == 200
    labels = {e["label"] for e in ok.json()["entries"]}
    assert other["label"] not in labels
    assert active["label"] in labels


def test_library_cap_refuses_twenty_first(client, tmp_path, monkeypatch):
    """Installing when the library already has 20 entries returns 400."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    tagged = templates / "main_template.docx"
    payload = _minimal_docx_bytes()
    (templates / "original_export.docx").write_bytes(payload)
    tagged.write_bytes(payload)

    # Fill the library with synthetic entries (no install needed).
    monkeypatch.setattr(template_ops, "_LIBRARY_MAX_ENTRIES", 2)
    c.get("/api/template/library")  # seeds Default (1)

    def stub_run_build(**_kwargs):
        return 1, "stub: subprocess skipped"

    monkeypatch.setattr(template_install, "_run_build", stub_run_build)
    upload, profile = _resume_upload_with_profile()
    first = c.post(
        "/api/template",
        data={"label": "Two", "profile": profile},
        files={
            "file": (
                "t.docx",
                upload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert first.status_code == 200, first.text
    assert len(c.get("/api/template/library").json()["entries"]) == 2

    blocked = c.post(
        "/api/template",
        data={"label": "Three", "profile": profile},
        files={
            "file": (
                "u.docx",
                upload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert blocked.status_code == 400
    assert "full" in blocked.json()["detail"].lower()


def test_library_thumbnail_route(client, tmp_path, monkeypatch):
    """GET /api/template/library/{id}/thumb.png renders the baseline; unknown ids 404."""
    from pypdf import PdfWriter

    from resume_tailor.document import thumbnails

    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    payload = _minimal_docx_bytes()
    (templates / "original_export.docx").write_bytes(payload)
    (templates / "main_template.docx").write_bytes(payload)

    def fake_convert(docx_path, pdf_path, **_):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as fh:
            writer.write(fh)
        return pdf_path

    monkeypatch.setattr(thumbnails.convert, "convert", fake_convert)
    entry_id = c.get("/api/template/library").json()["entries"][0]["id"]
    res = c.get(f"/api/template/library/{entry_id}/thumb.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG")
    assert c.get("/api/template/library/nope/thumb.png").status_code == 404
    assert c.get("/api/template/library/..%2F..%2Fx/thumb.png").status_code == 404

    def no_engine(*_a, **_k):
        raise RuntimeError("No PDF engine")

    monkeypatch.setattr(thumbnails.convert, "convert", no_engine)
    thumb = next(templates.rglob("thumb.png"))
    thumb.unlink()
    assert c.get(f"/api/template/library/{entry_id}/thumb.png").status_code == 503


def test_calibrate_route_reports_result_and_refuses_while_busy(client, tmp_path, monkeypatch):
    """POST /api/template/calibrate runs calibration; failures are ok=False, never 500."""
    from resume_tailor.document.calibrate import CalibrationResult

    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    assert c.post("/api/template/calibrate").status_code == 404  # no template yet

    (templates / "main_template.docx").write_bytes(_minimal_docx_bytes())
    calls = []

    def fake_run(*, verify_anchors=True, rebaseline=False):
        calls.append(verify_anchors)
        return CalibrationResult(
            chars_per_line=95, lines_per_page=50, path=tmp_path / "cal.json",
            log="CHARS_PER_LINE = 95", warnings=["anchor drift"],
        )

    monkeypatch.setattr(calibrate, "run", fake_run)
    monkeypatch.setattr(config, "reload_calibration", lambda: (95, 50, "test"))
    res = c.post("/api/template/calibrate")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["warnings"] == ["anchor drift"] and calls == [True]
    assert "calibrated_at" in body["calibration"]

    def boom(**_):
        raise RuntimeError("No PDF engine found")

    monkeypatch.setattr(calibrate, "run", boom)
    body = c.post("/api/template/calibrate").json()
    assert body["ok"] is False and "No PDF engine" in body["log"]

    from resume_tailor.web import routes

    monkeypatch.setattr(routes.template.get_queue(), "busy", lambda: True)
    assert c.post("/api/template/calibrate").status_code == 409


def test_default_templates_install_and_reuse_the_library_entry(client, tmp_path, monkeypatch):
    """POST /api/template/defaults/{name}/install builds the design like an upload."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    monkeypatch.setattr(template_install, "_run_build", lambda **_k: (1, "stub: in-process"))

    listed = c.get("/api/template/defaults").json()["templates"]
    assert [t["name"] for t in listed] == ["classic", "compact", "business"]
    assert all(t["library_id"] is None for t in listed)
    assert next(t for t in listed if t["name"] == "business")["education_first"] is True

    res = c.post("/api/template/defaults/classic/install")
    assert res.status_code == 200, res.text
    assert res.json()["info"]["active_label"] == "Classic"
    assert (templates / "main_template.docx").exists()
    assert (templates / "original_export.docx").read_bytes() == default_templates.build(
        "classic"
    )
    classic = next(
        t for t in c.get("/api/template/defaults").json()["templates"] if t["name"] == "classic"
    )
    assert classic["is_active"] and classic["library_id"]

    assert c.post("/api/template/defaults/compact/install").status_code == 200
    # Installing a design again activates its saved entry instead of adding a copy.
    again = c.post("/api/template/defaults/classic/install")
    assert again.status_code == 200, again.text
    assert again.json()["info"]["active_library_id"] == classic["library_id"]
    labels = [e["label"] for e in c.get("/api/template/library").json()["entries"]]
    assert sorted(labels) == ["Classic", "Compact"]

    assert c.post("/api/template/defaults/fancy/install").status_code == 404


def test_default_template_label_avoids_a_taken_one(client, tmp_path, monkeypatch):
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)
    monkeypatch.setattr(template_install, "_run_build", lambda **_k: (1, "stub: in-process"))
    monkeypatch.setattr(template_library_store, "_label_taken", lambda label, **_k: label == "Business")
    res = c.post("/api/template/defaults/business/install")
    assert res.status_code == 200, res.text
    assert res.json()["info"]["active_label"] == "Business (2)"


def test_default_template_thumbnail_route(client, tmp_path, monkeypatch):
    from pypdf import PdfWriter

    from resume_tailor.document import thumbnails

    c, _ = client

    def fake_convert(docx_path, pdf_path, **_):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as fh:
            writer.write(fh)
        return pdf_path

    monkeypatch.setattr(thumbnails.convert, "convert", fake_convert)
    res = c.get("/api/template/defaults/compact/thumb.png")
    assert res.status_code == 200
    assert res.content.startswith(b"\x89PNG")
    assert c.get("/api/template/defaults/nope/thumb.png").status_code == 404


def test_default_template_install_refused_while_tailoring(client):
    c, q = client
    q.busy = lambda: True  # type: ignore[method-assign]
    assert c.post("/api/template/defaults/classic/install").status_code == 409
