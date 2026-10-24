"""Read a job email for what it says happened, and which application it is about.

Pure, no LLM: email text is untrusted and never goes to the model. Claude Desktop's
Gmail connector reads the mail and hands messages over (`mcp_server`); this module only
proposes, and the student confirms every proposal in the app (`mail_inbox`).

`classify` looks at the subject and the first lines only, with fixed phrase lists, in a
fixed priority (an offer beats a rejection beats an interview beats an assessment beats
an acknowledgement). Text is normalised first (one space between words, straight
quotes), so a phrase wrapped onto a new line still matches, and a hit inside a
conditional sentence ("if you are not selected…", "you may receive an assessment") is
skipped: thank-you emails describe next steps that have not happened. It never proposes
``hired`` or ``offer_declined``: those are the student's own steps. `match` scores the
registry rows an email could be about; a tie or no match leaves it unclear, for the
student to assign.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from typing import Literal

from resume_tailor.apply.discovery import identity

from . import outcomes, store_models
from .submission_monitor import mentions_any, requisition_ids

#: What an email can propose: an outcome event, or "sent" (an acknowledgement that
#: confirms an application the app could not confirm itself).
Signal = Literal["sent", "assessment", "interview_invited", "offer", "rejected"]

#: Characters of the body read for the signal: the opening, where it is stated.
_HEAD_CHARS = 700

_NOISE = re.compile(
    r"\b(?:job alert|jobs? (?:for|picked for) you|recommended jobs|new jobs? (?:match|near)|"
    r"unsubscribe from (?:job|these) alerts|similar jobs|people also viewed|webinar|newsletter)\b",
    re.I,
)
_SIGNALS: tuple[tuple[Signal, re.Pattern[str]], ...] = (
    ("offer", re.compile(
        r"\b(?:offer letter|pleased to (?:extend |make )?(?:you )?(?:an |a formal )?offer|"
        r"(?:extend|extending) (?:you )?an offer(?! to (?:another|a different|other) candidate)|"
        r"offer of employment|your (?:job |written )?offer)\b",
        re.I)),
    ("rejected", re.compile(
        r"\b(?:not (?:be )?moving forward|no longer moving forward|"
        r"mov(?:e|ed|ing) forward with (?:some )?(?:other|another|different) "
        r"(?:candidates?|applicants?|individuals?)|"
        r"(?:decided|chosen|elected|opted|decision) to (?:move|moving) forward with "
        r"(?:the )?(?:candidates|applicants|others)|"
        r"only (?:be )?able to move forward with candidates|"
        r"(?:decided|chosen) to (?:progress|proceed|continue(?: the process)?) with "
        r"(?:other|another|others)|"
        r"(?:decided|chosen|elected|decision) (?:not to|to not) (?:proceed|move forward|progress)|"
        r"(?:won't|will not|unable to|not able to|cannot|can't)(?: be able to)? (?:be )?"
        r"(?:moving|move) forward|"
        r"pursue other (?:candidates|applicants)|other candidates whose|"
        r"other (?:candidates|applicants) (?:may |might )?(?:better|more closely) "
        r"(?:fit|match|align)|"
        r"(?:have|has) not been selected|not been selected|not selected your application|"
        r"regret to inform|no longer (?:under consideration|being considered)|"
        r"application is no longer active|no longer (?:hiring|recruiting) for|"
        r"(?:position|role|job|opening|requisition)\b.{0,60}?(?:has|have) (?:now )?been filled|"
        r"(?:position|role|job|opening) (?:is now|was) filled|"
        r"(?:offer(?:ed)?|extended an offer|made an offer) (?:the (?:position|role) )?to "
        r"(?:another|a different) candidate|(?:choose|chosen|selected) another candidate|"
        r"unable to offer you|will not be progressing|"
        r"not (?:to )?progress(?:ing)? your application|"
        r"did not find a (?:fit|match)|"
        r"(?:won't|will not|unable to|not able to) (?:be able to )?invite you to the next|"
        r"you (?:do not|don't|did not|didn't|haven't|have not) (?:meet|met) (?:the |our )?"
        r"(?:minimum |basic )?(?:qualifications|requirements))\b",
        re.I)),
    ("interview_invited", re.compile(
        r"\b(?:invit\w* (?:you )?to (?:an? )?(?:phone |video |virtual |onsite |on-site )?interview|"
        r"schedule (?:an?|your) (?:phone |video |virtual )?(?:interview|call|screen)|"
        r"interview (?:invitation|request|availability)|"
        r"your availability for (?:an? )?(?:interview|call)|"
        r"(?:phone|recruiter) screen|like to (?:speak|talk|chat|meet) with you|"
        r"next step (?:is|will be) (?:an? )?(?:interview|call)|book a time)\b",
        re.I)),
    ("assessment", re.compile(
        r"\b(?:online assessment|coding (?:challenge|assessment|test)|technical assessment|"
        r"take[- ]home|hackerrank|codesignal|codility|hirevue|pymetrics|"
        r"complete (?:the|an|your|this) (?:assessment|test|challenge))\b",
        re.I)),
    ("sent", re.compile(
        r"\b(?:thank you for (?:applying|your application)|thanks for applying|"
        r"(?:we(?:'ve| have)|we) received your application|"
        r"application (?:has been|was) (?:received|submitted)|"
        r"your application (?:to|for) .{1,80} (?:has been|was) (?:received|submitted))\b",
        re.I)),
)
#: Mail hosts of application systems -> the `Application.ats` value they serve.
ATS_DOMAINS: dict[str, str] = {
    "greenhouse.io": "greenhouse",
    "greenhouse-mail.io": "greenhouse",
    "lever.co": "lever",
    "hire.lever.co": "lever",
    "myworkday.com": "workday",
    "myworkdayjobs.com": "workday",
    "workday.com": "workday",
    "ashbyhq.com": "ashby",
    "smartrecruiters.com": "smartrecruiters",
    "icims.com": "icims",
    "successfactors.com": "successfactors",
    "taleo.net": "taleo",
    "jobvite.com": "jobvite",
    "bamboohr.com": "bamboohr",
}
#: Other senders of hiring mail (assessments, scheduling, recruiting tools). Only the
#: mailbox reader's pre-filter uses them (`mail_imap`); they never match a row alone.
HIRING_HOSTS: tuple[str, ...] = (
    "hackerrank.com", "codesignal.com", "codility.com", "hirevue.com", "pymetrics.ai",
    "karat.io", "calendly.com", "goodtime.io", "modernloop.io", "gem.com", "workable.com",
    "workablemail.com", "rippling.com", "jazzhr.com", "breezy.hr", "recruitee.com",
    "teamtailor.com", "oraclecloud.com", "avature.net", "eightfold.ai", "phenom.com",
    "paradox.ai", "brassring.com", "docusign.net", "joinhandshake.com", "simplify.jobs",
    "applytojob.com", "gr8people.com",
)
#: Words that make a sentence about what *might* happen ("if you are not selected", "you
#: may receive a coding assessment"): a thank-you email describing next steps.
_CONDITIONAL = re.compile(
    r"\b(?:if|should you|once you|whether|unless|in the event|likely|"
    r"may (?:receive|be invited|be contacted|be asked|choose))\b",
    re.I,
)
#: Where a sentence ends; " | " joins the subject to the body.
_SENTENCE_END = re.compile(r"[.!?|](?=\s|$)")
_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
_INVISIBLE = re.compile(r"[­​-‏⁠﻿]")
_SPACE = re.compile(r"\s+")
_ANGLE_ADDRESS = re.compile(r"<([^<>@\s]+@[^<>\s]+)>\s*$")
#: Rows an email can be about: anything the student may have applied to.
_APPLIED_OR_PREPARED = outcomes.SENT | {
    "ready", "filling", "awaiting_review", "awaiting_otp", "fill_failed",
}
_CONFIRMED_SENT = outcomes.SENT - {"submit_unconfirmed"}
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"the", "and", "of", "for", "at", "a", "an", "to", "in", "intern",
                   "internship", "summer", "fall", "spring", "winter", "co", "group"})
# Sites nearly every hiring email links to ("Follow us on LinkedIn"): their name in the
# text says nothing about who wrote, so it counts only in mail from their own domain.
_FOOTER_NAMES = frozenset({"linkedin", "indeed", "glassdoor", "facebook", "instagram",
                           "twitter", "youtube", "tiktok"})


@dataclass
class Mail:
    message_id: str
    sender: str
    subject: str
    body: str
    received_on: str | None

    @property
    def from_domain(self) -> str:
        return sender_parts(self.sender)[1].rpartition("@")[2].lower()

    @property
    def display_name(self) -> str:
        return sender_parts(self.sender)[0]

    @property
    def head(self) -> str:
        return _head(self.subject, self.body)


@dataclass
class Match:
    app_id: str | None
    reason: str
    #: Rows that tied for the best score, when nothing clearly won.
    candidates: list[str] = field(default_factory=list)
    #: What pointed at the row ("company named", "requisition id", ...).
    reasons: list[str] = field(default_factory=list)


def received_on(raw: str) -> str | None:
    """An email date (RFC 2822 or ISO) as an ISO date, or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return None


def sender_parts(sender: str) -> tuple[str, str]:
    """``(display name, address)`` of a From header. `parseaddr` gives up on an unquoted
    "@" in the name ("jobs@acme.com <jobs@acme.com>"); the angle-bracket address wins."""
    name, address = parseaddr(sender)
    if address:
        return name, address
    if found := _ANGLE_ADDRESS.search(sender):
        return sender[: found.start()].strip().strip('"'), found.group(1).strip()
    return "", sender.strip() if "@" in sender else ""


def normalize(text: str) -> str:
    """Text as matched: NFKC, straight quotes, no invisible characters, and one space
    between words, so a phrase wrapped onto a new line or typed with a curly apostrophe
    still matches."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return _SPACE.sub(" ", _INVISIBLE.sub("", text)).strip()


def _head(subject: str, body: str) -> str:
    return f"{normalize(subject)} | {normalize(body)[:_HEAD_CHARS]}"


def _stated(head: str, hit: re.Match[str]) -> bool:
    """False when the sentence leading up to ``hit`` makes it conditional."""
    start = max((m.end() for m in _SENTENCE_END.finditer(head, 0, hit.start())), default=0)
    return _CONDITIONAL.search(head, start, hit.start()) is None


def classify(subject: str, body: str) -> Signal | None:
    """What the email says happened, from its subject and opening; None for anything
    else (a newsletter, a job alert, a question)."""
    head = _head(subject, body)
    # Rejections often close with "join our newsletter" or "set up job alerts", so noise
    # only rules out the other signals.
    noise = _NOISE.search(head) is not None
    for signal, pattern in _SIGNALS:
        if noise and signal != "rejected":
            continue
        if any(_stated(head, hit) for hit in pattern.finditer(head)):
            return signal
    return None


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _phrase_in(phrase: list[str], words: list[str]) -> bool:
    n = len(phrase)
    return bool(n) and any(words[i:i + n] == phrase for i in range(len(words) - n + 1))


def hiring_sender(domain: str) -> bool:
    """An application, assessment or scheduling system's mail host."""
    return _ats_for(domain) is not None or any(
        domain == host or domain.endswith("." + host) for host in HIRING_HOSTS)


def _ats_for(domain: str) -> str | None:
    return next((ats for host, ats in ATS_DOMAINS.items()
                 if domain == host or domain.endswith("." + host)), None)


def _score(mail: Mail, app: store_models.Application) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    text_words = _words(f"{mail.display_name}\n{mail.head}")
    company = _words(identity.normalize_company(app.company))
    significant = [w for w in company if w not in _STOP]
    domain = mail.from_domain
    # A hiring system's own company (Workday) is named in, and sends from the domain of,
    # every email it carries for other employers: only its requisition id can match it.
    vendor = " ".join(significant) in ATS_DOMAINS.values()
    own_domain = (bool(significant) and len(significant[0]) >= 4 and not vendor
                  and significant[0] in domain.replace("-", ""))
    footer = " ".join(significant) in _FOOTER_NAMES or vendor
    if significant and _phrase_in(company, text_words) and (own_domain or not footer):
        score += 3
        reasons.append("company named")
    if own_domain:
        score += 2
        reasons.append("company's own mail domain")
    reqs = requisition_ids(app.canonical_key, app.ats)
    if reqs and mentions_any(reqs, mail.head):
        score += 5
        reasons.append("requisition id")
    role = [w for w in _words(identity.normalize_role(app.role)) if w not in _STOP]
    if role and _phrase_in(role, text_words):
        score += 2
        reasons.append("role named")
    if (ats := _ats_for(domain)) is not None and ats == app.ats:
        score += 1
        reasons.append(f"sent from {ats}")
    return score, reasons


def match(mail: Mail, apps: list[store_models.Application]) -> Match:
    """The one application ``mail`` is clearly about, or the tied candidates."""
    scored = []
    for app in apps:
        if app.status not in _APPLIED_OR_PREPARED and not app.outcome_events:
            continue
        score, reasons = _score(mail, app)
        # A company, its mail domain or the requisition must point at the row; an ATS
        # domain or a role title alone could be anyone's.
        if score >= 3 and any(r in reasons for r in
                              ("company named", "company's own mail domain", "requisition id")):
            scored.append((score, app.source_job_id, reasons))
    if not scored:
        return Match(None, "No application matched the sender or the text.")
    scored.sort(key=lambda item: -item[0])
    best = scored[0][0]
    top = [item for item in scored if item[0] == best]
    if len(top) > 1:
        return Match(None, "More than one application could match.",
                     candidates=[key for _, key, _ in top])
    return Match(scored[0][1], "Matched by " + ", ".join(scored[0][2]) + ".",
                 reasons=scored[0][2])


def confident(signal: Signal | None, found: Match, app: store_models.Application | None,
              flag: str) -> bool:
    """A rejection sure enough to record without asking: one application, pinned by its
    requisition id or its role, sent and still open, with nothing contradicting it."""
    if signal != "rejected" or app is None or flag or found.candidates:
        return False
    if found.app_id != app.source_job_id or app.status not in _CONFIRMED_SENT:
        return False
    if not {"requisition id", "role named"} & set(found.reasons):
        return False
    return outcomes.hiring_progress(app).closed is None


def check(signal: Signal, app: store_models.Application, on: str | None) -> str:
    """Why a proposal needs a second look ("" when it fits the row's state)."""
    progress = outcomes.hiring_progress(app)
    if signal == "sent":
        if app.status in _CONFIRMED_SENT:
            return "Already marked as sent."
        if app.archived_at:
            return "This application is in Done; restore it to change its status."
        return ""
    sent = outcomes.sent_on(app)
    # A day of slack: the email's date is in the sender's time zone, the send in UTC.
    if on and sent and date.fromisoformat(on) < date.fromisoformat(sent) - timedelta(days=1):
        return "This email is older than the application."
    rank = outcomes.STAGES.index(progress.stage or "applied")
    if signal == "rejected" and rank >= outcomes.STAGES.index("offer"):
        return "This application already has an offer recorded."
    closed = progress.closed
    if closed in ("rejected", "withdrawn") and signal in ("assessment", "interview_invited"):
        return f"This application is already closed ({outcomes.STAGE_LABELS[closed]})."
    for event in outcomes.live_events(app):
        if event.type == signal and on and (event.occurred_on or "") == on:
            return "Already recorded for this date."
    return ""
