"""Parallel Fill runs one application per Workday site at a time."""

from __future__ import annotations

import threading
import time
from collections import Counter

import pytest

from resume_tailor.apply.funnel import fill_hosts, op_slots, operations, store_models
from resume_tailor.web.schemas import ApplyOperationRequest, ApplySettings

_SITES = {
    "aptiv-1": "https://aptiv.wd5.myworkdayjobs.com/en-US/aptiv_careers/job/A_J1",
    "aptiv-2": "https://aptiv.wd5.myworkdayjobs.com/en-US/aptiv_careers/job/B_J2",
    "itron-1": "https://itron.wd5.myworkdayjobs.com/en-US/Itron/job/C_J3",
    "greenhouse": "https://job-boards.greenhouse.io/acme/jobs/1",
}


@pytest.fixture
def apps(monkeypatch):
    operations._CONTROLS.clear()
    operations._ACTIVE.clear()
    op_slots.WORKDAY_BUSY.clear()
    monkeypatch.setattr(operations, "_persist", lambda _operation: None)
    monkeypatch.setattr(operations.browser, "extension_mode", lambda: False)
    monkeypatch.setattr(operations.submit_guard, "is_paused", lambda: False)
    rows = {
        key: store_models.Application(
            source="test", source_job_id=key, company=key, role="Intern", status="ready",
            ats="workday" if "greenhouse" not in key else "greenhouse", final_url=url,
        )
        for key, url in _SITES.items()
    }
    monkeypatch.setattr(operations.store, "get", rows.get)
    return rows


def _run(ids: list[str], workers: int = 2) -> operations.ApplyOperation:
    request = ApplyOperationRequest(
        action="fill", application_ids=ids, model_provider="ollama", model_name="test",
    )
    operation = operations.ApplyOperation(
        operation_id="test", action="fill", state="running", application_ids=ids, total=len(ids),
    )
    operations._dispatch_items(operation, request, ApplySettings(max_parallel_fills=workers), None)
    return operation


def test_same_workday_site_never_fills_twice_at_once(apps, monkeypatch):
    lock = threading.Lock()
    active: Counter[str] = Counter()
    peak: Counter[str] = Counter()
    overall = overall_peak = 0

    def fake_fill(application_id, **_kwargs):
        nonlocal overall, overall_peak
        host = fill_hosts.workday_host(apps[application_id]) or application_id
        with lock:
            active[host] += 1
            overall += 1
            peak[host] = max(peak[host], active[host])
            overall_peak = max(overall_peak, overall)
        time.sleep(0.15)
        with lock:
            active[host] -= 1
            overall -= 1
        return store_models.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    operation = _run(["aptiv-1", "aptiv-2", "itron-1", "greenhouse"])

    assert peak["aptiv.wd5.myworkdayjobs.com"] == 1
    assert overall_peak == 2  # other sites still run beside the Aptiv queue
    assert (operation.processed, operation.completed, operation.failed) == (4, 4, 0)


def test_unverified_account_holds_the_rest_of_that_site(apps, monkeypatch):
    filled: list[str] = []

    def fake_fill(application_id, **_kwargs):
        filled.append(application_id)
        if application_id == "aptiv-1":
            apps["aptiv-1"].status = "awaiting_otp"
            return store_models.FillResult(status="awaiting_otp")
        return store_models.FillResult(status="awaiting_review", ready_to_submit=True)

    monkeypatch.setattr(operations.fill, "fill_application", fake_fill)
    operation = _run(["aptiv-1", "aptiv-2", "itron-1"], workers=1)

    assert filled == ["aptiv-1", "itron-1"]
    assert operation.processed == 3
    assert operation.blocked == 2
    held = [e for e in operation.events if e["application_id"] == "aptiv-2"]
    assert "waiting for email verification" in held[-1]["message"]


def test_non_workday_rows_have_no_site():
    row = store_models.Application(
        source="t", source_job_id="x", company="x", role="r",
        ats="greenhouse", final_url=_SITES["greenhouse"],
    )
    assert fill_hosts.workday_host(row) == ""
    assert fill_hosts.workday_host(None) == ""


def test_events_keep_each_applications_history(apps):
    operation = operations.ApplyOperation(
        operation_id="t", action="fill", state="running", application_ids=[], total=0,
    )
    operations._event(operation, "pause_requested", "Pause requested")
    for index in range(200):
        operations._event(operation, "filling", f"chatty {index}", "aptiv-1")
    operations._event(operation, "filling", "quiet one", "itron-1")
    owners = Counter(event["application_id"] for event in operation.events)
    assert owners["aptiv-1"] == operations._EVENTS_PER_APPLICATION
    assert owners["itron-1"] == 1
    assert operation.events[0]["stage"] == "pause_requested"
    assert operation.events[-1]["message"] == "quiet one"
