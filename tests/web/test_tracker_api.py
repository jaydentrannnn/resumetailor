"""The Tracker board over HTTP (`routes/tracker.py`)."""

from __future__ import annotations

from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.apply.funnel import store_models

ARCHIVED = "2026-09-20T12:00:00+00:00"


def _row(key, company, status="submitted", archived_at=ARCHIVED):
    history = [store_models.StatusChange(status=status, at="2026-09-20T12:00:00+00:00")]
    return store_models.Application(
        source="t", source_job_id=key, company=company, role="Data Analyst Intern",
        status=status, status_history=history, archived_at=archived_at,
    )


def _mail(message_id, sender, subject, body):
    return {"message_id": message_id, "sender": sender, "subject": subject,
            "date": "Tue, 20 Oct 2026 09:15:00 -0700", "body": body}


def _seed():
    apply_store.save_all({
        "acme": _row("acme", "Acme"),
        "globex": _row("globex", "Globex"),
        "skip": _row("skip", "Hooli", status="skipped"),
        "live": _row("live", "Initech", status="submit_unconfirmed", archived_at=None),
    })


def test_the_board_lists_done_rows_with_their_email_updates(client):
    c, _q = client
    _seed()
    c.post("/api/mail/messages", json={"messages": [
        _mail("m1", "Acme <jobs@acme.com>", "Your application to Acme",
              "We'd like to invite you to a phone interview."),
        _mail("m2", "Initech <jobs@initech.com>", "Initech update",
              "Unfortunately, we will not be moving forward with your application."),
        _mail("m3", "no-reply@greenhouse-mail.io", "Interview invitation",
              "We'd like to invite you to a phone interview."),
    ]})
    board = c.get("/api/tracker").json()
    cards = {card["id"]: card for card in board["cards"]}
    assert set(cards) == {"acme", "globex", "skip"}
    assert board["counts"]["applied"] == 2 and board["counts"]["not_sent"] == 1
    assert [p["message_id"] for p in cards["acme"]["proposals"]] == ["m1"]
    tray = {p["message_id"]: p for p in board["unmatched"]}
    assert set(tray) == {"m2", "m3"}
    assert tray["m2"]["company"] == "Initech"  # matched, but not in Done
    assert board["last_synced"]


def test_a_move_records_events_and_undo_reverses_it(client):
    c, _q = client
    _seed()
    moved = c.post("/api/tracker/acme/move", json={"column": "interview"})
    assert moved.status_code == 200
    body = moved.json()
    assert body["card"]["column"] == "interview" and len(body["receipt"]["added"]) == 1
    [event] = apply_store.get("acme").outcome_events
    assert (event.type, event.note) == ("interview_invited", "Moved on the tracker")

    undone = c.post("/api/tracker/acme/undo", json={"receipt": body["receipt"]})
    assert undone.status_code == 200 and undone.json()["column"] == "applied"
    again = c.post("/api/tracker/acme/undo", json={"receipt": body["receipt"]})
    assert again.status_code == 409


def test_refused_moves_say_why(client):
    c, _q = client
    _seed()
    closed = c.post("/api/tracker/acme/move", json={"column": "closed"})
    assert closed.status_code == 409 and "why" in closed.json()["detail"]
    assert c.post("/api/tracker/skip/move", json={"column": "applied"}).status_code == 409
    assert c.post("/api/tracker/live/move", json={"column": "interview"}).status_code == 409
    assert c.post("/api/tracker/nope/move", json={"column": "interview"}).status_code == 404
    assert c.post("/api/tracker/acme/move", json={"column": "bogus"}).status_code == 422
    assert apply_store.get("acme").outcome_events == []
