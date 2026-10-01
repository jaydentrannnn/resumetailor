"""Saved settings round-trips (`/api/settings`)."""

from __future__ import annotations

import json

from resume_tailor.content.data import load
from resume_tailor.web import jobs as jobs_mod
from tests.web.helpers import _point_settings_at


def test_get_settings_returns_seeded_defaults_when_missing(client, tmp_path, monkeypatch):
    """No settings.json yet: GET reports JobSettings() defaults and seeded=True."""
    c, _ = client
    _point_settings_at(tmp_path, monkeypatch)

    res = c.get("/api/settings")
    assert res.status_code == 200
    body = res.json()
    assert body["seeded"] is True
    assert body["settings"]["pages"] == 1
    # Ollama, not Claude: a profile that has never saved settings must still be runnable
    # without an Anthropic key.
    assert body["settings"]["model"] == "ollama"
    # Blank means "use the server's OLLAMA_MODEL" — the field only overrides when set.
    assert body["settings"]["ollama_model"] is None


def test_settings_round_trip(client, tmp_path, monkeypatch):
    """PUT persists new defaults; a later GET reflects them and reports seeded=False."""
    c, _ = client
    path = _point_settings_at(tmp_path, monkeypatch)

    res = c.put("/api/settings", json={"settings": {"pages": 2, "model": "ollama"}})
    assert res.status_code == 200
    body = res.json()
    assert body["seeded"] is False
    assert body["settings"]["pages"] == 2
    assert body["settings"]["model"] == "ollama"
    assert path.exists()

    got = c.get("/api/settings")
    assert got.status_code == 200
    got_body = got.json()
    assert got_body["seeded"] is False
    assert got_body["settings"]["pages"] == 2
    assert got_body["settings"]["model"] == "ollama"


def test_settings_round_trip_with_section_weighting(client, tmp_path, monkeypatch):
    """PUT/GET round-trip experience_bullet_share and max_bullets_per_entry."""
    c, _ = client
    _point_settings_at(tmp_path, monkeypatch)

    res = c.put(
        "/api/settings",
        json={"settings": {"experience_bullet_share": 0.7, "max_bullets_per_entry": 3}},
    )
    assert res.status_code == 200
    body = res.json()["settings"]
    assert body["experience_bullet_share"] == 0.7
    assert body["max_bullets_per_entry"] == 3

    got = c.get("/api/settings").json()["settings"]
    assert got["experience_bullet_share"] == 0.7
    assert got["max_bullets_per_entry"] == 3


def test_settings_round_trip_with_cover_angles(client, tmp_path, monkeypatch):
    """CoverAngles nested on JobSettings survive a settings PUT/GET."""
    c, _ = client
    _point_settings_at(tmp_path, monkeypatch)

    res = c.put(
        "/api/settings",
        json={
            "settings": {
                "cover_letter": True,
                "cover_angles": {
                    "why_company": "Their RAG stack",
                    "problem": "Retrieval latency",
                    "approach": "Measure first",
                    "tone": "direct",
                },
            }
        },
    )
    assert res.status_code == 200
    angles = res.json()["settings"]["cover_angles"]
    assert angles["why_company"] == "Their RAG stack"
    assert angles["tone"] == "direct"

    got = c.get("/api/settings").json()["settings"]["cover_angles"]
    assert got["problem"] == "Retrieval latency"
    assert got["approach"] == "Measure first"


def test_settings_round_trip_with_style_overrides(client, tmp_path, monkeypatch):
    """Custom rewrite/expand style blocks persist through GET/PUT."""
    c, _ = client
    _point_settings_at(tmp_path, monkeypatch)

    custom = "- Prefer past tense throughout."
    res = c.put(
        "/api/settings",
        json={"settings": {"rewrite_style": custom, "expand_style": custom}},
    )
    assert res.status_code == 200
    body = res.json()["settings"]
    assert body["rewrite_style"] == custom
    assert body["expand_style"] == custom

    got = c.get("/api/settings").json()["settings"]
    assert got["rewrite_style"] == custom
    assert got["expand_style"] == custom


def test_settings_round_trip_with_model_name(client, tmp_path, monkeypatch):
    """The blanket model_name override round-trips through settings.json."""
    c, _ = client
    _point_settings_at(tmp_path, monkeypatch)

    res = c.put("/api/settings", json={"settings": {"model_name": "gemma4:cloud"}})
    assert res.status_code == 200
    assert res.json()["settings"]["model_name"] == "gemma4:cloud"


def test_create_job_without_settings_uses_saved_defaults(client, tmp_path, monkeypatch):
    """POST /api/jobs with no `settings` falls back to the active profile's saved ones."""
    c, q = client
    _point_settings_at(tmp_path, monkeypatch)
    c.put("/api/settings", json={"settings": {"pages": 3, "no_semantic": True}})

    # The background worker picks this job up immediately; stub the first pipeline
    # call so it fails fast in-process instead of ever reaching the network, whether
    # or not an API key happens to be configured in this environment.
    def _stub_extract_raises(*args, **kwargs):
        raise RuntimeError("stub — no network in tests")

    monkeypatch.setattr(jobs_mod.jd, "extract", _stub_extract_raises)

    res = c.post("/api/jobs", json={"jd_text": "Some job description."})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    job = q.get(job_id)
    assert job.settings.pages == 3
    assert job.settings.no_semantic is True


def test_settings_round_trip_with_nested_include(client, tmp_path, monkeypatch):
    """PUT/GET round-trip the nested `include` field alongside the flat ones."""
    c, _ = client
    _point_settings_at(tmp_path, monkeypatch)

    res = c.put(
        "/api/settings",
        json={
            "settings": {
                "pages": 1,
                "include": {
                    "contact_fields": ["email", "linkedin"],
                    "gpa": False,
                    "coursework": False,
                    "exclude_experience": ["some-job"],
                    "exclude_projects": ["some-project"],
                },
            }
        },
    )
    assert res.status_code == 200
    body = res.json()["settings"]["include"]
    assert body["contact_fields"] == ["email", "linkedin"]
    assert body["gpa"] is False
    assert body["coursework"] is False
    assert body["exclude_experience"] == ["some-job"]
    assert body["exclude_projects"] == ["some-project"]

    got = c.get("/api/settings").json()["settings"]["include"]
    assert got == body


def test_settings_json_predating_include_key_still_loads(client, tmp_path, monkeypatch):
    """A settings.json written before `include` existed must not 500 on GET, and its
    GPA field must reflect the resume's own current `show_gpa` rather than the schema
    default — see `_seed_include_gpa_if_missing`. This fixture resume has GPA hidden."""
    c, _ = client
    resume = load()
    assert not any(edu.show_gpa for edu in resume.education)  # sanity: GPA is hidden
    path = _point_settings_at(tmp_path, monkeypatch)
    path.write_text(
        json.dumps({"schema_version": 1, "defaults": {"pages": 2, "model": "ollama"}}),
        encoding="utf-8",
    )

    res = c.get("/api/settings")
    assert res.status_code == 200
    body = res.json()["settings"]
    assert body["pages"] == 2
    assert body["include"] == {
        "contact_fields": None,
        "gpa": False,
        "coursework": True,
        "exclude_entries": [],
        "exclude_sections": [],
        "exclude_experience": [],
        "exclude_projects": [],
        "section_order": None,
    }


def test_settings_include_gpa_seed_never_overrides_an_explicit_choice(
    client, tmp_path, monkeypatch
):
    """Once `include` has been saved once, its `gpa` value is the user's own choice —
    the resume-derived fallback in `test_settings_json_predating_include_key_still_loads`
    must never apply after that point, even if it now disagrees with the resume."""
    c, _ = client
    path = _point_settings_at(tmp_path, monkeypatch)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {
                    "pages": 2,
                    "model": "ollama",
                    "include": {
                        "contact_fields": None,
                        "gpa": True,
                        "coursework": True,
                        "exclude_experience": [],
                        "exclude_projects": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    res = c.get("/api/settings")
    assert res.status_code == 200
    # The fixture resume's show_gpa is False, but an explicitly saved `gpa: True`
    # must win — this profile has already been through the include-aware save path.
    assert res.json()["settings"]["include"]["gpa"] is True
