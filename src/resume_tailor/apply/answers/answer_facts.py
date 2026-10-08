"""Applicant facts the "Ask the LLM" answer panel may show the model. Pure, no LLM.

An allowlist, not a denylist: a profile field added later stays out of the prompt until it
is named here. Contact details, salary, equal-opportunity answers and credentials are
never on it.
"""

from __future__ import annotations

from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.content import dates
from resume_tailor.content.data import MasterResume

#: (profile attribute, label) pairs, in the order they are shown to the model.
SAFE_PROFILE_FIELDS: tuple[tuple[str, str], ...] = (
    ("city", "City"),
    ("state", "State"),
    ("country", "Country"),
    ("work_authorization", "Work authorization"),
    ("authorized_to_work", "Authorized to work"),
    ("authorization_country", "Authorized to work in"),
    ("requires_sponsorship_now", "Requires sponsorship now"),
    ("requires_sponsorship_future", "Requires sponsorship in the future"),
    ("earliest_start", "Earliest start"),
    ("notice_period", "Notice period"),
    ("highest_education_obtained", "Highest education completed"),
)


def profile_facts(profile: ApplicantProfile) -> list[str]:
    """One ``"Label: value"`` line per allowlisted field the applicant has filled in."""
    lines: list[str] = []
    for attr, label in SAFE_PROFILE_FIELDS:
        value = getattr(profile, attr, None)
        if value is None:
            continue
        if isinstance(value, bool):
            value = "yes" if value else "no"
        text = str(value).strip()
        if attr == "earliest_start":
            text = dates.display(text)
        if text:
            lines.append(f"{label}: {text}")
    return lines


def all_bullets(resume: MasterResume) -> dict[str, str]:
    """Every master-resume bullet by id, so an answer can draw on the whole resume."""
    return {bullet.id: bullet.text for bullet in resume.all_bullets()}
