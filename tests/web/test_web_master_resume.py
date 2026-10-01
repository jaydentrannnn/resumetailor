"""Master-resume read/write, import and merge routes."""

from __future__ import annotations

import json

from resume_tailor import config
from resume_tailor.content.data import load
from tests.web.helpers import (
    _DOCX_MIME,
    _FakeSDKError,
    _resume_docx_bytes,
    _resume_docx_bytes_with_an_untaggable_bullet,
)


def test_master_resume_validate_rejects_bad_payload(client):
    """POST /api/master-resume/validate returns field errors, not a 500."""
    c, _ = client
    res = c.post("/api/master-resume/validate", json={"contact": {"name": "x"}})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["errors"]


def test_master_resume_round_trip(client, tmp_path, monkeypatch):
    """PUT saves a validated resume and keeps a backup of the previous file."""
    c, _ = client
    resume = load()
    path = tmp_path / "master_resume.json"
    path.write_text(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    payload = resume.model_dump(by_alias=True)
    payload["contact"]["name"] = "Test User"

    res = c.put("/api/master-resume", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["summary"]["name"] == "Test User"
    assert list(tmp_path.glob("master_resume.*.bak.json")), "expected a timestamped backup"

    got = c.get("/api/master-resume")
    assert got.status_code == 200
    assert got.json()["contact"]["name"] == "Test User"


def test_master_resume_put_accepts_legacy_shaped_payload(client, tmp_path, monkeypatch):
    """PUT still accepts the pre-`sections` wire shape — anything that never migrated to
    sending `sections` (an old script, a saved request) keeps working; the model's
    before-validator folds it in unchanged."""
    c, _ = client
    resume = load()
    path = tmp_path / "master_resume.json"
    path.write_text(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    before = len(resume.all_bullets())
    # Pre-`sections` wire shape: top-level lists instead of `sections`. Hand-built
    # here (rather than via a `to_legacy_dict` helper, since none exists any more —
    # accepting this shape is `MasterResume._migrate_legacy_sections`'s job, not a
    # dedicated function's) purely to exercise that before-validator through the API.
    payload = {
        "contact": resume.contact.model_dump(by_alias=True),
        "education": [e.model_dump(by_alias=True) for e in resume.education],
        "experience": [e.model_dump(by_alias=True) for e in resume.experience],
        "projects": [e.model_dump(by_alias=True) for e in resume.projects],
        "skills": [e.model_dump(by_alias=True) for e in resume.skills],
        "tag_vocabulary": resume.tag_vocabulary,
    }
    payload["experience"].append(
        {
            "company": "Editor Test Co",
            "title": "Software Engineer",
            "location": "Remote",
            "start": "2024-01",
            "end": "present",
            "bullets": [
                {
                    "id": "edittest_b1",
                    "text": "Shipped a feature with Python and FastAPI.",
                    "tags": ["Python", "FastAPI"],
                    "metric": False,
                }
            ],
        }
    )

    res = c.put("/api/master-resume", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["summary"]["bullets"] == before + 1
    assert body["summary"]["experience"] == len(resume.experience) + 1


def test_master_resume_get_put_round_trips_sections_natively(client, tmp_path, monkeypatch):
    """GET returns `sections` (no flattened `experience`/`projects` keys); appending an
    entry to a section there and PUTting it back grows that section, and a follow-up GET
    reflects it — the editor's actual read-edit-write flow."""
    c, _ = client
    path = tmp_path / "master_resume.json"
    path.write_text(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    got = c.get("/api/master-resume")
    assert got.status_code == 200
    payload = got.json()
    assert "sections" in payload
    assert "experience" not in payload

    exp_section = next(s for s in payload["sections"] if s["kind"] == "experience")
    exp_section["entries"].append(
        {
            "company": "Editor Test Co",
            "title": "Software Engineer",
            "location": "Remote",
            "start": "2024-01",
            "end": "present",
            "bullets": [
                {
                    "id": "edittest_b2",
                    "text": "Shipped a feature with Python and FastAPI.",
                    "tags": ["Python", "FastAPI"],
                    "metric": False,
                }
            ],
        }
    )

    res = c.put("/api/master-resume", json=payload)
    assert res.status_code == 200
    assert res.json()["ok"] is True

    got2 = c.get("/api/master-resume").json()
    exp_section2 = next(s for s in got2["sections"] if s["kind"] == "experience")
    last = exp_section2["entries"][-1]
    assert last["company"] == "Editor Test Co"
    assert last["bullets"][0]["id"] == "edittest_b2"
    # Tags come back canonicalised the way data.Bullet._normalise_tags stores them.
    assert "python" in [t.lower() for t in last["bullets"][0]["tags"]]


def test_import_master_resume_returns_a_draft_without_writing(client, tmp_path, monkeypatch):
    """POST /api/master-resume/import parses content into a draft and writes nothing —
    the master resume on disk (and its mtime) must be untouched."""
    c, _ = client
    path = tmp_path / "master_resume.json"
    path.write_text(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
    before = path.read_text(encoding="utf-8")
    before_mtime = path.stat().st_mtime

    res = c.post(
        "/api/master-resume/import",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["resume"]["contact"]["name"] == "Ada Lovelace"
    assert any(s["kind"] == "experience" for s in body["resume"]["sections"])
    assert "warnings" in body
    assert "untagged_bullet_count" in body

    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_mtime == before_mtime


def test_import_master_resume_rejects_a_non_docx(client):
    c, _ = client
    res = c.post(
        "/api/master-resume/import",
        files={"file": ("resume.txt", b"not a docx", "text/plain")},
    )
    assert res.status_code == 400


def test_import_master_resume_reads_a_pdf_without_writing(client):
    from tests.pdf_fixtures import single_column_resume

    c, _ = client
    before = config.MASTER_RESUME_PATH.read_text(encoding="utf-8")
    res = c.post(
        "/api/master-resume/import",
        files={"file": ("resume.pdf", single_column_resume(), "application/pdf")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["resume"]["contact"]["name"] == "Alex Doe"
    kinds = [s["kind"] for s in body["resume"]["sections"]]
    assert kinds[:3] == ["education", "experience", "project"]
    assert config.MASTER_RESUME_PATH.read_text(encoding="utf-8") == before


def test_import_master_resume_explains_an_image_only_pdf(client):
    from tests.pdf_fixtures import image_only_pdf

    c, _ = client
    res = c.post(
        "/api/master-resume/import",
        files={"file": ("scan.pdf", image_only_pdf(), "application/pdf")},
    )
    assert res.status_code == 400
    assert "no readable text" in res.json()["detail"]


def test_merge_master_resume_writes_and_backs_up(client):
    """POST /api/master-resume/merge actually persists — unlike /import — and reports
    the backup filename of the pre-merge content."""
    c, _ = client
    before = json.loads(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"))
    assert before["contact"]["name"] == "Jordan Rivera"

    imported = c.post(
        "/api/master-resume/import",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    ).json()

    res = c.post("/api/master-resume/merge", json=imported["resume"])
    assert res.status_code == 200
    body = res.json()
    assert body["resume"]["contact"]["name"] == "Ada Lovelace"  # incoming name overwrites
    assert "Analytical Engines" in body["added"]  # Ada's company, absent from Jordan's resume
    # Both fixtures happen to name their project "Note Engine" — a genuine match, updated in place.
    assert body["updated"] == ["Note Engine"]
    assert body["backup"] is not None

    backup_path = config.MASTER_RESUME_PATH.parent / body["backup"]
    assert backup_path.exists()
    assert json.loads(backup_path.read_text(encoding="utf-8")) == before

    on_disk = json.loads(config.MASTER_RESUME_PATH.read_text(encoding="utf-8"))
    assert on_disk["contact"]["name"] == "Ada Lovelace"
    # Jordan's original experience entry must still be present — merge, not replace.
    companies = {
        e["company"]
        for s in on_disk["sections"]
        if s["kind"] == "experience"
        for e in s["entries"]
    }
    assert "Example Corp" in companies  # Jordan's own entry, from synthetic_resume()
    assert "Analytical Engines" in companies  # Ada's newly-added entry

    get_after = c.get("/api/master-resume").json()
    assert get_after["contact"]["name"] == "Ada Lovelace"


def test_merge_master_resume_creates_a_file_when_none_exists(client, monkeypatch):
    """A workspace with no master resume yet merges against an empty one instead of
    raising — the same tolerance `import_master_resume` already applies."""
    c, _ = client
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", config.MASTER_RESUME_PATH.parent / "missing.json")
    assert not config.MASTER_RESUME_PATH.exists()

    imported = c.post(
        "/api/master-resume/import",
        files={"file": ("resume.docx", _resume_docx_bytes(), _DOCX_MIME)},
    ).json()

    res = c.post("/api/master-resume/merge", json=imported["resume"])
    assert res.status_code == 200
    body = res.json()
    assert body["backup"] is None  # nothing existed to back up
    assert config.MASTER_RESUME_PATH.exists()
    assert body["resume"]["contact"]["name"] == "Ada Lovelace"


def test_merge_master_resume_rejects_an_invalid_body(client):
    c, _ = client
    res = c.post("/api/master-resume/merge", json={"not": "a valid resume"})
    assert res.status_code == 400


def test_put_master_resume_rejects_an_invalid_body(client):
    """PUT must 400 on a rejected write, matching its sibling `/merge` route above —
    previously this returned 200 with `{"ok": false, "errors": [...]}`, so a caller
    checking only HTTP status (as `frontend/src/api.ts`'s generic `request()` helper
    does) would see the write as having succeeded."""
    c, _ = client
    res = c.put("/api/master-resume", json={"not": "a valid resume"})
    assert res.status_code == 400
    assert "detail" in res.json()


def test_import_master_resume_suggest_tags_fills_in_untagged_bullets(client, monkeypatch):
    """`suggest_tags=true` runs the opt-in LLM pass for whatever the deterministic
    seeding left untagged, and the response's untagged count drops to reflect it."""
    c, _ = client
    upload = _resume_docx_bytes_with_an_untaggable_bullet()

    baseline = c.post(
        "/api/master-resume/import",
        files={"file": ("resume.docx", upload, _DOCX_MIME)},
    ).json()
    assert baseline["untagged_bullet_count"] >= 1

    from resume_tailor.pipeline import propose as propose_mod

    def fake_propose_bullet_tags(bullets, known_tags, **_kwargs):
        return {0: ["python"]}

    monkeypatch.setattr(propose_mod, "propose_bullet_tags", fake_propose_bullet_tags)

    res = c.post(
        "/api/master-resume/import",
        data={"suggest_tags": "true"},
        files={"file": ("resume.docx", upload, _DOCX_MIME)},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["untagged_bullet_count"] == baseline["untagged_bullet_count"] - 1


def test_import_master_resume_suggest_tags_failure_is_a_warning_not_a_500(client, monkeypatch):
    """The LLM pass must never fail the import itself — a raised error becomes a
    warning in the response, and the deterministic draft is still returned."""
    c, _ = client
    from resume_tailor.pipeline import propose as propose_mod

    def fake_propose_bullet_tags(bullets, known_tags, **_kwargs):
        raise RuntimeError("model unreachable")

    monkeypatch.setattr(propose_mod, "propose_bullet_tags", fake_propose_bullet_tags)

    res = c.post(
        "/api/master-resume/import",
        data={"suggest_tags": "true"},
        files={"file": ("resume.docx", _resume_docx_bytes_with_an_untaggable_bullet(), _DOCX_MIME)},
    )
    assert res.status_code == 200
    body = res.json()
    assert any("model unreachable" in w for w in body["warnings"])
    assert body["resume"]["contact"]["name"] == "Ada Lovelace"


def test_import_master_resume_suggest_tags_is_pinned_to_ollama_regardless_of__active(
    client, monkeypatch
):
    """The import's tag-suggestion pass must not fall through to `backend_for`'s claude
    default. Resolving a claude job first (as a prior tailoring run would leave `_ACTIVE`)
    and then checking what backend the LLM call actually observes pins the fix: without
    `config.pinned(config.ONE_OFF_PROFILE)` around the call, this would come back
    provider='anthropic'."""
    c, _ = client
    config.resolve("claude")

    from resume_tailor.pipeline import propose as propose_mod

    observed: dict[str, object] = {}

    def fake_propose_bullet_tags(bullets, known_tags, **_kwargs):
        backend = config.backend_for("extract")
        observed["origin"] = backend.origin
        observed["model"] = backend.model
        observed["provider"] = backend.provider
        return {}

    monkeypatch.setattr(propose_mod, "propose_bullet_tags", fake_propose_bullet_tags)

    res = c.post(
        "/api/master-resume/import",
        data={"suggest_tags": "true"},
        files={
            "file": (
                "resume.docx",
                _resume_docx_bytes_with_an_untaggable_bullet(),
                _DOCX_MIME,
            )
        },
    )
    assert res.status_code == 200
    assert observed == {
        "origin": "ollama",
        "model": config.OLLAMA_MODEL,
        "provider": "openai",
    }
    # The pin must not leak into the ambient job routing.
    assert config.backend_for("extract").provider == "anthropic"
    config.resolve("claude")


def test_import_master_resume_suggest_tags_survives_a_non_runtimeerror_failure(
    client, monkeypatch
):
    """Regression for the reported bug: a real backend SDK error (e.g.
    `anthropic.BadRequestError`, which is neither `LLMError` nor `RuntimeError`) must
    still become a warning, not an unhandled 500."""
    c, _ = client
    from resume_tailor.pipeline import propose as propose_mod

    def fake_propose_bullet_tags(bullets, known_tags, **_kwargs):
        raise _FakeSDKError("Your credit balance is too low to access the Anthropic API.")

    monkeypatch.setattr(propose_mod, "propose_bullet_tags", fake_propose_bullet_tags)

    res = c.post(
        "/api/master-resume/import",
        data={"suggest_tags": "true"},
        files={
            "file": (
                "resume.docx",
                _resume_docx_bytes_with_an_untaggable_bullet(),
                _DOCX_MIME,
            )
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert any("credit balance" in w for w in body["warnings"])
    assert body["resume"]["contact"]["name"] == "Ada Lovelace"
