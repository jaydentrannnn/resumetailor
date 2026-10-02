"""Template tab: upload, preview, analyze, remap, install."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from resume_tailor import config
from resume_tailor.document import render, template_build, template_profile
from resume_tailor.web import job_types, template_info, template_install, template_uploads
from resume_tailor.web.schemas import JobSettings
from tests.web.helpers import (
    _DOCX_MIME,
    _minimal_docx_bytes,
    _point_templates_at,
    _resume_docx_bytes,
    _resume_upload_with_profile,
)


def test_get_template_returns_metadata(client, tmp_path, monkeypatch):
    """GET /api/template reports existence and calibration for redirected template paths."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    (templates / "original_export.docx").write_bytes(_minimal_docx_bytes())
    (templates / "main_template.docx").write_bytes(_minimal_docx_bytes())

    res = c.get("/api/template")
    assert res.status_code == 200
    body = res.json()
    assert body["baseline"]["exists"] is True
    assert body["tagged"]["exists"] is True
    assert body["baseline"]["size_bytes"] > 0
    assert "calibration" in body
    assert "stale" in body["calibration"]
    assert isinstance(body["experience_entries"], int)
    assert isinstance(body["bullets"], int)


def test_upload_template_rejects_non_docx(client, tmp_path, monkeypatch):
    """POST /api/template with a .txt leaves the baseline untouched and returns 400.

    `profile` is required now (Phase 7 retired the legacy no-profile path), but the
    extension check runs before the profile is even parsed, so any well-formed profile
    string reaches the assertion this test actually cares about.
    """
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    baseline = templates / "original_export.docx"
    original = _minimal_docx_bytes()
    baseline.write_bytes(original)
    _, profile = _resume_upload_with_profile()

    res = c.post(
        "/api/template",
        data={"profile": profile},
        files={"file": ("resume.txt", b"not a docx", "text/plain")},
    )
    assert res.status_code == 400
    assert "docx" in res.json()["detail"].lower()
    assert baseline.read_bytes() == original


def test_upload_template_rejects_when_queue_busy(client, tmp_path, monkeypatch):
    """POST /api/template returns 409 while a job is queued or running.

    The busy check runs before the profile is parsed, so any non-empty string for
    `profile` (required by FastAPI's own Form validation) reaches it.
    """
    c, q = client
    _point_templates_at(tmp_path, monkeypatch)

    # Insert a "running" job directly rather than through submit(), which starts the
    # real background worker regardless of reassigning `job.status` afterward — the
    # worker would independently run the real (unstubbed) pipeline against
    # "placeholder jd", reaching the network in the background for the rest of the
    # suite. See test_activate_workspace_409_when_queue_busy for the same pattern.
    job = job_types.Job(
        job_id="fake-busy", jd_text="placeholder jd", settings=JobSettings(), status="running"
    )
    q._jobs[job.job_id] = job

    res = c.post(
        "/api/template",
        data={"profile": "{}"},
        files={
            "file": (
                "resume.docx",
                _minimal_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 409
    assert "progress" in res.json()["detail"].lower() or "job" in res.json()["detail"].lower()


def test_upload_template_backs_up_and_rebuilds(client, tmp_path, monkeypatch):
    """Successful upload writes a timestamped backup and installs a real, verified build.

    `_run_build` is stubbed to skip the subprocess spawn; since it doesn't write the
    staged output path, `_install_with_profile`'s in-process fallback does the actual
    build, so this still exercises a real, verified template rather than a placeholder.
    """
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    baseline = templates / "original_export.docx"
    old_bytes = _minimal_docx_bytes()
    baseline.write_bytes(old_bytes)

    def stub_run_build(**_kwargs):
        return 1, "stub: subprocess skipped"

    monkeypatch.setattr(template_install, "_run_build", stub_run_build)

    new_bytes, profile = _resume_upload_with_profile()

    res = c.post(
        "/api/template",
        data={"profile": profile},
        files={
            "file": (
                "resume.docx",
                new_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert "in-process profile build ok" in body["log"].lower()
    backups = list((templates / "backups").glob("original_export.*.docx"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == old_bytes
    assert baseline.read_bytes() == new_bytes


def test_upload_template_restores_baseline_on_build_failure(client, tmp_path, monkeypatch):
    """A build that fails during staging (subprocess and in-process fallback both fail)
    never touches the live baseline and returns 422.

    Unlike the retired legacy path (which wrote the new baseline before building, so a
    failure needed an explicit restore), the profile path stages everything in a temp
    directory first — a staging failure means the live files were simply never written,
    which is a stronger guarantee than "restored to their old bytes".
    """
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    baseline = templates / "original_export.docx"
    old_bytes = _minimal_docx_bytes()
    baseline.write_bytes(old_bytes)

    def failing_run_build(**_kwargs):
        return 1, "ERROR: could not find section heading(s): WORK EXPERIENCES.\n"

    def failing_build_from_profile(src, dst, profile):
        raise RuntimeError("could not find section heading(s): WORK EXPERIENCES.")

    monkeypatch.setattr(template_install, "_run_build", failing_run_build)
    monkeypatch.setattr(
        template_build, "build_from_profile", failing_build_from_profile
    )

    upload, profile = _resume_upload_with_profile()
    res = c.post(
        "/api/template",
        data={"profile": profile},
        files={
            "file": (
                "resume.docx",
                upload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, dict)
    assert "log" in detail
    assert "WORK EXPERIENCES" in detail["log"]
    assert baseline.read_bytes() == old_bytes


def test_template_preview_uses_stubbed_render(client, tmp_path, monkeypatch):
    """GET /api/template/preview.pdf serves a PDF produced via the render seam (no Word)."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    (templates / "main_template.docx").write_bytes(_minimal_docx_bytes())
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir(exist_ok=True)

    def fake_render(resume, *, out, **_kwargs):
        """Write a placeholder .docx where the preview would land."""
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-docx")
        return out

    def fake_to_pdf(docx_path, pdf_path=None, **_kwargs):
        """Write a minimal PDF-like payload without calling Word/LibreOffice."""
        target = pdf_path or docx_path.with_suffix(".pdf")
        # Minimal PDF header so FileResponse has something to stream.
        target.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer\n%%EOF\n")
        return target

    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(render, "to_pdf", fake_to_pdf)

    res = c.get("/api/template/preview.pdf")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content.startswith(b"%PDF")


def test_preview_cache_invalidates_when_master_resume_changes(client, tmp_path, monkeypatch):
    """Editing the master resume re-renders the template preview.

    Regression: `ensure_preview` compared the cached PDF's mtime against the *tagged
    template* only. Since the preview renders the resume through that template, a
    resume edit left the template untouched, the cache looked fresh, and the Template
    tab served the pre-edit PDF forever — the "Refresh doesn't show my changes" report.
    """
    import os

    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    (templates / "main_template.docx").write_bytes(_minimal_docx_bytes())
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "preview-out")
    resume_path = tmp_path / "master_resume.json"
    resume_path.write_text(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)

    renders: list[int] = []

    def fake_render(resume, *, out, **_kwargs):
        renders.append(1)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-docx")
        return out

    def fake_to_pdf(docx_path, pdf_path=None, **_kwargs):
        target = pdf_path or docx_path.with_suffix(".pdf")
        target.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return target

    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(render, "to_pdf", fake_to_pdf)

    assert c.get("/api/template/preview.pdf").status_code == 200
    assert len(renders) == 1
    # Unchanged inputs must still hit the cache — this is a real render each time.
    assert c.get("/api/template/preview.pdf").status_code == 200
    assert len(renders) == 1

    _, pdf_path = template_info._preview_paths()
    future = pdf_path.stat().st_mtime + 10
    resume_path.write_text(resume_path.read_text(encoding="utf-8"), encoding="utf-8")
    os.utime(resume_path, (future, future))

    assert c.get("/api/template/preview.pdf").status_code == 200
    assert len(renders) == 2, "a master-resume edit must invalidate the preview cache"


def test_analyze_template_returns_structured_report(client, tmp_path, monkeypatch):
    """POST /api/template/analyze does not write under templates/ and returns issues."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    before = list(templates.iterdir()) if templates.exists() else []

    res = c.post(
        "/api/template/analyze",
        files={
            "file": (
                "resume.docx",
                _minimal_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert "source_sha256" in body
    assert "issues" in body
    assert "paragraphs" in body
    assert body["ready"] is False
    after = list(templates.iterdir()) if templates.exists() else []
    assert after == before


def test_analyze_template_exposes_field_candidates(client, tmp_path, monkeypatch):
    """POST /api/template/analyze surfaces per-field spans, not just section summaries
    — `field_candidates` was computed by `template_analyze` all along but dropped at
    the API boundary; the wizard's confirm step needs the per-field rows to show which
    specific span (company/dates/…) it is about to install."""
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)

    res = c.post(
        "/api/template/analyze",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is True
    assert body["field_candidates"], "expected at least one field candidate"
    fields = {c["field"] for c in body["field_candidates"]}
    assert "dates" in fields or "date" in fields
    sample = body["field_candidates"][0]
    assert {
        "field",
        "paragraph_id",
        "start",
        "end",
        "confidence",
        "preview",
        "section_heading_paragraph_id",
    } <= sample.keys()
    assert sample["section_heading_paragraph_id"] is not None


def test_remap_template_forces_a_heading_kind(client, tmp_path, monkeypatch):
    """POST /api/template/analyze/remap re-runs analysis with a user-confirmed kind for
    one heading, bypassing the heuristic entirely for that paragraph — a real server
    round trip so the wizard's remap reflects the analyzer's own downstream logic."""
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)

    analyzed = c.post(
        "/api/template/analyze",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    ).json()
    sha = analyzed["source_sha256"]
    skills_heading = next(s for s in analyzed["sections"] if s["key"] == "skills")

    remapped = c.post(
        "/api/template/analyze/remap",
        json={
            "source_sha256": sha,
            "overrides": {str(skills_heading["heading_paragraph_id"]): "list"},
        },
    )
    assert remapped.status_code == 200
    body = remapped.json()
    keys = {s["key"] for s in body["sections"]}
    assert "skills" not in keys
    assert "list" in keys


def test_remap_template_rejects_unknown_heading_kind(client):
    """A forced kind outside the five the analyzer understands is a 422 at the schema,
    not an arbitrary string flowing into `SectionCandidate.key`."""
    c, _ = client
    res = c.post(
        "/api/template/analyze/remap",
        json={"source_sha256": "0" * 64, "overrides": {"5": "bogus"}},
    )
    assert res.status_code == 422


def test_remap_template_unknown_sha_is_400(client, tmp_path, monkeypatch):
    """Remapping a sha that was never analyzed (or whose cache expired) is a 400 asking
    the wizard to start over, not a 404/500."""
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)

    res = c.post(
        "/api/template/analyze/remap",
        json={"source_sha256": "0" * 64, "overrides": {}},
    )
    assert res.status_code == 400


@pytest.mark.parametrize(
    "sha",
    [
        "../../../../../../etc/passwd",
        "..\\..\\..\\windows\\win.ini",
        "0" * 63,  # one short of a real digest
        "0" * 65,  # one over
        # Uppercase hex is not what hexdigest() ever produces. Digits alone don't
        # change under .upper(), unlike a real sha which mixes in a-f — this has to
        # be spelled with a letter for the case to mean anything.
        ("ab" * 32).upper(),
        "not-hex-at-all-000000000000000000000000000000000000000000000000",
    ],
)
def test_remap_template_rejects_non_hex_sha_before_touching_disk(
    client, tmp_path, monkeypatch, sha
):
    """`source_sha256` is interpolated straight into a filesystem path in
    `template_uploads._load_cached_upload` (`_upload_cache_dir() / f"{sha}.docx"`), and
    arrives in a JSON body rather than a path param, so nothing else stops a
    traversal value from reaching it. The schema-level pattern constraint
    (`web/schemas.py`'s `_SHA256_HEX_PATTERN`) must reject it with FastAPI's own 422,
    before `template_uploads.remap_upload` — and therefore any path/file access — ever
    runs. Covers the traversal case the existing `"0" * 64` test above cannot: that
    value is well-formed hex, so it only ever probes the "valid shape, unknown upload"
    400 path, never the "malformed shape" 422 path."""
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)

    res = c.post(
        "/api/template/analyze/remap",
        json={"source_sha256": sha, "overrides": {}},
    )
    assert res.status_code == 422

    res2 = c.post(
        "/api/template/preview/source",
        json={"source_sha256": sha, "overrides": {}},
    )
    assert res2.status_code == 422

    res3 = c.post(
        "/api/template/preview/draft",
        json={"source_sha256": sha, "profile": {}},
    )
    assert res3.status_code == 422


def test_preview_source_returns_pdf(client, tmp_path, monkeypatch):
    """POST /api/template/preview/source serves the uploaded (not-yet-installed)
    baseline as a PDF for the wizard's side-by-side comparison, via the same
    render/convert seam the other preview endpoint stubs."""
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)

    def fake_to_pdf(docx_path, pdf_path=None, **_kwargs):
        target = pdf_path or docx_path.with_suffix(".pdf")
        target.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return target

    monkeypatch.setattr(render, "to_pdf", fake_to_pdf)

    analyzed = c.post(
        "/api/template/analyze",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    ).json()

    res = c.post(
        "/api/template/preview/source",
        json={"source_sha256": analyzed["source_sha256"], "overrides": {}},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content.startswith(b"%PDF")


def test_preview_draft_returns_pdf(client, tmp_path, monkeypatch):
    """POST /api/template/preview/draft builds the staged profile into a temp tagged
    template and renders the master resume through it, without touching the live
    template slot."""
    c, _ = client
    templates = _point_templates_at(tmp_path, monkeypatch)
    before = list(templates.iterdir()) if templates.exists() else []

    def fake_to_pdf(docx_path, pdf_path=None, **_kwargs):
        target = pdf_path or docx_path.with_suffix(".pdf")
        target.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return target

    monkeypatch.setattr(render, "to_pdf", fake_to_pdf)

    analyzed = c.post(
        "/api/template/analyze",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    ).json()
    assert analyzed["suggested_profile"], analyzed["issues"]

    res = c.post(
        "/api/template/preview/draft",
        json={
            "source_sha256": analyzed["source_sha256"],
            "profile": analyzed["suggested_profile"],
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content.startswith(b"%PDF")
    # Never touches the live template slot.
    after = list(templates.iterdir()) if templates.exists() else []
    assert after == before


def test_preview_draft_reports_a_bad_mapping_as_422_not_503(client, tmp_path, monkeypatch):
    """`template_build.build_from_profile` raises plain `RuntimeError` for every
    mapping problem (a missing field, a paragraph id out of range, …) —
    indistinguishable, to a bare `except RuntimeError`, from `render.to_pdf` genuinely
    having no PDF backend available. `template_preview.preview_draft` re-raises the build
    failure as `TemplateBuildError`, and the route must catch that ahead of its
    `except RuntimeError` branch (it's a subclass), so a bad *mapping* reads as
    "fix your profile" (422, with the build log) rather than "install LibreOffice"
    (503) — that 503 branch stays reserved for `render.to_pdf` failing for real,
    covered separately below.
    """
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)

    def failing_build(source, output, profile):
        raise RuntimeError("Experience mapping is missing a job title.")

    monkeypatch.setattr(template_build, "build_from_profile", failing_build)

    analyzed = c.post(
        "/api/template/analyze",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    ).json()
    assert analyzed["suggested_profile"], analyzed["issues"]

    res = c.post(
        "/api/template/preview/draft",
        json={
            "source_sha256": analyzed["source_sha256"],
            "profile": analyzed["suggested_profile"],
        },
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "missing a job title" in detail["message"]
    assert "log" in detail


def test_preview_draft_reports_no_pdf_backend_as_503(client, tmp_path, monkeypatch):
    """The build succeeds; `render.to_pdf` is what has no backend available here —
    this is the genuine 503 case `preview_draft_template`'s `except RuntimeError`
    branch exists for, kept passing alongside the 422 case above to prove the route
    still tells the two apart."""
    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)

    def failing_to_pdf(docx_path, pdf_path=None, **_kwargs):
        raise RuntimeError("No PDF backend is configured.")

    monkeypatch.setattr(render, "to_pdf", failing_to_pdf)

    analyzed = c.post(
        "/api/template/analyze",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    ).json()
    assert analyzed["suggested_profile"], analyzed["issues"]

    res = c.post(
        "/api/template/preview/draft",
        json={
            "source_sha256": analyzed["source_sha256"],
            "profile": analyzed["suggested_profile"],
        },
    )
    assert res.status_code == 503


def test_install_clears_the_upload_cache(client, tmp_path, monkeypatch):
    """A successful install clears the wizard's cached upload — remap/preview against
    that sha afterward must 400, not silently keep serving a now-stale draft."""
    from resume_tailor.document import template_build as tb_mod

    c, _ = client
    _point_templates_at(tmp_path, monkeypatch)

    def fake_build(*, source=None, output=None, profile_path=None, legacy=False):
        out = Path(output) if output else config.DEFAULT_TEMPLATE_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        loaded_profile = template_profile.load_profile(Path(profile_path))
        tb_mod.build_from_profile(Path(source), out, loaded_profile)
        return 0, "stub build ok"

    monkeypatch.setattr(template_install, "_run_build", fake_build)

    upload = _resume_docx_bytes()
    analyzed = c.post(
        "/api/template/analyze", files={"file": ("resume.docx", upload, _DOCX_MIME)}
    ).json()
    sha = analyzed["source_sha256"]

    install = c.post(
        "/api/template",
        data={"profile": json.dumps(analyzed["suggested_profile"])},
        files={"file": ("resume.docx", upload, _DOCX_MIME)},
    )
    assert install.status_code == 200, install.json()

    res = c.post("/api/template/analyze/remap", json={"source_sha256": sha, "overrides": {}})
    assert res.status_code == 400


def test_prune_upload_cache_deletes_preview_pdfs_too(client, tmp_path, monkeypatch):
    """`_prune_upload_cache` used to glob only `*.docx`; `preview_source`/`preview_draft`
    also cache rendered `{sha}.source.pdf`/`{sha}.draft.pdf` alongside the upload in the
    same directory, and a `*.docx`-only glob left those — the largest, most PII-dense
    artifacts in that directory — never aged out. Exercised directly against
    `template_ops` rather than through the HTTP routes: this is a pure filesystem-age
    behavior with nothing route-specific about it."""
    _c, _q = client  # ensures config.OUTPUT_DIR is already redirected under tmp_path
    _point_templates_at(tmp_path, monkeypatch)

    cache_dir = template_uploads._upload_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    old_docx = cache_dir / "aaaa.docx"
    old_source_pdf = cache_dir / "aaaa.source.pdf"
    old_draft_pdf = cache_dir / "aaaa.draft.pdf"
    fresh_docx = cache_dir / "bbbb.docx"
    for f in (old_docx, old_source_pdf, old_draft_pdf, fresh_docx):
        f.write_bytes(b"x")

    import os

    day_and_a_half_ago = time.time() - 1.5 * 24 * 3600
    for f in (old_docx, old_source_pdf, old_draft_pdf):
        os.utime(f, (day_and_a_half_ago, day_and_a_half_ago))

    template_uploads._prune_upload_cache()

    assert not old_docx.exists()
    assert not old_source_pdf.exists(), "the .docx-only glob left this PDF behind"
    assert not old_draft_pdf.exists(), "the .docx-only glob left this PDF behind"
    assert fresh_docx.exists(), "prune must not delete anything under the age cutoff"
