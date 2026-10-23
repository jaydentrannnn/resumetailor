"""Interview prep, follow-up notes and "no reply" marks over HTTP (`routes/after_send.py`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from resume_tailor import config
from resume_tailor.apply.funnel import followup_due, outcomes, store_models
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.pipeline import followup_note, interview_prep


class _Reply:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _Client:
    def __init__(self, reply, seen):
        self.messages = self
        self._reply, self._seen = reply, seen

    def parse(self, **kwargs):
        self._seen.append(kwargs)
        return _Reply(self._reply)


def _sent(days_ago: int, key: str = "a", **extra) -> store_models.Application:
    at = (datetime.now(UTC) - timedelta(days=days_ago)).date().isoformat()
    return store_models.Application(
        source="t", source_job_id=key, company="Acme", role="Analyst", status="submitted",
        status_history=[store_models.StatusChange(status="submitted", at=f"{at}T12:00:00+00:00")],
        **extra,
    )


def _run(job_id: str = "run-1") -> None:
    run = config.OUTPUT_DIR / "jobs" / job_id
    run.mkdir(parents=True)
    (run / "bullets.json").write_text(json.dumps({"exp_b1": "Built the dashboard."}), "utf-8")


def test_prep_is_made_from_the_sent_files_saved_and_listed(client, monkeypatch):
    c, _q = client
    _run()
    apply_store.save_all({"a": _sent(12, job_id="run-1")})
    seen: list[dict] = []
    reply = interview_prep.PrepLLM(
        questions=[interview_prep.PrepQuestion(question="Why Acme?")], ask=["Team size?"])
    monkeypatch.setattr(interview_prep.llm, "client_for", lambda p: _Client(reply, seen))

    assert c.get("/api/applications/a/interview-prep").json() == {"preps": []}
    made = c.post("/api/applications/a/interview-prep", json={"stage": "behavioral"}).json()
    assert made["stage"] == "behavioral" and made["questions"][0]["question"] == "Why Acme?"
    assert made["based_on"].startswith("Latest prepared files")
    assert "Built the dashboard." in seen[0]["messages"][0]["content"]
    saved = c.get("/api/applications/a/interview-prep").json()["preps"]
    assert [p["stage"] for p in saved] == ["behavioral"]
    assert c.post("/api/applications/zz/interview-prep", json={"stage": "final"}).status_code == 404


def test_prep_needs_a_tailored_run_but_a_note_does_not(client, monkeypatch):
    c, _q = client
    apply_store.save_all({"a": _sent(12)})
    response = c.post("/api/applications/a/interview-prep", json={"stage": "technical"})
    assert response.status_code == 409
    reply = followup_note.FollowupLLM(body="Hello, I have 3 years of Rust.")
    monkeypatch.setattr(followup_note.llm, "client_for", lambda p: _Client(reply, []))
    note = c.post("/api/applications/a/follow-up", json={}).json()
    assert note["source"] == "template" and "Analyst position at Acme" in note["body"]


def test_a_follow_up_note_is_drafted_but_never_recorded(client, monkeypatch):
    c, _q = client
    _run()
    apply_store.save_all({"a": _sent(12, job_id="run-1")})
    reply = followup_note.FollowupLLM(subject="Checking in", body="Hello, I am still keen.")
    monkeypatch.setattr(followup_note.llm, "client_for", lambda p: _Client(reply, []))
    note = c.post("/api/applications/a/follow-up",
                  json={"kind": "follow_up", "channel": "email"}).json()
    assert (note["source"], note["subject"]) == ("llm", "Checking in")
    assert apply_store.get("a").outcome_events == []


def test_follow_ups_list_due_rows_and_no_reply_marks_only_stale_ones(client):
    c, _q = client
    apply_store.save_all({"a": _sent(70, "a"), "b": _sent(12, "b"), "c": _sent(3, "c")})
    listed = c.get("/api/applications/follow-ups").json()
    assert [r["application_id"] for r in listed["due"]] == ["a", "b"]
    assert [r["application_id"] for r in listed["stale"]] == ["a"]

    result = c.post("/api/applications/no-reply",
                    json={"application_ids": ["a", "b", "nope"]}).json()
    assert result["updated"] == ["a"]
    assert result["skipped"] == {
        "b": "Sent 12 days ago, under 60.", "nope": "Unknown application."}
    [event] = apply_store.get("a").outcome_events
    assert (event.type, event.note) == ("ghosted", "No reply 70 days after sending")
    assert apply_store.get("b").outcome_events == []
    assert c.get("/api/applications/follow-ups").json()["stale"] == []


def test_prep_refuses_to_save_after_a_profile_switch(client, monkeypatch, tmp_path):
    c, _q = client
    _run()
    apply_store.save_all({"a": _sent(12, job_id="run-1")})
    original_folder = config.APPLICATIONS_OUTPUT_DIR / "a" / "interview_prep"
    other_folder = tmp_path / "other-profile"
    reply = interview_prep.PrepLLM()

    class SwitchingClient(_Client):
        def parse(self, **kwargs):
            monkeypatch.setattr(config, "_ACTIVE_WORKSPACE_ID", "other-profile")
            monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", other_folder)
            return super().parse(**kwargs)

    monkeypatch.setattr(interview_prep.llm, "client_for", lambda p: SwitchingClient(reply, []))
    response = c.post("/api/applications/a/interview-prep", json={"stage": "technical"})
    assert response.status_code == 409
    assert not (original_folder / "technical.json").exists()
    assert not (other_folder / "a" / "interview_prep" / "technical.json").exists()


def test_a_saved_undated_timeline_keeps_detail_and_follow_ups_readable(client, monkeypatch):
    c, _q = client
    today = followup_due.today()
    app = _sent(70)
    outcomes.add_event(app, "employer_timeline", note="Waiting for the recruiter")
    apply_store.save_all({"a": app})
    # Read the persisted row, including the legacy null date, through both front doors.
    detail = c.get("/api/applications/a")
    assert detail.status_code == 200
    assert detail.json()["application"]["follow_up"]["stale"] is False
    assert c.get("/api/applications/follow-ups").json() == {"due": [], "stale": []}
    monkeypatch.setattr(followup_due, "today", lambda: today + timedelta(days=8))
    listed = c.get("/api/applications/follow-ups").json()
    assert [row["application_id"] for row in listed["due"]] == ["a"]


def test_bulk_no_reply_skips_an_old_application_with_a_pending_timeline(client):
    c, _q = client
    deadline = (followup_due.today() + timedelta(days=7)).isoformat()
    app = _sent(70)
    outcomes.add_event(app, "employer_timeline", occurred_on=deadline)
    apply_store.save_all({"a": app})
    result = c.post("/api/applications/no-reply", json={"application_ids": ["a"]})
    assert result.json() == {
        "updated": [], "skipped": {"a": f"The employer said to expect news by {deadline}."},
    }
    assert [e.type for e in apply_store.get("a").outcome_events] == ["employer_timeline"]


def test_the_report_downloads_as_one_html_file(client):
    c, _q = client
    apply_store.save_all({"a": _sent(30).model_copy(update={"company": "<Acme>"})})
    response = c.get("/api/applications/report.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="applications-report-'
    )
    assert "&lt;Acme&gt;" in response.text and "<Acme>" not in response.text
