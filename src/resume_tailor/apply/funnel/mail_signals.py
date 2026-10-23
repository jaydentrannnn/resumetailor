"""Read a job email for what it says happened, and which application it is about.

Pure, no LLM: email text is untrusted and never goes to the model. Claude Desktop's
Gmail connector reads the mail and hands messages over (`mcp_server`); this module only
proposes, and the student confirms every proposal in the app (`mail_inbox`).

`classify` looks at the subject and the first lines only, with fixed phrase lists, in a
fixed priority (an offer beats a rejection beats an interview beats an assessment beats
an acknowledgement). It never proposes ``hired`` or ``offer_declined``: those are the
student's own steps. `match` scores the registry rows an email could be about; a tie or
no match leaves it unclear, for the student to assign.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
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
        r"(?:extend|extending) (?:you )?an offer|offer of employment|"
        r"your (?:job |written )?offer)\b",
        re.I)),
    ("rejected", re.compile(
        r"\b(?:not (?:be )?moving forward|move forward with other candidates|"
        r"(?:decided|chosen|elected) (?:not to|to not) (?:proceed|move forward)|"
        r"pursue other candidates|other candidates whose|(?:have|has) not been selected|"
        r"not been selected|regret to inform|no longer (?:under consideration|being considered)|"
        r"position has (?:now )?been filled|unable to offer you|will not be progressing|"
        r"not (?:to )?progress(?:ing)? your application)\b",
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
#: Rows an email can be about: anything the student may have applied to.
_APPLIED_OR_PREPARED = outcomes.SENT | {
    "ready", "filling", "awaiting_review", "awaiting_otp", "fill_failed",
}
_CONFIRMED_SENT = outcomes.SENT - {"submit_unconfirmed"}
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"the", "and", "of", "for", "at", "a", "an", "to", "in", "intern",
                   "internship", "summer", "fall", "spring", "winter", "co", "group"})


@dataclass
class Mail:
    message_id: str
    sender: str
    subject: str
    body: str
    received_on: str | None

    @property
    def from_domain(self) -> str:
        return parseaddr(self.sender)[1].rpartition("@")[2].lower()

    @property
    def display_name(self) -> str:
        return parseaddr(self.sender)[0]

    @property
    def head(self) -> str:
        return f"{self.subject}\n{self.body[:_HEAD_CHARS]}"


@dataclass
class Match:
    app_id: str | None
    reason: str
    #: Rows that tied for the best score, when nothing clearly won.
    candidates: list[str] = field(default_factory=list)


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


def classify(subject: str, body: str) -> Signal | None:
    """What the email says happened, from its subject and opening; None for anything
    else (a newsletter, a job alert, a question)."""
    head = f"{subject}\n{body[:_HEAD_CHARS]}"
    if _NOISE.search(head):
        return None
    for signal, pattern in _SIGNALS:
        if pattern.search(head):
            return signal
    return None


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _phrase_in(phrase: list[str], words: list[str]) -> bool:
    n = len(phrase)
    return bool(n) and any(words[i:i + n] == phrase for i in range(len(words) - n + 1))


def _ats_for(domain: str) -> str | None:
    return next((ats for host, ats in ATS_DOMAINS.items()
                 if domain == host or domain.endswith("." + host)), None)


def _score(mail: Mail, app: store_models.Application) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    text_words = _words(f"{mail.display_name}\n{mail.head}")
    company = _words(identity.normalize_company(app.company))
    significant = [w for w in company if w not in _STOP]
    if significant and _phrase_in(company, text_words):
        score += 3
        reasons.append("company named")
    domain = mail.from_domain
    if significant and len(significant[0]) >= 4 and significant[0] in domain.replace("-", ""):
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
    return Match(scored[0][1], "Matched by " + ", ".join(scored[0][2]) + ".")


def check(signal: Signal, app: store_models.Application, on: str | None) -> str:
    """Why a proposal needs a second look ("" when it fits the row's state)."""
    progress = outcomes.hiring_progress(app)
    if signal == "sent":
        if app.status in _CONFIRMED_SENT:
            return "Already marked as sent."
        if app.archived_at:
            return "This application is in Done; restore it to change its status."
        return ""
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
