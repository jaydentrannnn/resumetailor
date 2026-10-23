"""A short follow-up or thank-you note for a sent application (purpose ``followup``).

One LLM call writes 60 to 120 words in the shape of the channel the candidate picked
(an email with a subject, a LinkedIn message, or an applicant-portal message). Every
sentence passes `sent_claims.check_claims` against the bullets that were sent, plus
what the candidate typed (the recipient and their interview notes); a draft that fails
is replaced by a plain template that claims nothing. The note is only shown: the
candidate copies it and records ``followup_sent`` when they send it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .. import config
from ..content.data import MasterResume
from ..infra import llm
from . import sent_claims

#: Bumped when ``_SYSTEM`` or the request shape changes.
_FOLLOWUP_PROMPT_VERSION = 1

Kind = Literal["follow_up", "thank_you"]
Channel = Literal["email", "linkedin", "portal"]

_CHANNEL = {
    "email": "an email: give a short subject line, then the body with a greeting and a sign-off",
    "linkedin": "a LinkedIn message: no subject, a short greeting, no formal sign-off",
    "portal": "a message in the employer's applicant portal: no subject, plain and brief",
}


class FollowupLLM(BaseModel):
    """Schema-validated model output for one note."""

    subject: str = ""
    body: str = ""


class FollowupNote(BaseModel):
    kind: Kind
    channel: Channel
    subject: str = ""
    body: str
    #: "llm", or "template" when the draft failed the claim check.
    source: Literal["llm", "template"] = "llm"
    warnings: list[str] = Field(default_factory=list)
    model: str = ""
    prompt_version: int = _FOLLOWUP_PROMPT_VERSION
    made_at: str = ""


_SYSTEM = """\
You write one short note from a job candidate to an employer, 60 to 120 words.

- A follow_up note asks politely about an application the candidate already sent and \
restates their interest in one sentence drawn from the resume bullets supplied.
- A thank_you note thanks the interviewer after an interview and may mention one topic \
from the candidate's own interview notes.

Rules:
- Never claim a skill, tool, number, employer or achievement that the bullets or the \
candidate's notes do not state. Do not repeat the whole resume.
- Do not invent the recipient's name; if none is given, use a neutral greeting.
- No pressure, no apologies, no em dashes. Plain text only.
"""


#: Capitalised words a note uses that claim nothing: salutations, days and months.
_LETTER_WORDS = (
    "Hiring Team Manager Recruiter Recruiting Talent Acquisition Committee "
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday "
    "January February March April May June July August September October November December"
)


def _dates(sent_on: str) -> list[str]:
    """The send date as a note may write it, so naming it is not an unsupported claim."""
    try:
        day = date.fromisoformat(sent_on)
    except ValueError:
        return []
    return [sent_on, f"{day:%B} {day.day}, {day.year}", f"{day.day} {day:%B} {day.year}"]


def _offenders(bullets: dict[str, str], text: str, typed: list[str]) -> list[str]:
    """Unsupported terms and numbers, line by line (a greeting line is its own sentence)."""
    found: list[str] = []
    for line in text.splitlines():
        if line.strip():
            check = sent_claims.check_claims(bullets, line, extra_sources=typed)
            found += check.unsupported_terms + check.unsupported_numbers
    return list(dict.fromkeys(found))


def _template(kind: Kind, channel: Channel, *, role: str, company: str,
              recipient: str, sent_on: str) -> tuple[str, str]:
    """A note that claims nothing, used when the model's draft fails the claim check."""
    greeting = f"Hi {recipient}," if recipient else "Hello,"
    position = f"the {role} position" if role else "the open position"
    if kind == "thank_you":
        subject = f"Thank you: {role}" if role else "Thank you"
        body = (
            f"{greeting}\n\nThank you for taking the time to speak with me about {position} "
            f"at {company}. I enjoyed learning more about the team and the work, and I am "
            "still very interested in the role. Please let me know if there is anything "
            "else I can share.\n\nBest regards"
        )
    else:
        subject = f"Following up: {role}" if role else "Following up on my application"
        when = f" on {sent_on}" if sent_on else ""
        body = (
            f"{greeting}\n\nI applied for {position} at {company}{when} and wanted to follow "
            "up. I remain very interested in the role and would welcome the chance to talk "
            "about it. Please let me know if there is anything else you need from me.\n\n"
            "Best regards"
        )
    return (subject if channel == "email" else ""), body


def draft(
    kind: Kind,
    channel: Channel,
    *,
    resume: MasterResume,
    role: str,
    company: str,
    bullets: dict[str, str],
    jd_text: str = "",
    sent_on: str = "",
    recipient: str = "",
    notes: Sequence[str] = (),
) -> FollowupNote:
    """Draft one note. Raises RuntimeError when the model reply won't parse.

    ``jd_text`` remains accepted for callers, but posting numbers are not evidence for
    candidate claims. Only the sent bullets and explicit typed facts support the note.
    """
    sent = "\n".join(f"  - {text}" for text in bullets.values())
    typed = "\n".join(f"  - {n}" for n in notes) or "  (none)"
    user = (
        f"<kind>{kind}</kind>\n<channel>{_CHANNEL[channel]}</channel>\n"
        f"<role>{role} at {company}</role>\n<sent_on>{sent_on or 'unknown'}</sent_on>\n"
        f"<recipient>{recipient or '(not given)'}</recipient>\n\n"
        f"<resume_bullets_sent>\n{sent}\n</resume_bullets_sent>\n\n"
        f"<candidate_notes>\n{typed}\n</candidate_notes>"
    )
    response = llm.client_for("followup").messages.parse(
        model=config.model_for("followup"),
        max_tokens=config.max_tokens_for("followup"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=FollowupLLM,
        output_config={"effort": config.effort_for("followup")},
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError(
            f"Model did not return a parseable note (stop_reason={response.stop_reason!r})."
        )
    subject = parsed.subject.strip() if channel == "email" else ""
    body = parsed.body.strip()
    typed = [resume.contact.name, recipient, company, role, _LETTER_WORDS,
             *_dates(sent_on), *notes]
    offenders = _offenders(bullets, f"{subject}\n{body}", typed)
    note = FollowupNote(
        kind=kind, channel=channel, subject=subject, body=body,
        warnings=sent_claims.missing_bullet_warnings(resume, bullets),
        model=config.backend_for("followup").label(),
        made_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    if body and not offenders:
        return note
    note.subject, note.body = _template(
        kind, channel, role=role, company=company, recipient=recipient, sent_on=sent_on
    )
    note.source = "template"
    note.warnings.append(
        f"The draft mentioned {', '.join(offenders)}, which the resume you sent doesn't show, so a "
        "plain note is shown instead." if offenders else
        "The model returned an empty note, so a plain note is shown instead."
    )
    return note
