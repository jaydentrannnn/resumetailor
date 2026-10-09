"""Hermetic tests for apply API routes (profile, applications list, browser status)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply.answers import profile as profile_mod
from resume_tailor.apply.funnel import operations as operations_mod
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models
from resume_tailor.apply.funnel.daily_progress import FindProgress
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.app import app
from resume_tailor.web.jobs import JobQueue
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


@pytest.mark.parametrize("endpoint", ["start", "list", "detail"])
def test_find_operation_api_preserves_measured_progress(client, monkeypatch, endpoint):
    c, _q = client
    operation = operations_mod.ApplyOperation(
        operation_id="find-progress", action="find", state="running",
        find_progress=FindProgress(phase="processing", processed=3, total=8, current="Acme"),
    )
    monkeypatch.setattr(operations_mod, "start", lambda _body: operation)
    monkeypatch.setattr(operations_mod, "list_recent", lambda: [operation])
    monkeypatch.setattr(operations_mod, "get", lambda _id: operation)
    if endpoint == "start":
        response = c.post("/api/applications/operations", json={
            "action": "find", "model_provider": "ollama", "model_name": "test",
        })
    else:
        path = "/api/applications/operations" + ("/find-progress" if endpoint == "detail" else "")
        response = c.get(path)
    assert response.status_code == (202 if endpoint == "start" else 200)
    body = response.json()[0] if endpoint == "list" else response.json()
    assert body["find_progress"] == {
        "phase": "processing", "processed": 3, "total": 8, "current": "Acme",
    }


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
        "a": store_models.Application(source="t", source_job_id="a", company="A", role="R",
                                     fill=store_models.FillResult(missing_profile=[met])),
        "b": store_models.Application(source="t", source_job_id="b", company="B", role="R"),
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
    apply_store.save_all(
        {
            "a": store_models.Application(
                source="simplify",
                source_job_id="a",
                company="Acme",
                role="Engineer",
                status="submitted",
            ),
            "b": store_models.Application(
                source="simplify", source_job_id="b", company="Beta", role="Designer"
            ),
        }
    )
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
    assert c.get("/api/applications/a").json()["application"]["status"] == "jd_fetched"


def test_undo_submitted_route_conflicts_and_success(client):
    c, _q = client
    assert c.post("/api/applications/unknown/undo-submitted").status_code == 404
    row = store_models.Application(
        source="test", source_job_id="one", company="Acme", role="Engineer", job_id="run-1"
    )
    apply_store.set_status(row, "ready")
    apply_store.set_status(row, "submitted")
    apply_store.upsert(row)
    assert c.post("/api/applications/one/undo-submitted").status_code == 409
    c.post("/api/applications/archive", json={"application_ids": ["one"], "archived": False})
    # Restore already undoes the mark, so mark again while the row is active.
    row = apply_store.get("one")
    row.status = "submitted"
    apply_store.upsert(row)
    response = c.post("/api/applications/one/undo-submitted")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["status_at"]
    assert c.post("/api/applications/one/undo-submitted").status_code == 409


def test_screened_out_row_moves_from_working_to_archived_listing(client):
    c, _q = client
    row = store_models.Application(
        source="simplify", source_job_id="screened", company="Acme", role="Intern"
    )
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
    apply_store.save_all(
        {
            "a": store_models.Application(
                source="simplify", source_job_id="a", company="Acme", role="Engineer"
            )
        }
    )
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
        f"job-{i}": store_models.Application(
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


def test_browser_status_reports_launch_state(client, monkeypatch):
    """The status names the state, what's installed, and the saved choice."""
    from resume_tailor.apply.driver import browser as browser_mod
    from resume_tailor.apply.driver import browser_launch

    c, _q = client
    monkeypatch.setattr(browser_launch, "can_launch", lambda: True)
    monkeypatch.setattr(browser_launch, "_port_in_use", lambda port: False)
    monkeypatch.setattr(browser_launch, "_debug_port", lambda: 9222)
    monkeypatch.setattr(
        browser_launch, "installed_browsers",
        lambda: {"edge": False, "chrome": True, "comet": False},
    )
    monkeypatch.setattr(
        browser_mod, "browser_status", lambda: browser_mod.BrowserStatus(reachable=False)
    )
    body = c.get("/api/browser/status").json()
    assert body["state"] == "idle"
    assert body["can_launch"] is True
    assert body["installed"] == {"edge": False, "chrome": True, "comet": False}
    assert (body["selected"], body["resolved"]) == (None, "chrome")


def test_browser_launch_route_reports_failure_as_status(client, monkeypatch):
    """A failed launch is a 200 with the reason, never a 500."""
    from resume_tailor.apply.driver import browser_launch

    c, _q = client

    def _fail():
        raise RuntimeError("Port 9222 is used by another program")

    monkeypatch.setattr(browser_launch, "ensure_browser", _fail)
    res = c.post("/api/browser/launch")
    assert res.status_code == 200
    assert "reachable" in res.json()


@pytest.mark.parametrize(("ids", "expected"), [
    ({"tab-b", "tab-a"}, {"reachable": True, "target_ids": ["tab-a", "tab-b"]}),
    (set(), {"reachable": True, "target_ids": []}),
    (None, {"reachable": False, "target_ids": []}),
])
def test_open_tabs_route_separates_no_tabs_from_unknown(client, monkeypatch, ids, expected):
    """An unreachable browser is "unknown", never "every tab closed"."""
    from resume_tailor.apply.driver import browser as browser_mod
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


def _stored_app(source_job_id: str, status: str) -> store_models.Application:
    return apply_store.upsert(
        store_models.Application(
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
    from resume_tailor.apply.funnel.screen import ScreenResult

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


def test_application_list_answers_304_when_unchanged(client):
    c, _ = client
    first = c.get("/api/applications?limit=50")
    etag = first.headers["etag"]
    again = c.get("/api/applications?limit=50", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    apply_store.upsert(
        store_models.Application(source="s", source_job_id="new", company="N", role="R")
    )
    changed = c.get("/api/applications?limit=50", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag
    assert changed.json()["total"] == first.json()["total"] + 1


def test_daily_run_now_starts_the_pass_or_refuses_while_busy(client, tmp_path, monkeypatch):
    """Apply settings → Run now starts the nightly pass through the scheduler's own seams."""
    from resume_tailor.web import app as web_app

    c, _q = client
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    started: list[bool] = []
    monkeypatch.setattr(web_app, "_start_daily_run", lambda: started.append(True))
    monkeypatch.setattr(web_app, "_apply_busy", lambda: False)
    res = c.post("/api/applications/daily-run")
    assert res.status_code == 202
    assert started == [True]
    assert res.json()["scheduler"]["last_started_at"]

    monkeypatch.setattr(web_app, "_apply_busy", lambda: True)
    res = c.post("/api/applications/daily-run")
    assert res.status_code == 409
    assert started == [True]


def test_notes_route_saves_only_the_notes(client):
    """The detail page's Notes tab writes `notes` and nothing else, archived or not."""
    c, _q = client
    apply_store.save_all({
        "a": store_models.Application(
            source="simplify", source_job_id="a", company="Acme", role="Analyst", status="ready"
        ),
    })
    res = c.put("/api/applications/a/notes", json={"notes": "Recruiter: Sam, follow up Friday"})
    assert res.status_code == 200
    stored = apply_store.get("a")
    assert stored.notes == "Recruiter: Sam, follow up Friday"
    assert stored.status == "ready"
    assert c.put("/api/applications/zzz/notes", json={"notes": "x"}).status_code == 404
    assert c.put("/api/applications/a/notes", json={"notes": "x" * 20_001}).status_code == 422


def test_transcript_upload_is_server_owned(client, tmp_path):
    """Only the upload route sets `transcript_path`; a PUT can't point it elsewhere."""
    c, _q = client
    bad = c.post("/api/applicant-profile/transcript", files={"file": ("t.txt", b"hello", "text/plain")})
    assert bad.status_code == 422
    res = c.post(
        "/api/applicant-profile/transcript",
        files={"file": ("t.pdf", b"%PDF-1.4 stub", "application/pdf")},
    )
    assert res.status_code == 200
    stored = res.json()["profile"]["transcript_path"]
    assert Path(stored).read_bytes().startswith(b"%PDF")

    profile = res.json()["profile"]
    profile["transcript_path"] = "/etc/passwd"
    put = c.put("/api/applicant-profile", json={"profile": profile})
    assert put.json()["profile"]["transcript_path"] == stored

    gone = c.delete("/api/applicant-profile/transcript")
    assert gone.json()["profile"]["transcript_path"] == ""
    assert not Path(stored).exists()


def test_portfolio_upload_is_server_owned_and_separate(client):
    c, _q = client
    too_big = b"%PDF" + b"0" * (10 * 1024 * 1024)
    big = c.post("/api/applicant-profile/portfolio", files={"file": ("p.pdf", too_big, "application/pdf")})
    assert big.status_code == 413
    res = c.post(
        "/api/applicant-profile/portfolio",
        files={"file": ("p.pdf", b"%PDF-1.4 stub", "application/pdf")},
    )
    assert res.status_code == 200
    profile = res.json()["profile"]
    stored = profile["portfolio_path"]
    assert Path(stored).name == "portfolio.pdf"
    assert profile["transcript_path"] == ""

    profile["portfolio_path"] = "/etc/passwd"
    put = c.put("/api/applicant-profile", json={"profile": profile})
    assert put.json()["profile"]["portfolio_path"] == stored

    gone = c.delete("/api/applicant-profile/portfolio")
    assert gone.json()["profile"]["portfolio_path"] == ""
    assert not Path(stored).exists()


def test_sources_status_shape_and_missing_file(client, tmp_path, monkeypatch):
    """No run yet (no file) is an empty result, not an error."""
    c, _q = client
    monkeypatch.setattr(config, "SOURCE_STATUS_PATH", tmp_path / "source_status.json")
    assert c.get("/api/apply/sources/status").json() == {"sources": {}, "last_run_at": None}


def test_sources_status_serves_the_recorded_entries(client, tmp_path, monkeypatch):
    c, _q = client
    path = tmp_path / "source_status.json"
    monkeypatch.setattr(config, "SOURCE_STATUS_PATH", path)
    entry = {"found": 4, "kept": 2, "error": None, "at": "2026-09-29T10:00:00+00:00"}
    failed = {"found": 0, "kept": 0, "error": "could not reach api.adzuna.com", "at": entry["at"]}
    path.write_text(
        json.dumps({"sources": {"a": entry, "b": failed}, "last_run_at": entry["at"]}),
        encoding="utf-8",
    )
    assert c.get("/api/apply/sources/status").json() == {
        "sources": {"a": entry, "b": failed}, "last_run_at": entry["at"],
    }


@pytest.mark.parametrize("content", ["{not json", "[]", '{"sources": []}', '{"sources": {"a": {"found": "x"}}}'])
def test_sources_status_tolerates_a_corrupt_file(client, tmp_path, monkeypatch, content):
    c, _q = client
    path = tmp_path / "source_status.json"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(config, "SOURCE_STATUS_PATH", path)
    res = c.get("/api/apply/sources/status")
    assert res.status_code == 200
    assert res.json() == {"sources": {}, "last_run_at": None}


def test_profile_response_flags_and_merges_duplicate_custom_answers(client, tmp_path, monkeypatch):
    c, _q = client
    monkeypatch.setattr(profile_mod.config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    body = c.get("/api/applicant-profile").json()
    body["profile"]["custom_answers"] = {"are you at least 18 years of age": "Yes"}
    saved = c.put("/api/applicant-profile", json={"profile": body["profile"]}).json()
    assert saved["custom_answer_duplicates"] == {"are you at least 18 years of age": "over_18"}

    merged = c.post(
        "/api/applicant-profile/merge-custom-answer", json={"question": "are you at least 18 years of age"}
    ).json()
    assert merged["profile"]["over_18"] is True
    assert merged["profile"]["custom_answers"] == {}
    assert merged["custom_answer_duplicates"] == {}

    missing = c.post("/api/applicant-profile/merge-custom-answer", json={"question": "nope"})
    assert missing.status_code == 404


def test_profile_options_are_served(client):
    c, _q = client
    options = c.get("/api/reference/profile-options").json()
    assert {"countries", "subdivisions", "pronouns", "genders", "races", "race_details", "disability"} <= set(options)
    assert "High school diploma" in options["education_levels"]
    assert options["education_level_aliases"]["bachelors"] == "Bachelor's degree"


@pytest.mark.parametrize("qualification", ["Bachelors", "Higher National Diploma", ""])
def test_completed_education_survives_profile_roundtrip(client, qualification):
    c, _q = client
    profile = c.get("/api/applicant-profile").json()["profile"]
    profile["highest_education_obtained"] = qualification
    assert c.put("/api/applicant-profile", json={"profile": profile}).status_code == 200
    loaded = c.get("/api/applicant-profile").json()["profile"]
    assert loaded["highest_education_obtained"] == qualification
    loaded["earliest_start"] = "2027-06-01"
    assert c.put("/api/applicant-profile", json={"profile": loaded}).status_code == 200
    assert c.get("/api/applicant-profile").json()["profile"]["highest_education_obtained"] == qualification
