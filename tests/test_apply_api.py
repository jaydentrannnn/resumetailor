"""Hermetic tests for apply API routes (profile, applications list, browser status)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply import profile as profile_mod
from resume_tailor.apply import store as apply_store
from resume_tailor.apply import operations as operations_mod
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue
from resume_tailor.web import jobs as jobs_mod
from tests.fixtures import synthetic_resume


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Minimal TestClient with isolated apply paths and stubbed job queue."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "output" / "applications")
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    resume_path = tmp_path / "master_resume.json"
    resume_path.write_text(
        json.dumps(synthetic_resume().model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)

    q = JobQueue()
    monkeypatch.setattr(jobs_mod, "queue_singleton", q)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: q)

    with TestClient(app) as test_client:
        test_client.get("/api/config")
        yield test_client, q


def test_applicant_profile_round_trip(client, tmp_path, monkeypatch):
    """GET seeds an empty profile; PUT persists and GET returns it."""
    c, _q = client
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    monkeypatch.setattr(profile_mod.config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")

    res = c.get("/api/applicant-profile")
    assert res.status_code == 200
    body = res.json()
    assert body["seeded"] is True
    assert body["profile"]["email"] == ""

    body["profile"]["email"] = "test@example.com"
    body["profile"]["first_name"] = "Ada"
    put = c.put("/api/applicant-profile", json={"profile": body["profile"]})
    assert put.status_code == 200
    assert put.json()["profile"]["email"] == "test@example.com"
    assert put.json()["seeded"] is False

    again = c.get("/api/applicant-profile")
    assert again.json()["profile"]["first_name"] == "Ada"
    assert again.json()["profile"]["languages"] == []

    body["profile"]["languages"] = [{"language": "Vietnamese", "fluent": True, "levels": {"Speaking": "Native"}}]
    c.put("/api/applicant-profile", json={"profile": body["profile"]})
    assert c.get("/api/applicant-profile").json()["profile"]["languages"] == body["profile"]["languages"]


def test_applicant_profile_lists_blank_fields_forms_ask_for(client, tmp_path, monkeypatch):
    """Gaps rank what stored fills actually met first; answered or defaulted fields drop out."""
    c, _q = client
    path = tmp_path / "applicant_profile.json"
    monkeypatch.setattr(profile_mod.config, "APPLICANT_PROFILE_PATH", path)
    met = {"key": "notice_period", "field_label": "Notice period", "questions": ["Notice period"]}
    apply_store.save_all({
        "a": apply_store.Application(source="t", source_job_id="a", company="A", role="R",
                                     fill=apply_store.FillResult(missing_profile=[met])),
        "b": apply_store.Application(source="t", source_job_id="b", company="B", role="R"),
    })

    body = c.get("/api/applicant-profile").json()
    keys = [gap["key"] for gap in body["gaps"]]
    assert keys[0] == "notice_period"  # not a common field, but a fill met it blank
    assert body["gaps"][0]["seen_in"] == 1
    assert "authorized_to_work" in keys
    assert "phone_device_type" not in keys
    assert body["defaults"] == {"phone_device_type": "Mobile"}
    assert next(gap for gap in body["gaps"] if gap["key"] == "authorized_to_work")["path"] == "/profile/application"

    body["profile"]["authorized_to_work"] = True
    body["profile"]["notice_period"] = "Two weeks"
    saved = c.put("/api/applicant-profile", json={"profile": body["profile"]}).json()
    assert not {"authorized_to_work", "notice_period"} & {gap["key"] for gap in saved["gaps"]}


def test_applicant_profile_redacts_and_preserves_workday_password(client, tmp_path, monkeypatch):
    """Ordinary profile responses never expose the stored Workday password."""
    c, _q = client
    path = tmp_path / "applicant_profile.json"
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", path)
    monkeypatch.setattr(profile_mod.config, "APPLICANT_PROFILE_PATH", path)

    profile = profile_mod.ApplicantProfile(
        first_name="Ada",
        workday_email="ada@example.com",
        workday_password="Secret!42",
    )
    profile_mod.save_profile(profile)

    got = c.get("/api/applicant-profile").json()
    assert got["profile"]["workday_password"] == ""
    assert got["workday_password_set"] is True

    got["profile"]["city"] = "London"
    saved = c.put("/api/applicant-profile", json={"profile": got["profile"]}).json()
    assert saved["profile"]["workday_password"] == ""
    assert saved["workday_password_set"] is True
    stored, _seeded = profile_mod.load_profile()
    assert stored.workday_password == "Secret!42"
    assert stored.city == "London"


def test_applications_list_empty(client):
    """Empty registry returns zero counts."""
    c, _q = client
    res = c.get("/api/applications")
    assert res.status_code == 200
    body = res.json()
    assert body["applications"] == []
    assert isinstance(body["counts"], dict)
    assert body["total"] == 0


def test_archive_endpoint_and_scoped_listing(client):
    c, _q = client
    apply_store.save_all({
        "a": apply_store.Application(source="simplify", source_job_id="a", company="Acme", role="Engineer", status="submitted"),
        "b": apply_store.Application(source="simplify", source_job_id="b", company="Beta", role="Designer"),
    })
    moved = c.post("/api/applications/archive", json={"application_ids": ["a", "unknown"], "archived": True})
    assert moved.status_code == 200
    assert moved.json()["updated"] == ["a"]
    assert moved.json()["errors"] == {"unknown": "Application not found"}
    assert c.get("/api/applications?archive=active").json()["total"] == 1
    archived = c.get("/api/applications?archive=archived&q=ACME").json()
    assert archived["total"] == 1
    assert archived["applications"][0]["status"] == "submitted"
    assert archived["applications"][0]["archived_at"]
    assert c.post("/api/applications/a/status", json={"status": "interview"}).status_code == 409
    assert c.get("/api/applications").json()["total"] == 2
    assert c.post("/api/applications/archive", json={"application_ids": ["a"], "archived": False}).status_code == 200
    assert c.get("/api/applications/a").json()["application"]["status"] == "submitted"


def test_screened_out_row_moves_from_working_to_archived_listing(client):
    c, _q = client
    row = apply_store.Application(source="simplify", source_job_id="screened", company="Acme", role="Intern")
    apply_store.set_status(row, "screened_out", note="prefilter: citizenship_required")
    apply_store.upsert(row)

    working = c.get("/api/applications?archive=active&group=working").json()
    archived = c.get("/api/applications?archive=archived&status=screened_out").json()
    assert working["total"] == 0
    assert archived["total"] == 1
    assert archived["applications"][0]["source_job_id"] == "screened"
    assert archived["applications"][0]["archived_at"] == row.archived_at


def test_archive_busy_conflict_does_not_write(client):
    c, _q = client
    apply_store.save_all({"a": apply_store.Application(source="simplify", source_job_id="a", company="Acme", role="Engineer")})
    assert operations_mod._RUN_LOCK.acquire(blocking=False)
    try:
        result = c.post("/api/applications/archive", json={"application_ids": ["a"], "archived": True})
        assert result.status_code == 409
        assert apply_store.get("a").archived_at is None
    finally:
        operations_mod._RUN_LOCK.release()


def test_applications_list_pages_and_filtered_total(client):
    c, _q = client
    apply_store.save_all({
        f"job-{i}": apply_store.Application(
            source="test",
            source_job_id=f"job-{i}",
            company="Example",
            role=f"Role {i}",
            discovered_at=f"2026-01-01T00:{i:02d}:00Z",
            status="ready" if i % 2 else "discovered",
        )
        for i in range(53)
    })

    first = c.get("/api/applications?limit=50").json()
    second = c.get("/api/applications?limit=50&offset=50").json()
    assert first["total"] == second["total"] == 53
    assert len(first["applications"]) == 50
    assert len(second["applications"]) == 3
    assert first["applications"][0]["source_job_id"] == "job-52"
    assert second["applications"][-1]["source_job_id"] == "job-0"

    filtered = c.get("/api/applications?status=ready&limit=10&offset=10").json()
    assert filtered["total"] == 26
    assert len(filtered["applications"]) == 10
    assert all(row["status"] == "ready" for row in filtered["applications"])


def test_browser_status_shape(client):
    """Browser status always returns the probe schema (usually unreachable in CI)."""
    c, _q = client
    res = c.get("/api/browser/status")
    assert res.status_code == 200
    body = res.json()
    assert "reachable" in body
    assert "cdp_url" in body


@pytest.mark.parametrize(("ids", "expected"), [
    ({"tab-b", "tab-a"}, {"reachable": True, "target_ids": ["tab-a", "tab-b"]}),
    (set(), {"reachable": True, "target_ids": []}),
    (None, {"reachable": False, "target_ids": []}),
])
def test_open_tabs_route_separates_no_tabs_from_unknown(client, monkeypatch, ids, expected):
    """An unreachable browser is "unknown", never "every tab closed"."""
    from resume_tailor.apply import browser as browser_mod
    c, _q = client
    monkeypatch.setattr(browser_mod, "open_target_ids", lambda: ids)
    res = c.get("/api/applications/open-tabs")
    assert res.status_code == 200
    assert res.json() == expected


def test_start_apply_operation_route(client, monkeypatch):
    """The explicit operation endpoint returns a trackable operation id."""
    c, _q = client
    operation = operations_mod.ApplyOperation(
        operation_id="op-1",
        action="prepare",
        application_ids=["a-1"],
        total=1,
        effective_model="ollama:test-model",
    )
    monkeypatch.setattr(operations_mod, "start", lambda _body: operation)
    res = c.post(
        "/api/applications/operations",
        json={
            "action": "prepare",
            "application_ids": ["a-1"],
            "auto_submit": False,
            "blocker_mode": "continue",
            "model_provider": "ollama",
            "model_name": "test-model",
        },
    )
    assert res.status_code == 202
    assert res.json()["operation_id"] == "op-1"
    assert res.json()["effective_model"] == "ollama:test-model"


def test_packet_missing_404(client):
    """Unknown job id has no packet."""
    c, _q = client
    res = c.get("/api/jobs/doesnotexist/packet.json")
    assert res.status_code == 404


def test_verify_claim_without_job_id(client, tmp_path, monkeypatch):
    """POST /api/verify-claim accepts omitted job_id and checks master bullets."""
    c, _q = client
    resume_path = tmp_path / "master_resume.json"
    resume = synthetic_resume()
    resume_path.write_text(json.dumps(resume.model_dump(mode="json"), indent=2), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)

    res = c.post(
        "/api/verify-claim",
        json={"text": "Led a Kubernetes migration for production services."},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is False


def _stored_app(source_job_id: str, status: str) -> apply_store.Application:
    return apply_store.upsert(
        apply_store.Application(
            source="simplify-internships",
            source_job_id=source_job_id,
            company="Acme",
            role="Intern",
            status=status,
            posting_url="https://example.com/job",
        )
    )


def test_list_rows_carry_server_retry_kind(client):
    """Each row tells the SPA whether, and how, it can be retried."""
    c, _q = client
    _stored_app("a-discovered", "discovered")
    _stored_app("a-skipped", "skipped")
    rows = {row["source_job_id"]: row for row in c.get("/api/applications").json()["applications"]}
    assert rows["a-discovered"]["retry_kind"] == "fetch"
    assert rows["a-skipped"]["retry_kind"] is None
    assert "terminal_application" in rows["a-skipped"]["preparation_reasons"]


def test_screened_out_rows_carry_a_short_reason_label(client):
    """The Status column shows why a row was screened out, including legacy reasons."""
    from resume_tailor.apply.screen import ScreenResult

    c, _q = client
    legacy = _stored_app("a-legacy", "screened_out")
    legacy.screen = ScreenResult(
        passed=False,
        reasons=["blocked by pattern '\\\\bU\\\\.?S\\\\.? citizen'", "blocked by pattern 'security clearance'"],
    )
    apply_store.upsert(legacy)
    _stored_app("a-discovered", "discovered")
    rows = {row["source_job_id"]: row for row in c.get("/api/applications").json()["applications"]}
    assert rows["a-legacy"]["screen_label"] == "Citizenship required +1"
    assert rows["a-discovered"]["screen_label"] is None


def test_review_group_lists_rows_waiting_on_the_applicant_with_a_summary(client):
    c, _q = client
    _stored_app("a-review", "awaiting_otp")
    _stored_app("a-ready", "ready")
    review = c.get("/api/applications?archive=active&group=review").json()
    working = c.get("/api/applications?archive=active&group=working").json()
    assert [row["source_job_id"] for row in review["applications"]] == ["a-review"]
    assert review["applications"][0]["review_summary"] == "Verification code"
    assert review["total"] == 1 and review["counts"] == {"awaiting_otp": 1}
    assert [row["source_job_id"] for row in working["applications"]] == ["a-ready"]
    assert working["applications"][0]["review_summary"] is None


def test_archived_application_is_not_preparable_or_retryable(client):
    c, _q = client
    app = _stored_app("a-discovered", "discovered")
    app.archived_at = "2026-09-24T00:00:00+00:00"
    apply_store.upsert(app)
    row = c.get("/api/applications?archive=archived").json()["applications"][0]
    assert row["preparation_eligible"] is False
    assert "archived_application" in row["preparation_reasons"]
    assert c.post("/api/applications/a-discovered/retry").status_code == 409
    result = c.post("/api/applications/operations", json={"action": "prepare", "application_ids": ["a-discovered"], "model_provider": "ollama", "model_name": "test"})
    assert result.status_code == 422


def test_retry_refused_while_an_apply_operation_is_active(client, monkeypatch):
    """A fetch retry may drive the browser an active Apply operation owns."""
    c, _q = client
    _stored_app("a-1", "discovered")
    monkeypatch.setattr(operations_mod, "active", lambda: object())
    res = c.post("/api/applications/a-1/retry")
    assert res.status_code == 409
    assert "Apply workflow" in res.json()["detail"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/applications/a-1/otp"),
        ("post", "/api/applications/a-1/fill"),
        ("get", "/api/applications/a-1/fill"),
        ("post", "/api/applications/run-daily"),
    ],
)
def test_retired_apply_routes_are_gone(client, method, path):
    """Superseded by Apply operations and the Workday handoff; the SPA no longer calls them."""
    c, _q = client
    res = c.request(method.upper(), path)
    assert res.status_code in {404, 405}
