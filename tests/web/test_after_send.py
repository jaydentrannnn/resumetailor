"""Interview prep, follow-up notes and "no reply" marks over HTTP (`routes/after_send.py`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from resume_tailor import config
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models
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
