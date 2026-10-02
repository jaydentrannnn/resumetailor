from resume_tailor import config
from resume_tailor.document import calibrate, calibration_cache
from resume_tailor.web import template_preview


def test_pdf_conversion_does_not_hold_the_template_switch_lock(client, tmp_path, monkeypatch):
    from resume_tailor.web import template_ops

    template = tmp_path / "tagged.docx"
    template.write_bytes(b"template A")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", template)
    monkeypatch.setattr(
        template_preview.render, "render", lambda resume, *, out: out.write_bytes(b"template A")
    )

    def pdf(source, target):
        assert template_ops.LOCK.acquire(blocking=False)
        try:
            template.write_bytes(b"template B")
        finally:
            template_ops.LOCK.release()
        target.write_bytes(source.read_bytes())

    monkeypatch.setattr(template_preview.render, "to_pdf", pdf)
    revision = template_preview.preview_revision()
    assert template_preview.ensure_preview(revision).read_bytes() == b"template A"
    assert template_preview.preview_revision() != revision


def test_revision_preview_is_cached_and_stale_revision_never_renders_new_template(
    client, tmp_path, monkeypatch
):
    c, _ = client
    template = tmp_path / "tagged.docx"
    template.write_bytes(b"template A")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", template)
    renders = []

    def render(resume, *, out, **kwargs):
        renders.append(template.read_bytes())
        out.write_bytes(template.read_bytes())

    def pdf(source, target):
        target.write_bytes(source.read_bytes())

    monkeypatch.setattr(template_preview.render, "render", render)
    monkeypatch.setattr(template_preview.render, "to_pdf", pdf)
    a = template_preview.preview_revision()
    assert c.get(f"/api/template/preview.pdf?revision={a}").content == b"template A"
    template.write_bytes(b"template B")
    b = template_preview.preview_revision()
    assert a != b
    assert c.get(f"/api/template/preview.pdf?revision={b}").content == b"template B"
    assert c.get(f"/api/template/preview.pdf?revision={a}").content == b"template A"
    assert c.get(f"/api/template/preview.pdf?revision={'0' * 64}").status_code == 409
    assert renders == [b"template A", b"template B"]


def test_calibration_restores_only_matching_inputs(tmp_path, monkeypatch):
    template = tmp_path / "main_template.docx"
    master = tmp_path / "master_resume.json"
    template.write_bytes(b"template A")
    master.write_bytes(b"resume A")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", template)
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", master)
    calibrate.write_calibration(99, 49)
    template.write_bytes(b"template B")
    calibration_cache.activate()
    assert config.CALIBRATION_SOURCE == "fallback"
    template.write_bytes(b"template A")
    calibration_cache.activate()
    assert config.CHARS_PER_LINE == 99
    assert config.LINES_PER_PAGE == 49
    master.write_bytes(b"resume B")
    calibration_cache.activate()
    assert config.CALIBRATION_SOURCE == "fallback"


def test_template_snapshot_has_one_active_identity(client):
    c, _ = client
    state = c.get("/api/template/state")
    assert state.status_code == 200
    body = state.json()
    assert body["info"]["active_library_id"] == body["library"]["active_id"]
    assert len(body["preview_revision"]) == 64


def test_calibration_loader_uses_requested_workspace_inputs(tmp_path):
    import json

    paths = {
        name: tmp_path / name
        for name in (
            "DEFAULT_TEMPLATE_PATH",
            "TEMPLATE_PROFILE_PATH",
            "MASTER_RESUME_PATH",
        )
    }
    for path in paths.values():
        path.write_bytes(b"another workspace")
    digest = calibration_cache.input_digest(paths=paths, backend="word")
    (tmp_path / "word.json").write_text(
        json.dumps(
            {
                "backend": "word",
                "chars_per_line": 99,
                "lines_per_page": 49,
                "input_digest": digest,
            }
        ),
        encoding="utf-8",
    )
    assert config._load_calibration("word", tmp_path, paths=paths) == (
        99,
        49,
        str(tmp_path / "word.json"),
        None,
    )
    paths["MASTER_RESUME_PATH"].write_bytes(b"changed")
    assert config._load_calibration("word", tmp_path, paths=paths)[2] == "fallback"
