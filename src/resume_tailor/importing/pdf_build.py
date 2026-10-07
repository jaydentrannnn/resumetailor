"""Building a master resume from structured PDF lines: contact, bullets, skills, education."""

from __future__ import annotations

import re

from ..content.data import (
    Bullet,
    Contact,
    Education,
    EducationSection,
    Experience,
    ExperienceSection,
    ListItem,
    ListSection,
    MasterResume,
    Project,
    ProjectSection,
    Section,
    SkillGroup,
    SkillsSection,
    SummaryVariant,
)
from ..document import analysis_types
from ..document.render import parse_range
from . import pdf_lines, pdf_patterns, pdf_structure
from .import_common import UNTAGGED, _fresh_id, _seed_tags, with_skill_terms


# --------------------------------------------------------------------------------------
# 4. Build the MasterResume
# --------------------------------------------------------------------------------------
def _contact(
    preamble: list[pdf_lines.Line], links: list[str], warnings: list[str]
) -> tuple[Contact, str]:
    """(contact, leftover preamble text that reads as a summary)."""
    if not preamble:
        warnings.append("No name or contact line was found at the top of the PDF.")
        return Contact(name="", email=""), ""
    name_line = max(preamble[:3], key=lambda ln: ln.size)
    rest = [ln for ln in preamble if ln is not name_line]
    text = " | ".join(ln.text.replace("\t", " | ") for ln in rest)
    email_m = analysis_types._EMAIL_RE.search(text)
    phone = ""
    phone_m = analysis_types._PHONE_RE.search(text)
    if phone_m and not analysis_types._DATE_RE.search(phone_m.group(0)):
        phone = phone_m.group(0)
        if phone_m.start() > 0 and text[phone_m.start() - 1] == "(":
            phone = "(" + phone
    found = {key: "" for key in pdf_patterns._LINK_RES}
    others: list[str] = []
    for uri in links:
        low = uri.lower()
        if low.startswith("mailto:"):
            continue
        key = next((k for k in pdf_patterns._LINK_RES if f"{k}.com" in low), None)
        if key and not found[key]:
            found[key] = uri
        elif not key and uri not in others:
            others.append(uri)
    for key, pattern in pdf_patterns._LINK_RES.items():
        m = pattern.search(text)
        if m and not found[key]:
            found[key] = m.group(0)
    location = ""
    summary: list[str] = []
    for ln in rest:
        segments = pdf_structure._split_segments(ln.text)
        contact_like = False
        for seg in segments:
            if (
                "@" in seg
                or analysis_types._PHONE_RE.fullmatch(seg.strip("() "))
                or pdf_patterns._URL_RE.search(seg)
                or any(p.search(seg) for p in pdf_patterns._LINK_RES.values())
                or seg.lower() in ("linkedin", "github", "portfolio")
            ):
                contact_like = True
            elif not location and pdf_patterns._LOCATION_RE.match(seg):
                location = seg
                contact_like = True
        if not contact_like and len(ln.text) > 40:
            summary.append(ln.text)
    for m in pdf_patterns._URL_RE.finditer(text):
        url = m.group(0).rstrip(".")
        is_profile = any(p.search(url) for p in pdf_patterns._LINK_RES.values())
        if not is_profile and "@" not in url and url not in others:
            others.append(url)
    email = email_m.group(0) if email_m else ""
    if not email:
        warnings.append("No email address was found; add it in the editor.")
    contact = Contact(
        name=name_line.text.replace("\t", " ").strip(),
        email=email,
        phone=phone,
        location=location,
        linkedin=found["linkedin"],
        github=found["github"],
        links=others[:5],
    )
    return contact, " ".join(summary)

def _bullets(texts: list[str], entry_id: str, vocabulary: set[str]) -> list[Bullet]:
    return [
        Bullet(
            id=f"{entry_id}_b{i}",
            text=text,
            tags=_seed_tags(text, vocabulary) or [UNTAGGED],
            metric=bool(re.search(r"\d", text)),
        )
        for i, text in enumerate((t.strip() for t in texts), start=1)
        if text
    ]

def _skill_groups(lines: list[str], title: str, warnings: list[str]) -> list[SkillGroup]:
    """One group per "Label: items" line. Lines with no label (a sidebar listing one
    skill per line) are gathered into a single group named after the heading."""
    groups: list[SkillGroup] = []
    unlabelled: list[str] = []
    for text in lines:
        flat = text.replace("\t", " ")
        label, sep, items = flat.partition(":")
        if not sep:
            items = flat
        values = [i.strip() for i in re.split(r"[,;]| \u2022 | \| ", items) if i.strip()]
        if not sep:
            unlabelled.extend(values)
        elif label.strip() and values:
            groups.append(SkillGroup(label=label.strip(), items=values))
    if unlabelled:
        name = title.strip().title() or "Skills"
        groups.append(SkillGroup(label=name, items=unlabelled))
        warnings.append(f"Skills without a label were grouped as {name!r}; rename it if needed.")
    return groups

def _education(entry: pdf_structure._Entry) -> Education:
    degree = entry.secondary
    gpa = ""
    details: list[str] = []
    coursework: list[str] = []
    for text in [degree, *entry.extra, *entry.details]:
        m = pdf_patterns._GPA_RE.search(text)
        if m and not gpa:
            gpa = m.group(1).strip()
            if text is degree:
                degree = (degree[: m.start()] + degree[m.end() :]).strip(" ,|")
                continue
            rest = (text[: m.start()] + text[m.end() :]).strip(" ,|")
            if rest:
                details.append(rest)
            continue
        if text is degree:
            continue
        cw = pdf_patterns._COURSEWORK_RE.match(text)
        if cw and not coursework:
            coursework = [c.strip() for c in re.split(r"[,;]", cw.group(1)) if c.strip()]
        elif text:
            details.append(text.replace("\t", " "))
    return Education(
        school=entry.primary,
        degree=degree,
        dates=entry.dates,
        location=entry.location,
        coursework=coursework,
        gpa=gpa,
        show_gpa=bool(gpa),
        details=details,
    )

def _build(
    contact: Contact,
    summary: str,
    drafts: list[pdf_structure._Draft],
    vocabulary: set[str],
    warnings: list[str],
) -> MasterResume:
    entry_ids: set[str] = set()
    section_ids: set[str] = set()
    sections: list[Section] = []
    summaries: list[SummaryVariant] = []
    if summary:
        summaries.append(SummaryVariant(id="summary", text=summary))
    for draft in drafts:
        sid = _fresh_id(draft.title, section_ids)
        if draft.kind == "summary":
            text = " ".join(t.replace("\t", " ") for t in draft.lines).strip()
            if text:
                summaries.append(SummaryVariant(id=_fresh_id("summary", section_ids), text=text))
            continue
        if draft.kind == "experience":
            jobs = []
            for e in draft.entries:
                start, end = parse_range(e.dates) if e.dates else ("", "")
                eid = _fresh_id(e.primary or "entry", entry_ids)
                label = e.primary or draft.title
                if not e.primary:
                    warnings.append(f"{draft.title}: an entry has no company or organisation.")
                if not e.dates:
                    warnings.append(f"{label}: no dates found.")
                if e.extra:
                    warnings.append(f"{label}: header text not used: {', '.join(e.extra)}.")
                jobs.append(
                    Experience(
                        id=eid,
                        company=e.primary,
                        title=e.secondary,
                        location=e.location,
                        start=start,
                        end=end,
                        bullets=_bullets(e.bullets, eid, vocabulary),
                    )
                )
            sections.append(ExperienceSection(id=sid, title=draft.title, entries=jobs))
        elif draft.kind == "project":
            projects = []
            for e in draft.entries:
                tech_text = next((s for s in [e.secondary, *e.extra] if "," in s), e.secondary)
                tech_text = re.sub(r"(?i)^(tech(nologies)?|tools|stack)\s*:\s*", "", tech_text)
                pid = _fresh_id(e.primary or "project", entry_ids)
                if not e.bullets:
                    warnings.append(f"{e.primary or draft.title}: no bullets found.")
                projects.append(
                    Project(
                        id=pid,
                        name=e.primary,
                        tech=[t.strip() for t in re.split(r"[,;]", tech_text) if t.strip()],
                        date=e.dates,
                        bullets=_bullets(e.bullets, pid, vocabulary),
                    )
                )
            sections.append(ProjectSection(id=sid, title=draft.title, entries=projects))
        elif draft.kind == "education":
            schools = [_education(e) for e in draft.entries]
            for school in schools:
                if not school.degree:
                    warnings.append(f"{school.school or draft.title}: no degree line found.")
            sections.append(EducationSection(id=sid, title=draft.title, entries=schools))
        elif draft.kind == "skills":
            groups = _skill_groups(draft.lines, draft.title, warnings)
            sections.append(SkillsSection(id=sid, title=draft.title, entries=groups))
        else:
            items = [
                ListItem(
                    id=_fresh_id(t, entry_ids),
                    text=t.replace("\t", " ").strip(),
                    tags=_seed_tags(t, vocabulary),
                )
                for t in draft.lines
                if t.strip()
            ]
            sections.append(ListSection(id=sid, title=draft.title, entries=items))
    resume = MasterResume(contact=contact, summary_variants=summaries, sections=sections)
    used = sorted({t for b in resume.all_bullets() for t in b.tags if t != UNTAGGED})
    return resume.model_copy(update={"tag_vocabulary": with_skill_terms(resume, used)})
