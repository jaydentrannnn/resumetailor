"""The read-only mailbox reader (`apply/funnel/mail_imap.py`) against a fake IMAP server."""

from __future__ import annotations

import imaplib
from datetime import date
from email.message import EmailMessage

import pytest

from resume_tailor.apply.funnel import mail_imap


def _raw(sender, subject, body, *, message_id="", html=False):
    msg = EmailMessage()
    msg["From"], msg["Subject"] = sender, subject
    msg["Date"] = "Tue, 20 Oct 2026 09:15:00 -0700"
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content(body, subtype="html" if html else "plain")
    return msg.as_bytes()


MAILBOX = {
    "INBOX": {
        1: _raw("Acme Recruiting <no-reply@us.greenhouse-mail.io>", "Your application to Acme",
                "Unfortunately, we will not be moving forward.", message_id="<r1@acme>"),
        2: _raw("Shop <deals@store.example>", "Big sale this weekend", "Everything 20% off.",
                message_id="<s1@store>"),
        3: _raw("Jo at Globex <jo@globex.com>", "Next steps", "<p>We'd like to invite you "
                "to an <b>interview</b>.</p>", message_id="<i1@globex>", html=True),
    },
    "Junk": {
        # The same rejection filed twice, and a message with no Message-ID.
        8: _raw("Acme Recruiting <no-reply@us.greenhouse-mail.io>", "Your application to Acme",
                "Unfortunately, we will not be moving forward.", message_id="<r1@acme>"),
        9: _raw("HackerRank <support@hackerrank.com>", "Complete your test", "x" * 9000),
    },
    "Sent": {4: _raw("me@mro.example", "My application", "Hello")},
    "Deleted Items": {5: _raw("x@acme.com", "Old application", "Old")},
}
LIST = [b'(\\HasNoChildren) "/" INBOX', b'(\\HasNoChildren \\Junk) "/" "Junk"',
        b'(\\HasNoChildren \\Sent) "/" "Sent"', b'(\\HasNoChildren) "/" "Deleted Items"']
_ALLOWED = {"login", "list", "select", "response", "uid", "logout"}


class FakeImap:
    instances: list[FakeImap] = []

    def __init__(self, host, port, ssl_context=None, timeout=None):
        if host == "down.example":
            raise OSError("connection refused")
        self.calls: list[tuple] = []
        self.selected = ""
        FakeImap.instances.append(self)

    def __getattr__(self, name):  # Any other command (store, expunge, copy...) is a bug.
        raise AssertionError(f"forbidden IMAP command: {name}")

    def login(self, username, password):
        self.calls.append(("login",))
        if password != "secret":
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def list(self):
        self.calls.append(("list",))
        return "OK", LIST

    def select(self, name, readonly=False):
        self.calls.append(("select", name, readonly))
        self.selected = name.strip('"')
        return "OK", [b"3"]

    def response(self, code):
        return code, [b"77"]

    def uid(self, command, *args):
        messages = MAILBOX[self.selected]
        if command == "SEARCH":
            self.calls.append(("uid", "SEARCH", args))
            return "OK", [b" ".join(str(u).encode() for u in messages)]
        uids, spec = args
        self.calls.append(("uid", "FETCH", uids, spec))
        out: list = []
        for uid in uids.split(","):
            raw = messages[int(uid)]
            part = raw.split(b"\n\n", 1)[0] + b"\n\n" if "HEADER.FIELDS" in spec else raw
            out += [(f"{uid} (UID {uid} BODY[] {{{len(part)}}}".encode(), part), b")"]
        return "OK", out

    def logout(self):
        self.calls.append(("logout",))


@pytest.fixture
def fake(monkeypatch):
    FakeImap.instances.clear()
    monkeypatch.setattr(mail_imap.imaplib, "IMAP4_SSL", FakeImap)
    return FakeImap


ACCOUNT = mail_imap.MailAccount(host="mail.example.com", username="me@example.com")


def test_fetch_reads_hiring_mail_read_only_and_never_bodies_of_other_mail(fake):
    mails = mail_imap.fetch(ACCOUNT, "secret", since=date(2026, 9, 23), companies=["Globex"])
    calls = fake.instances[0].calls
    assert {c[0] for c in calls} <= _ALLOWED and calls[-1] == ("logout",)
    selects = [c for c in calls if c[0] == "select"]
    assert [(c[1], c[2]) for c in selects] == [('"INBOX"', True), ('"Junk"', True)]
    search = next(c for c in calls if c[1:2] == ("SEARCH",))
    assert search[2] == (None, "SINCE", "23-Sep-2026")
    bodies = [c for c in calls if c[1:2] == ("FETCH",) and "HEADER.FIELDS" not in c[3]]
    assert all("BODY.PEEK" in c[3] for c in calls if c[1:2] == ("FETCH",))
    # The shop's sale (uid 2) had its headers read, never its body.
    assert [c[2] for c in bodies] == ["1,3", "9"]
    by_subject = {m.subject: m for m in mails}
    assert set(by_subject) == {"Your application to Acme", "Next steps", "Complete your test"}
    html_body = " ".join(by_subject["Next steps"].body.split())
    assert "invite you to an interview" in html_body and "<" not in html_body
    assert by_subject["Complete your test"].message_id == "imap:Junk:77:9"
    assert len(by_subject["Complete your test"].body) == 4000
    assert sum(m.message_id == "<r1@acme>" for m in mails) == 1


def test_a_refused_login_and_an_unreachable_server_are_told_apart(fake):
    with pytest.raises(mail_imap.MailAuthError, match="username or password"):
        mail_imap.fetch(ACCOUNT, "wrong", since=date(2026, 9, 23))
    down = ACCOUNT.model_copy(update={"host": "down.example"})
    with pytest.raises(mail_imap.MailConnectError, match="Could not reach down.example"):
        mail_imap.test(down, "secret")
    assert mail_imap.test(ACCOUNT, "secret") == 2  # INBOX and Junk


def test_only_peek_reads_are_ever_sent(fake):
    box = mail_imap._Box(ACCOUNT)
    with pytest.raises(ValueError, match="BODY.PEEK"):
        box.fetch([b"1"], "(BODY[])")


def test_readable_folders_skip_own_and_deleted_mail_and_read_literal_names():
    lines = [*LIST, (b'(\\HasNoChildren) "/" {11}', b"Recruiting!"),
             b'(\\Noselect \\HasChildren) "/" "[Gmail]"', b'(\\HasNoChildren) "/" "Drafts"']
    assert mail_imap.readable_folders(lines) == [b"INBOX", b'"Junk"', b"Recruiting!"]


@pytest.mark.parametrize(
    ("sender", "subject", "expected"),
    [
        ("no-reply@us.greenhouse-mail.io", "Hello", True),  # An application system.
        ("support@codesignal.com", "Reminder", True),  # An assessment platform.
        ("Globex Talent <talent@globex.com>", "Next steps", True),  # A company applied to.
        ("noreply@mail.globex.com", "Update", True),  # Its own mail domain.
        ("news@store.example", "Your interview with our CEO", True),  # A job word.
        ("news@store.example", "Weekend sale", False),
        ("jobs@acme.com <jobs@acme.com>", "Hi", False),  # Unquoted @ in the name still parses.
    ],
)
def test_wanted_reads_headers_only(sender, subject, expected):
    assert mail_imap.wanted(sender, subject, mail_imap.company_terms(["Globex Inc."])) is expected
