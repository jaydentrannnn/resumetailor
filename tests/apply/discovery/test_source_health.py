"""Per-source run history and its health verdict (`source_status.health`)."""

from __future__ import annotations

import json

from resume_tailor import config
from resume_tailor.apply.discovery import source_status
from resume_tailor.apply.discovery.source_rows import SourceRow
from resume_tailor.apply.funnel import daily_batch


def _entry(found: int, *, blank: int = 0, error: str | None = None, at: str = "t") -> dict:
    return {"found": found, "kept": found, "blank": blank, "error": error, "at": at}


def _runs(*entries: dict) -> dict:
    for i, entry in enumerate(entries):
        source_status.record_source_status({"src": {**entry, "at": f"2026-10-{i + 1:02d}"}},
                                           f"2026-10-{i + 1:02d}")
    return source_status.load_source_status()["sources"]["src"]


def test_history_keeps_the_last_ten_runs_after_an_old_entry():
    old = {"found": 7, "kept": 3, "error": None, "at": "2026-01-01"}
    config.SOURCE_STATUS_PATH.write_text(json.dumps({"sources": {"src": old}}), "utf-8")
    entry = _runs(*[_entry(n) for n in range(12)])
    assert len(entry["history"]) == source_status.HISTORY
    assert [r["found"] for r in entry["history"]] == list(range(2, 12))
    assert entry["found"] == 11 and entry["blank"] == 0


def test_a_healthy_or_never_finding_source_gets_no_verdict():
    assert source_status.health(_runs(_entry(5), _entry(6)))["health"] is None
    config.SOURCE_STATUS_PATH.unlink()
    quiet = _runs(_entry(0, error="No postings found"), _entry(0, error="No postings found"))
    assert source_status.health(quiet)["health"] is None


def test_zero_after_earlier_finds_is_degraded():
    entry = _runs(_entry(40), _entry(12), _entry(0, error="No postings found"))
    verdict = source_status.health(entry)
    assert verdict["health"] == "degraded" and "after 40 before" in verdict["health_reason"]


def test_a_plain_failure_is_left_to_the_error_line():
    entry = _runs(_entry(40), _entry(0, error="could not reach x.example"))
    assert source_status.health(entry)["health"] is None


def test_mostly_blank_company_or_title_is_degraded_from_four_rows():
    verdict = source_status.health(_runs(_entry(6, blank=3)))
    assert verdict["health"] == "degraded" and verdict["health_reason"].startswith("3 of 6")
    assert source_status.health(_runs(_entry(3, blank=3)))["health"] is None


def test_throttling_reads_as_rate_limited():
    for error in ("HTTP 429 from api.example", "Rate limit exceeded", "request blocked"):
        verdict = source_status.health(_runs(_entry(8), _entry(0, error=error)))
        assert verdict["health"] == "rate_limited", error
    assert source_status.health(_entry(0, error="HTTP 4290 from x"))["health"] is None


def test_a_run_entry_counts_rows_missing_a_company_or_title():
    rows = [SourceRow(company=c, role=r, location="", age="1d") for c, r in
            (("Acme", "Analyst"), ("", "Analyst"), ("Acme", "  "))]
    entry = daily_batch._source_status_entry(rows, 1, "")
    assert (entry["found"], entry["kept"], entry["blank"], entry["error"]) == (3, 1, 2, None)
    assert daily_batch._source_status_entry([], 0, "")["error"] == "No postings found"
