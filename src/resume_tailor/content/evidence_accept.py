"""Put one evidence proposal into the master resume, as the student edited it. Pure.

The student's own edits are trusted, like typing in the editor: the text, the entry it
goes to, and which skills become the bullet's Extra skills. Ids are minted the way the
editor mints them (`frontend/src/lib/resumeEdit.ts`: ``<prefix>_bN`` bullets,
``proj_<slug>`` projects). The caller writes the result through the resume route's save,
which keeps a version and a backup and refreshes inferred skills.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.content.data import Bullet, MasterResume, Project
from resume_tailor.content.evidence_store import NewProject, Proposal


class AcceptError(ValueError):
    """Plain-words reason the item could not be added."""


class AddRequest(BaseModel):
    """What the student settled on in the add dialog."""

    text: str = Field(min_length=1, max_length=400)
    #: The entry a bullet goes to (defaults to the proposal's).
    target_entry_id: str = ""
    #: A new project's details (defaults to the proposal's).
    new_project: NewProject | None = None
    #: The project section a new project goes to (defaults to the first).
    section_id: str = ""
    #: Skills the student ticks as the bullet's Extra skills.
    skills: list[str] = Field(default_factory=list, max_length=12)
    #: The Skills group a skill joins.
    skill_group: str = ""
    #: The education entry a course joins (its position, as the editor lists them).
    education_index: int = 0


_BULLET_ID = re.compile(r"^(.*)_b\d+$")


def _clean(text: str) -> str:
    return " ".join(text.split())


def _prefix(bullets: list[Bullet], name: str) -> str:
    for bullet in bullets:
        if match := _BULLET_ID.match(bullet.id):
            return match.group(1)
    return config.slugify(name) or "entry"


def _next_bullet_id(prefix: str, taken: set[str]) -> str:
    n = 1
    while f"{prefix}_b{n}" in taken:
        n += 1
    return f"{prefix}_b{n}"


def _next_project_id(name: str, taken: set[str]) -> str:
    base = f"proj_{config.slugify(name) or 'project'}"
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def _add_bullet(resume: MasterResume, request: AddRequest, default_target: str) -> str:
    target = request.target_entry_id or default_target
    for section in resume.entry_sections:
        for entry in section.entries:
            if entry.id != target:
                continue
            name = entry.company if section.kind == "experience" else entry.name
            taken = {b.id for b in resume.all_bullets()}
            bid = _next_bullet_id(_prefix(entry.bullets, name), taken)
            entry.bullets.append(Bullet(id=bid, text=_clean(request.text), tags=request.skills))
            return f"bullet {bid}"
    raise AcceptError("That resume entry no longer exists; pick another.")


def _add_project(resume: MasterResume, request: AddRequest, proposed: NewProject | None) -> str:
    details = request.new_project or proposed
    if details is None or not _clean(details.name):
        raise AcceptError("Give the project a name.")
    sections = [s for s in resume.sections if s.kind == "project"]
    section = next((s for s in sections if s.id == request.section_id), None) or (
        sections[0] if sections else None
    )
    if section is None:
        raise AcceptError("Add a Projects section to your resume first.")
    entry_ids = {e.id for s in resume.entry_sections for e in s.entries}
    pid = _next_project_id(details.name, entry_ids)
    section.entries.append(Project(
        id=pid, name=_clean(details.name), tech=[_clean(t) for t in details.tech if t.strip()],
        url=details.url.strip(), start=details.start, end=details.end,
        bullets=[Bullet(id=f"{pid}_b1", text=_clean(request.text), tags=request.skills)],
    ))
    return f"project {pid}"


def _add_skill(resume: MasterResume, request: AddRequest) -> str:
    skill = _clean(request.text)
    groups = resume.skills
    group = next((g for g in groups if g.label == request.skill_group), None)
    if group is None:
        raise AcceptError("Pick the Skills group it belongs to.")
    if skill.casefold() not in {i.casefold() for i in group.items}:
        group.items.append(skill)
    return f"skills {group.label}"


def _add_course(resume: MasterResume, request: AddRequest) -> str:
    course = _clean(request.text)
    schools = resume.education
    if not 0 <= request.education_index < len(schools):
        raise AcceptError("Pick the school it belongs to.")
    school = schools[request.education_index]
    if course.casefold() not in {c.casefold() for c in school.coursework}:
        school.coursework.append(course)
    return f"coursework {school.school}"


def add(resume: MasterResume, proposal: Proposal, request: AddRequest) -> tuple[MasterResume, str]:
    """A copy of ``resume`` with the item added, and where it went."""
    draft = resume.model_copy(deep=True)
    if proposal.kind == "bullet":
        where = _add_bullet(draft, request, proposal.target_entry_id)
    elif proposal.kind == "project":
        where = _add_project(draft, request, proposal.new_project)
    elif proposal.kind == "skill":
        where = _add_skill(draft, request)
    else:
        where = _add_course(draft, request)
    # Validate again: ids stay unique and dated entries keep their order.
    return MasterResume.model_validate(draft.model_dump(by_alias=True)), where
