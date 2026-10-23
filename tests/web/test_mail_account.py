"""The email account the app checks itself (`routes/mail_account.py`) and what the
Tracker shows of it (`routes/tracker.py`, `routes/mail_updates.py` undo)."""

from __future__ import annotations

import threading

from resume_tailor.apply.funnel import mail_imap, mail_inbox, mail_sync, store_models
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.web.routes import mail_account

ACCOUNT = {"host": "mail.example.com", "port": 993, "username": "me@example.com"}


def _row(key, company, status="submitted"):
    history = [store_models.StatusChange(status=status, at="2026-09-20T12:00:00+00:00")]
    return store_models.Application(
        source="t", source_job_id=key, company=company, role="Data Analyst Intern",
        status=status, status_history=history,
    )


def test_the_password_is_saved_but_never_sent_back(client):
    c, _q = client
    assert c.get("/api/mail/account").json()["password_set"] is False
    assert c.put("/api/mail/account", json=ACCOUNT).status_code == 422  # no password yet
    saved = c.put("/api/mail/account", json={**ACCOUNT, "password": "hunter2-secret",
                                            "every_hours": 6, "auto_close": True})
    assert saved.status_code == 200
    body = saved.json()
    assert "hunter2-secret" not in saved.text and "password" not in body
    assert (body["host"], body["password_set"], body["every_hours"], body["auto_close"]) == (
        "mail.example.com", True, 6, True)
    assert mail_sync.password() == "hunter2-secret"
    assert "hunter2-secret" not in mail_sync.path().read_text(encoding="utf-8")

    # An empty password keeps the saved one; a different mailbox starts reading over.
    mail_sync.update(lambda s: setattr(s, "last_checked", "2026-10-22T09:00:00+00:00"))
    kept = c.put("/api/mail/account", json={**ACCOUNT, "every_hours": 3}).json()
    assert kept["password_set"] and kept["last_checked"] == "2026-10-22T09:00:00+00:00"
    moved = c.put("/api/mail/account", json={**ACCOUNT, "username": "other@example.com"})
    assert moved.json()["last_checked"] == ""

    assert c.put("/api/mail/account", json={**ACCOUNT, "every_hours": 2}).status_code == 422
    assert c.put("/api/mail/account", json={**ACCOUNT, "host": "mail/../x"}).status_code == 422

    gone = c.delete("/api/mail/account").json()
    assert (gone["host"], gone["password_set"]) == ("", False)
    assert mail_sync.password() == ""


def test_test_connection_tells_a_refused_login_from_an_unreachable_server(client, monkeypatch):
    c, _q = client
    calls = []

    def fake_test(account, password):
        calls.append((account.host, password))
        if password == "wrong":
            raise mail_imap.MailAuthError("The mail server refused that username or password.")
        if account.host == "down.example":
            raise mail_imap.MailConnectError("Could not reach down.example on port 993.")
        return 4
    monkeypatch.setattr(mail_account.mail_imap, "test", fake_test)

    assert c.post("/api/mail/account/test", json={}).status_code == 422
    ok = c.post("/api/mail/account/test", json={**ACCOUNT, "password": "pw"})
    assert ok.json() == {"folders": 4}
    refused = c.post("/api/mail/account/test", json={**ACCOUNT, "password": "wrong"})
    assert refused.status_code == 409 and "refused" in refused.json()["detail"]
    down = c.post("/api/mail/account/test",
                  json={**ACCOUNT, "host": "down.example", "password": "pw"})
    assert down.status_code == 502

    # With nothing typed, the saved account and password are used.
    c.put("/api/mail/account", json={**ACCOUNT, "password": "saved-pw"})
    assert c.post("/api/mail/account/test", json={}).json() == {"folders": 4}
    assert calls[-1] == ("mail.example.com", "saved-pw")


def test_check_now_starts_one_check_at_a_time(client, monkeypatch):
    c, _q = client
    assert c.post("/api/mail/account/check").status_code == 409  # no account
    c.put("/api/mail/account", json={**ACCOUNT, "password": "pw"})
    release, started = threading.Event(), threading.Event()

    def slow_fetch(*_a, **_k):
        started.set()
        release.wait(5)
        return []
    monkeypatch.setattr(mail_sync.mail_imap, "fetch", slow_fetch)

    first = c.post("/api/mail/account/check")
    assert first.status_code == 200 and first.json()["running"] is True
    assert started.wait(5)
    assert c.post("/api/mail/account/check").status_code == 409
    release.set()
    for _ in range(100):
        if not mail_sync.running():
            break
        threading.Event().wait(0.05)
    view = c.get("/api/mail/account").json()
    assert view["running"] is False and view["last_checked"] and view["last_error"] == ""


def test_the_tracker_shows_the_mailbox_and_the_automatic_closes_with_undo(client):
    c, _q = client
    board = c.get("/api/tracker").json()
    assert board["mail"]["configured"] is False and board["auto_closed"] == []

    apply_store.save_all({"acme": _row("acme", "Acme")})
    c.put("/api/mail/account", json={**ACCOUNT, "password": "pw"})
    mail_inbox.ingest([mail_inbox.IncomingMail(
        message_id="r", sender="Acme <jobs@acme.com>", subject="Your application",
        date="Tue, 20 Oct 2026 09:15:00 -0700",
        body="Thank you for applying to the Data Analyst Intern role. Unfortunately, we "
             "will not be moving forward with your application.",
    )], list(apply_store.rows_view().values()))
    assert c.get("/api/mail/account").json()["confident_pending"] == 1
    on = c.put("/api/mail/account", json={**ACCOUNT, "auto_close": True}).json()
    assert on["auto_close"] and on["confident_pending"] == 0  # closed when switched on
    assert apply_store.get("acme").outcome_events[0].source == "monitor"

    board = c.get("/api/tracker").json()
    assert (board["mail"]["configured"], board["mail"]["username"]) == (True, "me@example.com")
    closed = board["auto_closed"]
    assert [(p["company"], p["auto"], p["stage"]) for p in closed] == [("Acme", True, "Rejected")]

    undone = c.post(f"/api/mail/proposals/{closed[0]['id']}/undo")
    assert undone.status_code == 200 and undone.json()["state"] == "pending"
    assert c.get("/api/tracker").json()["auto_closed"] == []
    assert c.post(f"/api/mail/proposals/{closed[0]['id']}/undo").status_code == 409
    assert c.post("/api/mail/proposals/nope/undo").status_code == 404
