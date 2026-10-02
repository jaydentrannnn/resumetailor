"""Hermetic tests for the auto-submit guard rails (`apply/submit_guard.py`, plan P4-S)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply.forms import submit_guard
from resume_tailor.apply.funnel import operations, scheduler, store, store_models
from resume_tailor.web.app import app as web_app
from resume_tailor.web.schemas import ApplySettings

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
SETTINGS = ApplySettings(auto_submit_enabled=True, auto_submit_ats=["greenhouse"])


def _app(key: str, *, company: str = "Acme", role: str = "Analyst Intern", **fields):
    return store_models.Application(
        source="simplify",
        source_job_id=key,
        canonical_key=f"greenhouse:{key}",
        company=company,
        role=role,
        ats="greenhouse",
        status=fields.pop("status", "ready"),
        **fields,
    )


def _submitted(key: str, *, at: datetime, note: str = "auto_submit", status="submitted", **fields):
    row = _app(key, **fields)
    row.status = status
    row.status_history.append(
        store_models.StatusChange(status=status, at=at.isoformat(), note=note)
    )
    return row


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme, Inc.", "acme"),
        ("ACME", "acme"),
        ("Goldman Sachs & Co. LLC", "goldman sachs"),
        ("", ""),
    ],
)
def test_normalize_company(raw, expected):
    assert submit_guard.normalize_company(raw) == expected


def test_nothing_holds_a_fresh_application():
    assert submit_guard.check(_app("a"), SETTINGS, apps=[], now=NOW) is None


def test_pause_switch_round_trip_and_hold():
    assert submit_guard.automation_state()["paused"] is False
    state = submit_guard.set_paused(True)
    assert state["paused"] is True and state["changed_at"]
    hold = submit_guard.check(_app("a"), SETTINGS, apps=[], now=NOW)
    assert hold is not None and hold.code == "paused"
    submit_guard.set_paused(False)
    assert submit_guard.check(_app("a"), SETTINGS, apps=[], now=NOW) is None


def test_unreadable_pause_file_means_not_paused():
    submit_guard.pause_path().write_text("{not json", encoding="utf-8")
    assert submit_guard.is_paused() is False


def test_a_row_submitted_before_is_never_submitted_again():
    row = _submitted("a", at=NOW - timedelta(days=90), note="manual")
    row.status = "awaiting_review"  # e.g. the student reopened it
    hold = submit_guard.check(row, SETTINGS, apps=[row], now=NOW)
    assert hold is not None and hold.code == "already_submitted"


def test_same_company_and_role_within_30_days_is_a_duplicate():
    earlier = _submitted("old", at=NOW - timedelta(days=10), company="ACME Inc.", note="manual")
    hold = submit_guard.check(_app("new"), SETTINGS, apps=[earlier], now=NOW)
    assert hold is not None and hold.code == "duplicate"
    assert hold.message == "Possible duplicate of ACME Inc. — Analyst Intern"


def test_same_job_submitted_long_ago_is_not_a_duplicate():
    earlier = _submitted("old", at=NOW - timedelta(days=45), note="manual")
    assert submit_guard.check(_app("new"), SETTINGS, apps=[earlier], now=NOW) is None


def test_different_role_at_the_same_company_is_not_a_duplicate():
    earlier = _submitted("old", at=NOW - timedelta(days=1), role="Data Intern", note="manual")
    assert submit_guard.check(_app("new"), SETTINGS, apps=[earlier], now=NOW) is None


def test_same_duplicate_group_is_a_duplicate_whatever_the_age():
    earlier = _submitted(
        "old", at=NOW - timedelta(days=200), role="Other title", group_key="g1", note="manual"
    )
    hold = submit_guard.check(_app("new", group_key="g1"), SETTINGS, apps=[earlier], now=NOW)
    assert hold is not None and hold.code == "duplicate"


def test_daily_cap_counts_only_automatic_submits_in_the_last_24_hours():
    settings = SETTINGS.model_copy(update={"auto_submit_max_per_day": 2})
    apps = [
        _submitted("a1", company="A", at=NOW - timedelta(hours=2)),
        _submitted("a2", company="B", at=NOW - timedelta(hours=30)),  # too old
        _submitted("a3", company="C", at=NOW - timedelta(hours=1), note="manual"),  # by hand
    ]
    assert submit_guard.check(_app("new", company="Z"), settings, apps=apps, now=NOW) is None
    apps.append(
        _submitted("a4", company="D", at=NOW - timedelta(hours=3), status="submit_unconfirmed")
    )
    hold = submit_guard.check(_app("new", company="Z"), settings, apps=apps, now=NOW)
    assert hold is not None and hold.code == "daily_cap"
    assert hold.message.startswith("Daily cap reached")


def test_zero_daily_cap_means_no_automatic_submits():
    settings = SETTINGS.model_copy(update={"auto_submit_max_per_day": 0})
    hold = submit_guard.check(_app("a"), settings, apps=[], now=NOW)
    assert hold is not None and hold.code == "daily_cap"


def test_per_company_cap():
    apps = [
        _submitted("a1", role="Role 1", at=NOW - timedelta(hours=1)),
        _submitted("a2", role="Role 2", company="Acme, Inc.", at=NOW - timedelta(hours=5)),
    ]
    hold = submit_guard.check(_app("new", role="Role 3"), SETTINGS, apps=apps, now=NOW)
    assert hold is not None and hold.code == "company_cap"
    assert (
        submit_guard.check(_app("new", company="Beta", role="Role 3"), SETTINGS, apps=apps, now=NOW)
        is None
    )


def test_defaults():
    settings = ApplySettings()
    assert settings.auto_submit_max_per_day == 25
    assert settings.auto_submit_max_per_company_per_day == 2


# --- pacing -------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(submit_guard, "_clock", fake)
    monkeypatch.setattr(submit_guard, "_sleep", fake.sleep)
    submit_guard.seed(7)
    return fake


def test_first_submit_does_not_wait_and_the_next_one_does(clock):
    with submit_guard.pace() as go:
        assert go
    assert clock.slept == []
    waits: list[float] = []
    with submit_guard.pace(on_wait=waits.append) as go:
        assert go
    (announced,) = waits
    assert 20 <= announced <= 90
    assert sum(clock.slept) == pytest.approx(announced)
    assert max(clock.slept) <= 1.0


def test_delays_are_repeatable_with_a_seed():
    submit_guard.seed(3)
    first = [submit_guard.next_delay() for _ in range(3)]
    submit_guard.seed(3)
    assert [submit_guard.next_delay() for _ in range(3)] == first
    assert all(20 <= d <= 90 for d in first)


def test_time_already_passed_counts_toward_the_gap(clock):
    with submit_guard.pace():
        pass
    clock.now += 500
    with submit_guard.pace() as go:
        assert go
    assert clock.slept == []


def test_cancel_during_the_wait_stops_the_submit(clock):
    with submit_guard.pace():
        pass
    before = submit_guard._last_submit  # noqa: SLF001
    with submit_guard.pace(should_cancel=lambda: bool(clock.slept)) as go:
        assert go is False
    assert submit_guard._last_submit == before  # noqa: SLF001 - an unused slot is not recorded


def test_pause_switch_stops_a_submit_even_without_a_wait(clock):
    submit_guard.set_paused(True)
    with submit_guard.pace() as go:
        assert go is False


def test_final_submit_guard_runs_in_paced_slot(clock):
    allowed = True
    with submit_guard.pace(can_submit=lambda: allowed) as go:
        assert go
    before = submit_guard._last_submit  # noqa: SLF001
    allowed = False
    with submit_guard.pace(can_submit=lambda: allowed) as go:
        assert go is False
    assert submit_guard._last_submit == before  # noqa: SLF001


# --- scheduler and operation worker -------------------------------------------------


def test_scheduler_does_not_start_while_paused(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    started: list[int] = []
    now = datetime(2026, 9, 25, 2, 1)

    def tick():
        return scheduler.tick(
            enabled=True,
            schedule_time="02:00",
            busy=lambda: False,
            start=lambda: started.append(1),
            now=lambda: now,
        )

    submit_guard.set_paused(True)
    assert tick() == "paused"
    assert started == []
    submit_guard.set_paused(False)
    assert tick() == "run"
    assert started == [1]


def test_operation_waits_while_automation_is_paused(monkeypatch):
    op = operations.ApplyOperation.model_validate(
        {"operation_id": "op-1", "action": "fill", "state": "running", "application_ids": []}
    )
    monkeypatch.setattr(operations, "_persist", lambda _op: None)
    assert operations._wait_while_automation_paused(op) is True  # noqa: SLF001

    submit_guard.set_paused(True)
    waits = iter([False, False])

    class _Cancel:
        def wait(self, timeout):
            if next(waits, None) is False:
                return False
            submit_guard.set_paused(False)
            return False

        def is_set(self):
            return False

    monkeypatch.setattr(operations, "_CANCEL", _Cancel())
    assert operations._wait_while_automation_paused(op) is True  # noqa: SLF001
    assert op.state == "running"
    assert [e["stage"] for e in op.events][-2:] == ["automation_paused", "resumed"]


def test_cancelled_while_automation_is_paused(monkeypatch):
    op = operations.ApplyOperation.model_validate(
        {"operation_id": "op-1", "action": "fill", "state": "running", "application_ids": []}
    )
    monkeypatch.setattr(operations, "_persist", lambda _op: None)
    submit_guard.set_paused(True)

    class _Cancelled:
        def wait(self, timeout):
            return True

    monkeypatch.setattr(operations, "_CANCEL", _Cancelled())
    assert operations._wait_while_automation_paused(op) is False  # noqa: SLF001


# --- routes -------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output" / "applications")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    with TestClient(web_app) as test_client:
        yield test_client


def test_automation_routes(client):
    recent = _submitted("a1", at=datetime.now(UTC) - timedelta(hours=1))
    store.upsert(recent)
    body = client.get("/api/automation").json()
    assert body["paused"] is False
    assert body["auto_submits_24h"] == 1
    assert body["max_per_day"] == 25
    body = client.put("/api/automation", json={"paused": True}).json()
    assert body["paused"] is True
    assert submit_guard.is_paused()


def test_submit_evidence_routes(client):
    row = _app("a1")
    store.upsert(row)
    folder = config.APPLICATIONS_OUTPUT_DIR / "a1" / "submit-20260925T120000Z"
    folder.mkdir(parents=True)
    (folder / "before.json").write_text(json.dumps({"url": "https://x/apply"}), encoding="utf-8")
    (folder / "after.json").write_text(
        json.dumps({"url": "https://x/done", "status": "submitted", "confirmation": "thank you"}),
        encoding="utf-8",
    )
    (folder / "after.png").write_bytes(b"\x89PNG")
    (config.APPLICATIONS_OUTPUT_DIR / "a1" / "not-evidence").mkdir()

    body = client.get("/api/applications/greenhouse:a1/submit-evidence").json()
    (item,) = body["evidence"]
    assert item["stamp"] == "submit-20260925T120000Z"
    assert item["files"] == ["before.json", "after.json", "after.png"]
    assert item["status"] == "submitted" and item["url"] == "https://x/done"

    png = client.get(
        "/api/applications/greenhouse:a1/submit-evidence/submit-20260925T120000Z/after.png"
    )
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert (
        client.get(
            "/api/applications/greenhouse:a1/submit-evidence/submit-20260925T120000Z/secret.txt"
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/applications/greenhouse:a1/submit-evidence/..%2F..%2Fx/after.png"
        ).status_code
        == 404
    )
    assert client.get("/api/applications/nope/submit-evidence").status_code == 404
