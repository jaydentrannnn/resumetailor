"""theme.json merge: preference, accent and scale keep each other."""

from __future__ import annotations

import json

import pytest

from resume_tailor.infra import appearance
from resume_tailor.web.schemas import JobSettings


def test_save_merges_without_clearing_other_fields(tmp_path, monkeypatch):
    """Writing accent leaves preference; clearing accent leaves scale."""
    path = tmp_path / "theme.json"
    monkeypatch.setenv("RESUME_TAILOR_THEME_PATH", str(path))
    appearance.save(preference="dark")
    appearance.save(accent="#3b82f6")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["preference"] == "dark"
    assert data["accent"] == "#3b82f6"
    appearance.save(scale=1.25)
    appearance.save(accent=None)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["preference"] == "dark"
    assert "accent" not in data
    assert data["scale"] == 1.25


def test_save_rejects_bad_accent_and_scale(tmp_path, monkeypatch):
    """Invalid accent or scale raises ValueError."""
    monkeypatch.setenv("RESUME_TAILOR_THEME_PATH", str(tmp_path / "theme.json"))
    with pytest.raises(ValueError, match="accent"):
        appearance.save(accent="blue")
    with pytest.raises(ValueError, match="scale"):
        appearance.save(scale=1.15)


def test_job_settings_include_rail_and_start_page():
    """Fresh JobSettings expose the Appearance app-wide keys."""
    settings = JobSettings()
    assert settings.start_page == "/"
    assert settings.rail_layout.order == []
    assert settings.apply.table_prefs.queue.columns == []
