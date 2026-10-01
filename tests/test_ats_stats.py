"""Hermetic tests for `scripts/ats_stats.py` (plan P4-A: pick adapters by volume)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from resume_tailor.apply.funnel import store

_SPEC = importlib.util.spec_from_file_location(
    "ats_stats", Path(__file__).parents[1] / "scripts" / "ats_stats.py"
)
assert _SPEC and _SPEC.loader
ats_stats = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ats_stats)


def _app(ats: str, status: str, url: str = "", archived: bool = False) -> store.Application:
    return store.Application(
        source="test",
        source_job_id=f"{ats}-{status}-{url}",
        company="Acme",
        role="Analyst",
        ats=ats,
        status=status,
        final_url=url,
        archived_at="2026-09-01T00:00:00Z" if archived else None,
    )


def test_tally_redetects_platforms_stored_as_other():
    apps = [
        _app("greenhouse", "submitted"),
        _app("greenhouse", "awaiting_review"),
        _app("other", "ready", "https://jpmc.taleo.net/careersection/2/jobdetail.ftl?job=1"),
        _app("other", "fill_failed", "https://jpmc.taleo.net/careersection/2/jobdetail.ftl?job=2"),
        _app("other", "ready", "https://careers.acme.com/jobs/3"),
        _app("workday", "ready", archived=True),
    ]
    table = ats_stats.tally(apps)
    assert list(table) == ["greenhouse", "taleo", "other"]
    assert table["taleo"]["total"] == 2
    assert table["taleo"]["fill_failed"] == 1
    assert "workday" not in table

    stored = ats_stats.tally(apps, stored=True, include_archived=True)
    assert stored["other"]["total"] == 3
    assert stored["workday"]["ready"] == 1


def test_format_table_lines_up_columns():
    table = ats_stats.tally([_app("lever", "submitted"), _app("lever", "ready")])
    header, row = ats_stats.format_table(table).splitlines()
    assert header.split()[:3] == ["ats", "total", "ready"]
    assert row.split()[:3] == ["lever", "2", "1"]
    assert header.index("submitted") == row.index("1", header.index("submitted"))
