"""Email updates over HTTP (`routes/mail_updates.py`, `apply/funnel/mail_inbox.py`)."""

from __future__ import annotations

from resume_tailor.apply.funnel import mail_inbox, store_models
from resume_tailor.apply.funnel import store as apply_store


def _row(key, company, status="submitted", **extra):
    history = [store_models.StatusChange(status=status, at="2026-09-20T12:00:00+00:00")]
    return store_models.Application(
        source="t", source_job_id=key, company=company, role="Data Analyst Intern",
        status=status, status_history=history, **extra,
    )


def _mail(message_id, sender, subject, body=""):
    return {"message_id": message_id, "sender": sender, "subject": subject,
            "date": "Tue, 20 Oct 2026 09:15:00 -0700", "body": body}


MESSAGES = [
    _mail("m-reject", "Acme <jobs@acme.com>", "Your application to Acme",
          "Unfortunately, we will not be moving forward with your application."),
    _mail("m-invite", "Globex Talent <talent@globex.com>", "Interview invitation",
          "We'd like to invite you to a phone interview."),
    _mail("m-unclear", "no-reply@greenhouse-mail.io", "Thanks for applying",
          "Thank you for applying. We received your application."),
    _mail("m-news", "alerts@jobs.example", "Jobs picked for you", "New jobs for you today."),
]


def test_emails_become_proposals_and_nothing_is_recorded_until_accepted(client):
    c, _q = client
    apply_store.save_all({"acme": _row("acme", "Acme"), "globex": _row("globex", "Globex")})
    result = c.post("/api/mail/messages", json={"messages": MESSAGES}).json()
    assert (result["matched"], result["unclear"], result["ignored"]) == (2, 1, 1)
    assert result["pending"] == 3
    assert apply_store.get("acme").outcome_events == []

    again = c.post("/api/mail/messages", json={"messages": MESSAGES}).json()
    assert again["already_seen"] == 4 and again["pending"] == 3

    proposals = {p["message_id"]: p for p in c.get("/api/mail/proposals").json()["proposals"]}
    rejected = proposals["m-reject"]
    assert (rejected["signal"], rejected["app_id"], rejected["company"]) == ("rejected", "acme", "Acme")
    assert rejected["excerpt"].startswith("Unfortunately")

    accepted = c.post(f"/api/mail/proposals/{rejected['id']}/accept", json={}).json()
    assert accepted["state"] == "accepted"
    event = apply_store.get("acme").outcome_events[0]
    assert (event.type, event.occurred_on, event.source) == ("rejected", "2026-10-20", "mcp")
    assert event.note == "From email “Your application to Acme”"
    assert c.post(f"/api/mail/proposals/{rejected['id']}/accept", json={}).status_code == 409

    unclear = proposals["m-unclear"]
    assert unclear["app_id"] is None and unclear["signal"] == "sent"
    dismissed = c.post(f"/api/mail/proposals/{unclear['id']}/dismiss").json()
    assert dismissed["state"] == "dismissed"
    assert [p["message_id"] for p in c.get("/api/mail/proposals").json()["proposals"]] == ["m-invite"]


def test_an_unclear_email_is_assigned_and_an_acknowledgement_confirms_a_send(client):
    c, _q = client
    apply_store.save_all({"u": _row("u", "Initech", status="submit_unconfirmed")})
    c.post("/api/mail/messages", json={"messages": [MESSAGES[2]]})
    proposal = c.get("/api/mail/proposals").json()["proposals"][0]
    assert c.post(f"/api/mail/proposals/{proposal['id']}/accept", json={}).status_code == 409
    done = c.post(f"/api/mail/proposals/{proposal['id']}/accept", json={"app_id": "u"})
    assert done.status_code == 200
    row = apply_store.get("u")
    assert row.status == "submitted"
    assert row.status_history[-1].note == "Confirmed by email: Thanks for applying"
    assert not row.attempts[-1].confirmed  # the app did not upload these files itself


def test_an_acknowledgement_for_a_row_already_sent_changes_nothing(client):
    c, _q = client
    apply_store.save_all({"s": _row("s", "Initech")})
    c.post("/api/mail/messages", json={"messages": [MESSAGES[2]]})
    proposal = c.get("/api/mail/proposals").json()["proposals"][0]
    done = c.post(f"/api/mail/proposals/{proposal['id']}/accept", json={"app_id": "s"})
    assert done.status_code == 200 and done.json()["state"] == "accepted"
    assert len(apply_store.get("s").status_history) == 1


def test_an_unmatched_email_offers_every_open_application(client):
    c, _q = client
    apply_store.save_all({
        "b": _row("b", "Globex"), "a": _row("a", "Acme"),
        "x": _row("x", "Hooli", status="discovered"),
    })
    c.post("/api/mail/messages", json={"messages": [MESSAGES[2]]})
    proposal = c.get("/api/mail/proposals").json()["proposals"][0]
    assert [o["company"] for o in proposal["options"]] == ["Acme", "Globex"]


def test_the_search_plan_names_open_companies_and_never_only_the_inbox(client):
    c, _q = client
    closed = store_models.OutcomeEvent(id="r", type="rejected", occurred_on="2026-10-01",
                                       recorded_at="2026-10-01T00:00:00+00:00")
    apply_store.save_all({
        "a": _row("a", "Acme \"Labs\""),
        "b": _row("b", "Globex", outcome_events=[closed]),
        "c": _row("c", "Hooli", status="discovered"),
    })
    plan = c.get("/api/mail/search-plan").json()
    assert plan["companies"] == ['Acme "Labs"']
    assert '"Acme Labs"' in plan["query"] and "Globex" not in plan["query"]
    assert "-in:sent -in:drafts" in plan["query"] and "in:inbox" not in plan["query"]
    assert plan["query"].startswith(f"after:{plan['since'].replace('-', '/')} ")
    assert "from:greenhouse-mail.io" in plan["query"]


def test_the_inbox_keeps_only_a_short_cleaned_excerpt(client):
    c, _q = client
    apply_store.save_all({"acme": _row("acme", "Acme")})
    body = "Unfortunately we will not be moving forward.​ " + "x" * 2000
    c.post("/api/mail/messages", json={"messages": [_mail("m", "jobs@acme.com", "Acme", body)]})
    proposal = mail_inbox.pending()[0]
    assert len(proposal.excerpt) <= mail_inbox.EXCERPT_CHARS + 1
    assert "​" not in proposal.excerpt
