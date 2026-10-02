"""Browser-extension pairing, its lane through the request gate, and page capture (P4-X)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.apply.funnel import daily, daily_retry, daily_row_run, daily_rows, store
from resume_tailor.apply.funnel import operations as apply_operations
from resume_tailor.web import extension
from resume_tailor.web.app import app as web_app

_ORIGIN = {"origin": "chrome-extension://abcdefghijklmnop"}
_JD = (
    "About the role. You will build financial models, analyze company performance and "
    "present findings to the team. Requirements: Excel, PowerPoint and strong written "
    "communication. Experience with valuation is a plus. We offer mentorship and a "
    "summer program for students graduating in 2027. "
) * 2


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    with TestClient(web_app) as test_client:
        yield test_client


def _pair(client: TestClient) -> dict[str, str]:
    code = client.post("/api/extension-pairings/code").json()["code"]
    response = client.post(
        "/api/extension/pair/complete", json={"code": code, "label": "Chrome"}, headers=_ORIGIN
    )
    assert response.status_code == 200, response.text
    return {**_ORIGIN, extension.HEADER_NAME: response.json()["token"]}


# --- pairing store ------------------------------------------------------------------


def test_code_is_single_use_and_token_is_stored_hashed():
    code = extension.start_pairing()["code"]
    assert len(code) == 6 and code.isdigit()
    pairing_id, token = extension.complete_pairing(code, "Edge")
    assert extension.verify_token(token) == pairing_id
    assert token not in extension.store_path().read_text(encoding="utf-8")
    with pytest.raises(extension.PairingError, match="No pairing code"):
        extension.complete_pairing(code)
    assert extension.list_pairings()[0]["label"] == "Edge"
    assert "token_sha256" not in extension.list_pairings()[0]


def test_code_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(extension, "_clock", lambda: now[0])
    code = extension.start_pairing()["code"]
    now[0] += extension.CODE_TTL + 1
    with pytest.raises(extension.PairingError, match="expired"):
        extension.complete_pairing(code)


def test_wrong_guesses_void_the_code():
    code = extension.start_pairing()["code"]
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    for _ in range(extension.MAX_ATTEMPTS - 1):
        with pytest.raises(extension.PairingError, match="not right"):
            extension.complete_pairing(wrong)
    with pytest.raises(extension.PairingError, match="Too many"):
        extension.complete_pairing(wrong)
    with pytest.raises(extension.PairingError, match="No pairing code"):
        extension.complete_pairing(code)


def test_a_new_code_replaces_the_old_one():
    first = extension.start_pairing()["code"]
    second = extension.start_pairing()["code"]
    if first != second:
        with pytest.raises(extension.PairingError):
            extension.complete_pairing(first)
    extension.complete_pairing(second)


def test_revoke_and_unreadable_store(tmp_path):
    _id, token = extension.complete_pairing(extension.start_pairing()["code"])
    assert extension.revoke(_id)
    assert not extension.revoke(_id)
    assert extension.verify_token(token) is None
    extension.store_path().write_text("{not json", encoding="utf-8")
    assert extension.list_pairings() == []
    assert extension.verify_token("anything") is None


# --- request gate -------------------------------------------------------------------


def test_extension_routes_need_a_paired_token(client):
    assert client.get("/api/extension/status", headers=_ORIGIN).status_code == 401
    bad = {**_ORIGIN, extension.HEADER_NAME: "nope"}
    assert client.get("/api/extension/status", headers=bad).json()["error"] == "extension_auth"
    headers = _pair(client)
    status = client.get("/api/extension/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["app"] == "resumetailor"


def test_extension_origin_writes_pass_only_on_the_extension_lane(client):
    headers = _pair(client)
    # The same origin is still refused on the app's own routes.
    refused = client.put("/api/automation", json={"paused": True}, headers=headers)
    assert refused.status_code == 403
    response = client.post(
        "/api/extension/capture",
        json={"url": "https://boards.greenhouse.io/acme/jobs/123", "jd_text": _JD},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_web_pages_cannot_use_the_extension_lane(client):
    headers = _pair(client)
    evil = {**headers, "origin": "https://evil.example"}
    assert client.get("/api/extension/status", headers=evil).status_code == 403
    code = client.post("/api/extension-pairings/code").json()["code"]
    response = client.post(
        "/api/extension/pair/complete", json={"code": code}, headers={"origin": "null"}
    )
    assert response.status_code == 403


def test_extension_lane_works_with_the_session_token_on(client, monkeypatch):
    headers = _pair(client)
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "s3cret")
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/extension/status", headers=headers).status_code == 200
    # Pairing management stays behind the app's own session.
    assert client.get("/api/extension-pairings").status_code == 401
    assert (
        client.get("/api/extension-pairings", headers={"x-rt-token": "s3cret"}).status_code == 200
    )


def test_pairing_routes(client):
    headers = _pair(client)
    rows = client.get("/api/extension-pairings").json()
    assert [r["label"] for r in rows] == ["Chrome"]
    assert client.delete(f"/api/extension-pairings/{rows[0]['id']}").status_code == 204
    assert client.get("/api/extension/status", headers=headers).status_code == 401
    assert client.delete(f"/api/extension-pairings/{rows[0]['id']}").status_code == 404
    wrong = client.post("/api/extension/pair/complete", json={"code": "000000"}, headers=_ORIGIN)
    assert wrong.status_code == 400


# --- capture ------------------------------------------------------------------------


def test_capture_creates_a_tracked_row_and_dedupes(client):
    headers = _pair(client)
    body = {
        "url": "https://www.linkedin.com/jobs/view/analyst-at-acme-3812345678",
        "company": "Acme",
        "role": "Summer Analyst",
        "location": "New York, NY",
        "jd_text": _JD,
    }
    first = client.post("/api/extension/capture", json=body, headers=headers).json()
    assert first["result"] == "created"
    row = first["application"]
    assert row["id"] == "linkedin:jobs:3812345678"
    assert row["ats"] == "linkedin"
    assert row["status"] == "jd_fetched"
    stored = store.get(row["id"])
    assert stored is not None and stored.source == "extension"
    assert Path(stored.jd_text_path).read_text(encoding="utf-8").startswith("About the role")

    again = client.post("/api/extension/capture", json=body, headers=headers).json()
    assert again["result"] == "exists"
    assert len(store.load_all()) == 1

    lookup = client.get(
        "/api/extension/lookup", params={"url": body["url"]}, headers=headers
    ).json()
    assert lookup["assist_only"] is True
    assert lookup["application"]["id"] == row["id"]


def test_capture_keys_on_the_external_apply_url(client):
    headers = _pair(client)
    body = {
        "url": "https://www.linkedin.com/jobs/view/3812345678",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/4455",
        "company": "Acme",
        "role": "Analyst",
        "jd_text": _JD,
    }
    row = client.post("/api/extension/capture", json=body, headers=headers).json()["application"]
    assert row["id"] == "greenhouse:acme:4455"
    assert row["ats"] == "greenhouse"
    # The same job seen later on its own board is the same row.
    later = client.post(
        "/api/extension/capture",
        json={"url": "https://boards.greenhouse.io/acme/jobs/4455", "jd_text": _JD},
        headers=headers,
    ).json()
    assert later["result"] == "exists"


def test_capture_rejects_a_login_wall(client):
    headers = _pair(client)
    response = client.post(
        "/api/extension/capture",
        json={"url": "https://www.linkedin.com/jobs/view/1", "jd_text": "Sign in to view"},
        headers=headers,
    )
    assert response.status_code == 422
    assert "Send selection" in response.json()["detail"]
    assert store.load_all() == {}


def test_capture_runs_the_no_llm_prefilter(client):
    headers = _pair(client)
    body = {
        "url": "https://jobs.lever.co/acme/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab",
        "company": "Acme",
        "role": "Analyst",
        "jd_text": _JD + " An active security clearance is required.",
    }
    row = client.post("/api/extension/capture", json=body, headers=headers).json()["application"]
    assert row["status"] == "screened_out"
    assert row["screen_reasons"]


def test_prepare_reuses_the_captured_text():
    app = store.Application(
        source="extension",
        source_job_id="ext-1",
        company="Acme",
        role="Analyst",
        posting_url="https://www.linkedin.com/jobs/view/1",
        final_url="https://www.linkedin.com/jobs/view/1",
        ats="linkedin",
    )
    app.jd_text_path = daily_rows._save_jd("ext-1", _JD)
    captured = daily_rows._captured_jd(app)
    assert captured is not None
    assert captured.method == "captured"
    assert captured.ats == "linkedin"
    assert captured.text == _JD

    other = app.model_copy(update={"source": "simplify"})
    assert daily_rows._captured_jd(other) is None


def test_prepare_and_fill_build_the_request_from_settings(client, monkeypatch):
    settings = {"defaults": {"apply": {"model_provider": "gemini", "model_name": "flash"}}}
    config.SETTINGS_PATH.write_text(json.dumps(settings), encoding="utf-8")
    headers = _pair(client)
    body = {"url": "https://boards.greenhouse.io/acme/jobs/9", "jd_text": _JD}
    row = client.post("/api/extension/capture", json=body, headers=headers).json()["application"]

    seen = []

    def _start(request):
        seen.append(request)
        return apply_operations.ApplyOperation(
            operation_id="op1", action=request.action, application_ids=request.application_ids
        )

    monkeypatch.setattr(apply_operations, "start", _start)
    response = client.post(f"/api/extension/applications/{row['id']}/prepare", headers=headers)
    assert response.status_code == 202, response.text
    response = client.post(f"/api/extension/applications/{row['id']}/fill", headers=headers)
    assert response.status_code == 202
    assert [r.action for r in seen] == ["prepare", "fill"]
    assert all(r.model_provider == "gemini" and r.model_name == "flash" for r in seen)
    assert all(r.auto_submit is False for r in seen)
    assert seen[0].application_ids == [row["id"]]

    missing = client.post("/api/extension/applications/nope/prepare", headers=headers)
    assert missing.status_code == 404

    def _busy(_request):
        raise RuntimeError("Apply operation x is already active")

    monkeypatch.setattr(apply_operations, "start", _busy)
    busy = client.post(f"/api/extension/applications/{row['id']}/fill", headers=headers)
    assert busy.status_code == 409


def _cards(*ids: str, site: str = "linkedin") -> list[dict[str, str]]:
    def url(job: str) -> str:
        if site == "linkedin":
            return f"https://www.linkedin.com/jobs/view/{job}/?trk=search"
        return f"https://www.indeed.com/viewjob?jk={job}"

    return [
        {"url": url(job), "job_id": job, "company": "Acme", "role": f"Analyst {job}", "site": site}
        for job in ids
    ]


# --- batch capture: stubs -----------------------------------------------------------


def test_capture_stubs_saves_cards_without_descriptions(client):
    headers = _pair(client)
    cards = [*_cards("111", "222"), {"url": "https://example.com/job/3", "site": "linkedin"}]
    body = client.post("/api/extension/capture-stubs", json={"cards": cards}, headers=headers).json()
    assert [r["result"] for r in body["results"]] == ["created", "created", "invalid"]
    stub = store.get("linkedin:jobs:111")
    assert stub is not None and stub.capture_stub and stub.status == "discovered"
    assert stub.posting_url == "https://www.linkedin.com/jobs/view/111/"  # tracking dropped
    assert stub.jd_text_path is None
    assert body["results"][0]["application"]["capture_stub"] is True

    again = client.post("/api/extension/capture-stubs", json={"cards": cards[:1]}, headers=headers)
    assert again.json()["results"][0]["result"] == "exists"
    assert len(store.load_all()) == 2

    # One screen of results per request.
    too_many = client.post(
        "/api/extension/capture-stubs",
        json={"cards": _cards(*[str(n) for n in range(1000, 1051)])},
        headers=headers,
    )
    assert too_many.status_code == 422
    # A card id that disagrees with its URL is not trusted.
    wrong = client.post(
        "/api/extension/capture-stubs",
        json={"cards": [{**_cards("333")[0], "job_id": "999"}]},
        headers=headers,
    )
    assert wrong.json()["results"][0]["result"] == "invalid"


def test_indeed_stub_keys_on_the_job_not_the_search_page(client):
    headers = _pair(client)
    card = {
        "url": "https://www.indeed.com/jobs?q=analyst&vjk=AbC123",
        "company": "Acme",
        "role": "Analyst",
        "site": "indeed",
    }
    client.post("/api/extension/capture-stubs", json={"cards": [card]}, headers=headers)
    stub = store.get("indeed:jobs:abc123")
    assert stub is not None and stub.posting_url == "https://www.indeed.com/viewjob?jk=abc123"


def test_lookup_batch_reports_queue_status(client):
    headers = _pair(client)
    client.post("/api/extension/capture-stubs", json={"cards": _cards("111")}, headers=headers)
    client.post(
        "/api/extension/capture",
        json={"url": "https://boards.greenhouse.io/acme/jobs/9", "jd_text": _JD},
        headers=headers,
    )
    urls = [
        "https://www.linkedin.com/jobs/search/?currentJobId=111&keywords=x",
        "https://boards.greenhouse.io/acme/jobs/9",
        "https://www.linkedin.com/jobs/view/404/",
    ]
    results = client.post(
        "/api/extension/lookup-batch", json={"urls": urls}, headers=headers
    ).json()["results"]
    assert [(r["exists"], r["stub"]) for r in results] == [(True, True), (True, False), (False, False)]
    assert results[0]["id"] == "linkedin:jobs:111" and results[0]["status"] == "discovered"
    assert results[1]["status"] == "jd_fetched"
    too_many = client.post(
        "/api/extension/lookup-batch", json={"urls": ["https://x.test"] * 51}, headers=headers
    )
    assert too_many.status_code == 422


def test_opening_a_stub_completes_it(client):
    headers = _pair(client)
    client.post("/api/extension/capture-stubs", json={"cards": _cards("111")}, headers=headers)
    # The user opens the job in the search page's detail pane.
    body = {
        "url": "https://www.linkedin.com/jobs/search/?currentJobId=111",
        "company": "Acme Inc",
        "role": "Summer Analyst",
        "location": "New York, NY",
        "jd_text": _JD,
        "apply_kind": "easy_apply",
    }
    done = client.post("/api/extension/capture", json=body, headers=headers).json()
    assert done["result"] == "completed"
    assert done["application"]["id"] == "linkedin:jobs:111"
    row = store.get("linkedin:jobs:111")
    assert row is not None and not row.capture_stub
    assert row.status == "jd_fetched"
    assert (row.role, row.location, row.apply_kind) == ("Summer Analyst", "New York, NY", "easy_apply")
    assert Path(row.jd_text_path).read_text(encoding="utf-8") == _JD.strip()
    assert len(store.load_all()) == 1
    # Once complete, the same page is simply tracked.
    again = client.post("/api/extension/capture", json=body, headers=headers).json()
    assert again["result"] == "exists"


def test_completed_stub_runs_the_prefilter(client):
    headers = _pair(client)
    client.post("/api/extension/capture-stubs", json={"cards": _cards("111")}, headers=headers)
    body = {
        "url": "https://www.linkedin.com/jobs/view/111/",
        "jd_text": _JD + " An active security clearance is required.",
    }
    done = client.post("/api/extension/capture", json=body, headers=headers).json()
    assert done["result"] == "completed"
    assert done["application"]["status"] == "screened_out"
    assert done["application"]["screen_reasons"]


def test_stub_completed_with_an_external_apply_link_keeps_its_key(client):
    headers = _pair(client)
    client.post("/api/extension/capture-stubs", json={"cards": _cards("111")}, headers=headers)
    body = {
        "url": "https://www.linkedin.com/jobs/view/111/",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/4455",
        "jd_text": _JD,
    }
    done = client.post("/api/extension/capture", json=body, headers=headers).json()
    app = done["application"]
    assert (done["result"], app["id"], app["ats"]) == ("completed", "linkedin:jobs:111", "greenhouse")
    assert app["apply_kind"] == "external"
    assert app["apply_url"] == "https://boards.greenhouse.io/acme/jobs/4455"
    # The ATS page now finds the same row.
    lookup = client.get(
        "/api/extension/lookup", params={"url": body["apply_url"]}, headers=headers
    ).json()
    assert lookup["application"]["id"] == "linkedin:jobs:111"


def test_capturing_the_ats_page_merges_into_the_board_row(client):
    headers = _pair(client)
    board = {
        "url": "https://www.linkedin.com/jobs/view/555/",
        "company": "Acme, Inc.",
        "role": "Summer Analyst (2027)",
        "jd_text": _JD,
        "apply_kind": "external",
    }
    created = client.post("/api/extension/capture", json=board, headers=headers).json()
    assert created["result"] == "created"
    assert created["application"]["apply_kind"] == "external"
    ats = {
        "url": "https://boards.greenhouse.io/acme/jobs/777",
        "company": "Acme",
        "role": "Summer Analyst",
        "jd_text": _JD,
    }
    merged = client.post("/api/extension/capture", json=ats, headers=headers).json()
    assert merged["result"] == "merged"
    assert merged["application"]["id"] == "linkedin:jobs:555"
    assert merged["application"]["apply_url"] == ats["url"]
    assert len(store.load_all()) == 1
    row = store.get("linkedin:jobs:555")
    assert row is not None and row.final_url == ats["url"] and row.ats == "greenhouse"
    assert row.posting_url == "https://www.linkedin.com/jobs/view/555/"
    # Captured again, the ATS page is the same tracked job, not a new one.
    again = client.post("/api/extension/capture", json=ats, headers=headers).json()
    assert (again["result"], again["application"]["id"]) == ("exists", "linkedin:jobs:555")
    # A second posting at the same company for the same role is not merged again.
    other = {**ats, "url": "https://boards.greenhouse.io/acme/jobs/778"}
    assert client.post("/api/extension/capture", json=other, headers=headers).json()["result"] == "created"


def test_ats_capture_completes_a_matching_stub(client):
    headers = _pair(client)
    cards = [{**_cards("111")[0], "company": "Acme", "role": "Analyst"}]
    client.post("/api/extension/capture-stubs", json={"cards": cards}, headers=headers)
    ats = {
        "url": "https://jobs.lever.co/acme/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab",
        "company": "Acme",
        "role": "Analyst",
        "jd_text": _JD,
    }
    merged = client.post("/api/extension/capture", json=ats, headers=headers).json()
    assert merged["result"] == "merged"
    row = store.get("linkedin:jobs:111")
    assert row is not None and not row.capture_stub and row.status == "jd_fetched"
    assert row.ats == "lever"


def test_board_capture_records_how_to_apply(client):
    headers = _pair(client)
    body = {"url": "https://www.indeed.com/viewjob?jk=abc", "jd_text": _JD, "apply_kind": "easy_apply"}
    row = client.post("/api/extension/capture", json=body, headers=headers).json()["application"]
    assert row["apply_kind"] == "easy_apply"
    # apply_kind only describes LinkedIn/Indeed pages.
    ats = {"url": "https://boards.greenhouse.io/acme/jobs/1", "jd_text": _JD, "apply_kind": "easy_apply"}
    other = client.post("/api/extension/capture", json=ats, headers=headers).json()["application"]
    assert other["apply_kind"] == "unknown"


def test_easy_apply_blocks_fill_and_stubs_block_prepare(client, monkeypatch):
    headers = _pair(client)
    body = {"url": "https://www.indeed.com/viewjob?jk=abc", "jd_text": _JD, "apply_kind": "easy_apply"}
    row = client.post("/api/extension/capture", json=body, headers=headers).json()["application"]
    monkeypatch.setattr(
        apply_operations,
        "start",
        lambda request: apply_operations.ApplyOperation(
            operation_id="op1", action=request.action, application_ids=request.application_ids
        ),
    )
    fill = client.post(f"/api/extension/applications/{row['id']}/fill", headers=headers)
    assert fill.status_code == 422 and "Indeed" in fill.json()["detail"]
    assert client.post(f"/api/extension/applications/{row['id']}/prepare", headers=headers).status_code == 202

    client.post("/api/extension/capture-stubs", json={"cards": _cards("111")}, headers=headers)
    stub = client.post("/api/extension/applications/linkedin:jobs:111/prepare", headers=headers)
    assert stub.status_code == 409 and "no description" in stub.json()["detail"]


def test_app_lists_captures_and_stubs(client):
    headers = _pair(client)
    client.post("/api/extension/capture-stubs", json={"cards": _cards("111")}, headers=headers)
    client.post(
        "/api/extension/capture",
        json={"url": "https://boards.greenhouse.io/acme/jobs/9", "jd_text": _JD},
        headers=headers,
    )
    other = store.Application(source="simplify", source_job_id="s1", company="B", role="C")
    store.upsert(other)
    rows = client.get("/api/extension-captures").json()
    assert {r["id"] for r in rows} == {"linkedin:jobs:111", "greenhouse:acme:9"}
    stubs = client.get("/api/extension-captures", params={"stubs_only": True}).json()
    assert [(r["id"], r["site"], r["posting_url"]) for r in stubs] == [
        ("linkedin:jobs:111", "linkedin", "https://www.linkedin.com/jobs/view/111/")
    ]
    # Links use the colon-free source id: a canonical key in a URL path breaks the SPA's
    # static-file fallback on Windows.
    assert stubs[0]["link_id"].startswith("ext-") and ":" not in stubs[0]["link_id"]
    assert client.get(f"/api/applications/{stubs[0]['link_id']}").status_code == 200
    # The regular application API carries the new fields too.
    listed = client.get("/api/applications").json()["applications"]
    assert {a["source_job_id"]: a["capture_stub"] for a in listed}[store.get("linkedin:jobs:111").source_job_id]


def test_daily_funnel_and_prepare_skip_stubs(client, monkeypatch):
    from resume_tailor.web.schemas import ApplySettings as Settings
    from tests.fixtures import synthetic_resume

    headers = _pair(client)
    client.post("/api/extension/capture-stubs", json={"cards": _cards("111")}, headers=headers)
    plain = store.Application(
        source="simplify", source_job_id="s1", company="B", role="C",
        posting_url="https://boards.greenhouse.io/b/jobs/1", canonical_key="greenhouse:b:1",
    )
    store.upsert(plain)
    stub = store.get("linkedin:jobs:111")
    assert stub is not None
    assert daily_retry.retry_kind(stub) is None
    with pytest.raises(RuntimeError, match="no description"):
        daily.prepare_application("linkedin:jobs:111", settings=Settings())

    processed: list[str] = []
    monkeypatch.setattr(daily_row_run, "_process_one", lambda row, **_kw: processed.append(row.job_id))
    monkeypatch.setattr(daily.data, "load", synthetic_resume)
    settings = Settings(enabled=True)
    settings.sources = []  # no discovery: only the rows already pending
    summary = daily.run_daily(settings=settings, log=lambda _m: None)
    assert not summary.already_running
    assert processed == ["s1"]
    assert store.get("linkedin:jobs:111").status == "discovered"


def test_status_counts_rows_that_need_you(client):
    headers = _pair(client)
    for n, status in enumerate(["awaiting_otp", "ready", "fill_failed"]):
        row = store.Application(
            source="t", source_job_id=f"r{n}", company="A", role="B", canonical_key=f"k{n}"
        )
        store.set_status(row, status)
        store.upsert(row)
    body = client.get("/api/extension/status", headers=headers).json()
    assert body["needs_you"] == 2
    assert body["paused"] is False
