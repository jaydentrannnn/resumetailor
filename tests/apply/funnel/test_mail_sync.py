"""The app's own mailbox check (`mail_sync.py`) and the automatic closes it records
(`mail_inbox.auto_close`, `undo_auto`, `mail_signals.confident`)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from resume_tailor import config
from resume_tailor.apply.funnel import mail_imap, mail_inbox, mail_sync, outcomes, store_models
from resume_tailor.apply.funnel import store as apply_store

ACCOUNT = mail_imap.MailAccount(host="mail.example.com", username="me@example.com")
REJECTION = ("Thank you for applying to the Data Analyst Intern role. Unfortunately, we "
             "will not be moving forward with your application.")


def _row(key, company, status="submitted", role="Data Analyst Intern", **extra):
    history = [store_models.StatusChange(status=status, at="2026-09-20T12:00:00+00:00")]
    return store_models.Application(
        source="t", source_job_id=key, company=company, role=role,
        status=status, status_history=history, **extra,
    )


def _mail(message_id, sender, subject, body, day="Tue, 20 Oct 2026 09:15:00 -0700"):
    return mail_inbox.IncomingMail(message_id=message_id, sender=sender, subject=subject,
                                   date=day, body=body)


def _connect(every_hours=3, auto_close=False):
    mail_sync.set_password("secret")

    def mutate(settings):
        settings.imap, settings.every_hours, settings.auto_close = (
            ACCOUNT, every_hours, auto_close)
    mail_sync.update(mutate)


def _proposal(message_id):
    return next(p for p in mail_inbox.load().proposals if p.message_id == message_id)


# --- when a check runs, and from which day ---------------------------------------------

def test_due_checks_after_startup_then_on_schedule():
    started = datetime(2026, 10, 23, 8, tzinfo=UTC)
    now = started + timedelta(minutes=1)
    assert not mail_sync.due(now, mail_sync.Settings(), started=started)
    connected = mail_sync.Settings(imap=ACCOUNT, every_hours=3)
    assert mail_sync.due(now, connected, started=started)  # never tried
    before = connected.model_copy(update={"last_attempt": "2026-10-22T20:00:00+00:00"})
    assert mail_sync.due(now, before, started=started)  # tried before this start
    recent = connected.model_copy(update={"last_attempt": now.isoformat()})
    assert not mail_sync.due(now + timedelta(hours=2), recent, started=started)
    assert mail_sync.due(now + timedelta(hours=3), recent, started=started)
    off = recent.model_copy(update={"every_hours": 0})
    assert not mail_sync.due(now + timedelta(days=9), off, started=started)


def test_the_first_check_reads_from_the_first_application_sent():
    apps = [_row("a", "Acme"), _row("b", "Globex", status="awaiting_review")]
    today = date(2026, 10, 23)
    assert mail_sync.since_date(mail_sync.Settings(), apps, today) == date(2026, 9, 20)
    assert mail_sync.since_date(mail_sync.Settings(), [], today) == date(2026, 9, 23)
    later = mail_sync.Settings(last_checked="2026-10-22T09:00:00+00:00")
    assert mail_sync.since_date(later, apps, today) == date(2026, 10, 21)


# --- a check -------------------------------------------------------------------------

def test_a_check_ingests_past_one_post_and_records_its_result(monkeypatch):
    apply_store.save_all({"acme": _row("acme", "Acme")})
    _connect()
    seen = {}

    def fake_fetch(account, password, *, since, companies):
        seen.update(account=account, password=password, since=since, companies=companies)
        noise = [_mail(f"n{i}", "x@store.example", "Sale", "20% off") for i in range(59)]
        thanks = _mail("t", "Acme <jobs@acme.com>", "Thanks for applying",
                       "Thank you for applying. We received your application.")
        return [*noise, thanks, _mail("r", "Acme <jobs@acme.com>", "Your application", REJECTION)]
    monkeypatch.setattr(mail_sync.mail_imap, "fetch", fake_fetch)

    result = mail_sync.run()
    assert (result.ignored, result.matched, result.closed) == (60, 1, 0)
    assert seen == {"account": ACCOUNT, "password": "secret", "since": date(2026, 9, 20),
                    "companies": ["Acme"]}
    settings = mail_sync.load()
    assert settings.last_checked and settings.last_error == ""
    assert settings.last_result == result and settings.last_since == "2026-09-20"
    assert apply_store.get("acme").outcome_events == []  # auto_close is off
    assert _proposal("r").confident
    # An acknowledgement for an application already sent is not news.
    assert [p.message_id for p in mail_inbox.load().proposals] == ["r"]


def test_the_check_ignores_acknowledgements_unless_one_confirms_a_submit(monkeypatch):
    apply_store.save_all({
        "a1": _row("a1", "Acme"), "a2": _row("a2", "Acme", role="Data Engineer Intern"),
        "g": _row("g", "Globex", status="awaiting_review"),
        "u": _row("u", "Umbrella", status="submit_unconfirmed"),
    })
    _connect()
    thanks = "Thank you for applying. We received your application."
    monkeypatch.setattr(mail_sync.mail_imap, "fetch", lambda *_a, **_k: [
        _mail("acme", "Acme <jobs@acme.com>", "Thanks for applying", thanks),  # two roles
        _mail("globex", "Globex <jobs@globex.com>", "Thanks for applying", thanks),
        _mail("umbrella", "Umbrella <jobs@umbrella.com>", "Thanks for applying", thanks),
    ])
    result = mail_sync.run()
    assert (result.ignored, result.matched) == (2, 1)
    assert [(p.message_id, p.app_id) for p in mail_inbox.load().proposals] == [("umbrella", "u")]


def test_a_failed_check_keeps_the_last_good_one_and_says_why(monkeypatch):
    _connect()

    def refused(*_a, **_k):
        raise mail_imap.MailAuthError("The mail server refused that username or password.")
    monkeypatch.setattr(mail_sync.mail_imap, "fetch", refused)
    assert mail_sync.run() is None
    settings = mail_sync.load()
    assert settings.last_error.startswith("The mail server refused")
    assert settings.last_attempt and not settings.last_checked


def test_a_profile_switch_during_a_check_discards_what_it_read(monkeypatch):
    _connect()
    workspace = config.active_workspace_id()

    def switch(*_a, **_k):
        monkeypatch.setattr(mail_sync.config, "active_workspace_id",
                            lambda: f"{workspace}-other")
        return [_mail("r", "Acme <jobs@acme.com>", "Your application", REJECTION)]
    monkeypatch.setattr(mail_sync.mail_imap, "fetch", switch)
    assert mail_sync.run() is None
    assert mail_inbox.load().seen == []


def test_without_a_password_a_check_asks_for_setup():
    mail_sync.update(lambda s: setattr(s, "imap", ACCOUNT))
    assert mail_sync.run() is None
    assert mail_sync.load().last_error.startswith("Set up the email account")


def test_forget_removes_the_account_and_its_password():
    _connect()
    mail_sync.forget()
    assert mail_sync.load().imap is None and mail_sync.password() == ""


# --- which rejections are confident ----------------------------------------------------

def _confident(body, app, *, others=(), day="Tue, 20 Oct 2026 09:15:00 -0700"):
    mail_inbox.ingest([_mail("m", "Acme <jobs@acme.com>", "Your application", body, day)],
                      [app, *others])
    return _proposal("m").confident


def test_a_rejection_naming_the_role_of_one_sent_application_is_confident():
    assert _confident(REJECTION, _row("acme", "Acme"))


@pytest.mark.parametrize(
    ("body", "app", "others", "day"),
    [
        # Only the company points at it: which of its roles is unknown.
        ("Unfortunately, we will not be moving forward.", _row("acme", "Acme"), (), None),
        # Two applications to the same role at the same company tie.
        (REJECTION, _row("acme", "Acme"), (_row("acme2", "Acme"),), None),
        # Not sent yet: the email contradicts the record.
        (REJECTION, _row("acme", "Acme", status="awaiting_review"), (), None),
        # Older than the application: about an earlier one.
        (REJECTION, _row("acme", "Acme"), (), "Mon, 01 Jun 2026 09:00:00 -0700"),
        # Not a rejection.
        ("Thank you for applying to the Data Analyst Intern role. We'd like to invite you "
         "to an interview.", _row("acme", "Acme"), (), None),
    ],
    ids=["company-only", "tied", "not-sent", "older", "interview"],
)
def test_anything_less_certain_is_left_for_the_student(body, app, others, day):
    kwargs = {"day": day} if day else {}
    assert not _confident(body, app, others=others, **kwargs)


def test_an_application_already_closed_is_not_confident():
    app = _row("acme", "Acme")
    outcomes.add_event(app, "rejected", occurred_on="2026-10-01")
    assert not _confident(REJECTION, app)


# --- automatic closes and their undo ---------------------------------------------------

def test_auto_close_records_a_monitor_event_and_undo_takes_it_back():
    apply_store.save_all({"acme": _row("acme", "Acme")})
    mail_inbox.ingest([_mail("r", "Acme <jobs@acme.com>", "Your application", REJECTION)],
                      list(apply_store.rows_view().values()))
    assert mail_inbox.auto_close() == 1
    event = apply_store.get("acme").outcome_events[0]
    assert (event.type, event.source, event.occurred_on) == ("rejected", "monitor", "2026-10-20")
    assert event.note == "Closed from email “Your application”"
    proposal = _proposal("r")
    assert (proposal.state, proposal.auto, proposal.event_id) == ("accepted", True, event.id)
    assert [p.id for p in mail_inbox.recent_auto()] == [proposal.id]
    assert mail_inbox.auto_close() == 0  # nothing left pending

    back = mail_inbox.undo_auto(proposal.id)
    assert (back.state, back.auto, back.confident, back.event_id) == ("pending", False, False, "")
    assert apply_store.get("acme").outcome_events[0].voided_at is not None
    assert outcomes.hiring_progress(apply_store.get("acme")).closed is None
    assert mail_inbox.auto_close() == 0  # never closed automatically again
    with pytest.raises(ValueError, match="not recorded automatically"):
        mail_inbox.undo_auto(proposal.id)


def test_auto_close_leaves_a_row_closed_meanwhile_alone():
    apply_store.save_all({"acme": _row("acme", "Acme")})
    mail_inbox.ingest([_mail("r", "Acme <jobs@acme.com>", "Your application", REJECTION)],
                      list(apply_store.rows_view().values()))
    apply_store.update("acme", lambda a: outcomes.add_event(a, "withdrawn",
                                                            occurred_on="2026-10-21"))
    assert mail_inbox.auto_close() == 0
    proposal = _proposal("r")
    assert (proposal.state, proposal.confident) == ("pending", False)
    assert len(apply_store.get("acme").outcome_events) == 1


def test_a_check_with_auto_close_on_closes_the_confident_rejection(monkeypatch):
    apply_store.save_all({"acme": _row("acme", "Acme")})
    _connect(auto_close=True)
    monkeypatch.setattr(mail_sync.mail_imap, "fetch", lambda *_a, **_k: [
        _mail("r", "Acme <jobs@acme.com>", "Your application", REJECTION)])
    assert mail_sync.run().closed == 1
    assert apply_store.get("acme").outcome_events[0].source == "monitor"
