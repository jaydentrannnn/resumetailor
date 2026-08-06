"""Deterministic DOCX -> `MasterResume` importer.

An upload to the Template tab was, until now, a layout donor whose content was
discarded — a new user uploads their resume and then retypes every bullet by hand into
the editor. `template_analyze.analyze_docx` already locates every section, entry,
header field, date, and bullet in an uploaded document (Phase 4's move to reconciling
*every* entry via `_reconcile_header_fields`, not just a single prototype, is exactly
the prerequisite this needed); this module turns that same structural analysis into a
`MasterResume` draft instead of a template mapping.

No LLM call is required to produce a usable draft. Tags are seeded deterministically by
substring-matching each bullet's text against a known-tag vocabulary
(`_seed_tags`) — the same "cheap and free first" instinct the rest of the pipeline
follows (tag-overlap scoring before the semantic LLM blend, `TAG_ALIASES` before a
model call). A bullet nothing matched gets the sentinel tag `"untagged"` (required
since `Bullet.tags` has `min_length=1`) and is counted in `ImportedResume.
untagged_bullet_count`, surfaced to the user rather than silently guessed at.

An optional, explicitly opt-in LLM pass — `propose.propose_bullet_tags` — can suggest
real tags for whatever the deterministic pass left untagged. It is never part of this
module's own call graph; the caller (the web route) decides whether to run it, exactly
as `propose.py`'s existing vocabulary proposals are opt-in Settings-tab actions, never
pipeline stages.

Reuses `template_analyze`'s own private paragraph-level helpers (`_load_paras`,
`_split_entries`, `_header_fields_from_text`, `_skills_spans`) rather than re-deriving
entry/field detection a second time — two independent implementations of "where is the
company name on this line" would drift the moment either one's edge cases were fixed
only in one place. This mirrors how `template_verify.py` already shares
`template_build`'s tag constants instead of re-deriving them.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from . import config, docx_text, template_analyze
from .data import (
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
)
from .render import parse_range
from .template_analyze import AnalyzeResult, HeaderFieldMapping, _Para

#: Sentinel tag for a bullet the deterministic pass matched nothing for — `Bullet.tags`
#: requires at least one entry, so this stands in until the user (or an opt-in LLM
#: pass) supplies a real one. Never treated as a real tag anywhere else in the pipeline.
UNTAGGED = "untagged"

_COURSEWORK_RE = re.compile(r"(?i)^relevant coursework:\s*(.+)$")
_GPA_RE = re.compile(r"(?i)\s*\|\s*GPA:\s*(.+)$")


class ImportedResume(BaseModel):
    """A draft `MasterResume` plus what the importer could not confidently fill in.

    Returned to the caller without writing anything — the web route hands it to the
    editor as unsaved state; the user reviews and saves through the existing
    `PUT /api/master-resume`, the same path a hand edit takes.
    """

    resume: MasterResume
    #: Plain-English notes naming the entry/field a value could not be parsed for, so a
    #: user reviewing the draft knows exactly what to check rather than discovering a
    #: blank field on its own.
    warnings: list[str] = Field(default_factory=list)
    untagged_bullet_count: int = 0


def _default_vocabulary() -> set[str]:
    """Alias keys and their canonical targets — every tag name the deterministic
    matcher can recognize with no resume-specific vocabulary supplied."""
    return set(config.TAG_ALIASES.keys()) | set(config.TAG_ALIASES.values())


def _fresh_id(label: str, taken: set[str]) -> str:
    """Slugify `label` into an id unique within `taken`, recording it. Mirrors
    `MasterResume._fill_entry_ids`'s own collision suffixing (`-2`, `-3`, …) so an
    imported file's ids look like a hand-authored one's, not a machine's."""
    base = config.slugify(label) or "entry"
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


def _seed_tags(text: str, vocabulary: set[str]) -> list[str]:
    """Whole-word, case-insensitive substring match against `vocabulary`, canonicalised.

    Deliberately conservative: a false negative (a real skill left untagged) is safe —
    the user or an opt-in LLM pass can add it — while a false positive (tagging a
    bullet with a skill it does not actually claim) would corrupt the fabrication
    guard's own whitelist for that bullet. Whole-word matching keeps a short term like
    "r" or "go" from matching inside an unrelated word.
    """
    lower = text.lower()
    found: set[str] = set()
    for term in vocabulary:
        term = term.strip()
        if not term:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, lower):
            found.add(config.canonical_tag(term))
    return sorted(found)


def _field_text(para: _Para, header: HeaderFieldMapping, field: str) -> str:
    """Slice `para`'s text at `header`'s span for `field`, or "" when absent."""
    opt = header.fields.get(field)
    if opt is None or not opt.present or opt.span is None:
        return ""
    return para.text[opt.span.start : opt.span.end].strip()


def _paragraph_hyperlink_target(
    para: _Para, *, limit: int | None = None
) -> tuple[str, str, int | None]:
    """Return `(label, url, start)` for the last hyperlink in `para` ending at or
    before `limit` (an entry header's tab index, or end of text when None) — mirrors
    `template_analyze`'s own "last hyperlink before the tab" project-link detection.
    `start` is the label's own character offset, for excluding it from the
    primary/secondary field search region (see `_header_fields_from_text`'s
    `exclude_after`).
    """
    if not para.has_hyperlink:
        return "", "", None
    text = para.text
    region_limit = len(text) if limit is None else limit
    in_region = [
        (s, e) for s, e in docx_text.hyperlink_char_spans(para.paragraph) if e <= region_limit
    ]
    if not in_region:
        return "", "", None
    start, end = in_region[-1]
    label = text[start:end]
    url = ""
    for child in para.paragraph._p.xpath("w:hyperlink"):
        target = docx_text.hyperlink_target(para.paragraph, child)
        if target:
            url = target
            break
    return label, url, start


def _import_bullets(bullet_paras: list[_Para], entry_id: str, vocabulary: set[str]) -> list[Bullet]:
    bullets: list[Bullet] = []
    for i, p in enumerate(bullet_paras, start=1):
        text = p.text.strip()
        if not text:
            continue
        tags = _seed_tags(text, vocabulary) or [UNTAGGED]
        bullets.append(
            Bullet(
                id=f"{entry_id}_b{i}",
                text=text,
                tags=tags,
                # Coarse draft heuristic, not a claim about the source resume's own
                # writing style: any digit is treated as "carries a metric". The user
                # reviews every imported bullet before saving, same as every other
                # importer field here.
                metric=bool(re.search(r"\d", text)),
            )
        )
    return bullets


def _import_contact(paras: list[_Para]) -> Contact:
    """Best-effort contact extraction from paragraphs 0 (name) and 1 (contact line) —
    the same fixed convention `template_analyze`'s legacy path and `build_name`/
    `build_contact` already assume for this codebase's resumes."""
    name = paras[0].text.strip() if paras else ""
    contact_para = paras[1] if len(paras) > 1 else None
    text = contact_para.text if contact_para is not None else ""

    email_m = template_analyze._EMAIL_RE.search(text)
    email = email_m.group(0) if email_m else ""

    phone = ""
    phone_m = template_analyze._PHONE_RE.search(text)
    if phone_m and not template_analyze._DATE_RE.search(phone_m.group(0)):
        phone = phone_m.group(0)
        # `_PHONE_RE` requires its match to start on a digit, so a leading "(" in
        # "(555) 123-4567" is never part of the match — restore it here rather than
        # importing a phone number with its opening parenthesis silently dropped.
        if phone_m.start() > 0 and text[phone_m.start() - 1] == "(":
            phone = "(" + phone

    linkedin = ""
    github = ""
    if contact_para is not None:
        for child in contact_para.paragraph._p.xpath("w:hyperlink"):
            target = docx_text.hyperlink_target(contact_para.paragraph, child)
            if not target:
                continue
            low = target.lower()
            if "linkedin.com" in low and not linkedin:
                linkedin = target
            elif "github.com" in low and not github:
                github = target

    # Split on the *actual* separator this line uses (reusing
    # `template_analyze._contact_separator`'s own detection) rather than a bare
    # character class: a plain-text profile URL typed inline, not a real w:hyperlink
    # ("www.linkedin.com/in/…", common when an export loses its hyperlinks), contains
    # bare "/" and "." itself — splitting on those unconditionally shreds the URL into
    # unrelated fragments instead of treating it as one field.
    sep = template_analyze._contact_separator(text) if text.strip() else " • "
    segments = [s.strip() for s in text.split(sep) if s.strip()] if sep in text else (
        [text.strip()] if text.strip() else []
    )

    location = ""
    for seg in segments:
        if not seg or seg == email or seg == phone or "@" in seg:
            continue
        low = seg.lower()
        if "linkedin" in low:
            if not linkedin:
                linkedin = seg
            continue
        if "github" in low:
            if not github:
                github = seg
            continue
        if template_analyze._PHONE_RE.fullmatch(seg.replace(" ", "")):
            continue
        location = seg
        break

    return Contact(name=name, email=email, phone=phone, location=location, linkedin=linkedin, github=github)


def _import_experience_entries(
    body: list[_Para], vocabulary: set[str], taken_ids: set[str]
) -> tuple[list[Experience], list[str]]:
    warnings: list[str] = []
    entries: list[Experience] = []
    for entry in template_analyze._split_entries(body):
        header_para = entry[0]
        header, _candidates = template_analyze._header_fields_from_text(
            header_para, primary="company", secondary="location", date_field="dates"
        )
        company = _field_text(header_para, header, "company")
        location = _field_text(header_para, header, "location")
        dates_text = _field_text(header_para, header, "dates")

        rest = entry[1:]
        titles = [p for p in rest if not p.is_bullet and p.text.strip()]
        title = ""
        if titles:
            title_text = titles[0].text
            tab_idx = title_text.find("\t")
            if tab_idx < 0:
                title = title_text.strip()
            else:
                # The title line carries its own trailing tab-aligned date (a two-line
                # header where *each* line has one, e.g. an org affiliation followed by
                # a specific role's own date range) — keep just the title text out of
                # it, and fall back to its date only when the entry header itself had
                # none, rather than silently storing the raw "Title\tDate" text.
                title = title_text[:tab_idx].strip()
                if not dates_text:
                    dates_text = title_text[tab_idx + 1 :].strip()
        start, end = parse_range(dates_text) if dates_text else ("", "")
        bullet_paras = [p for p in rest if p.is_bullet]

        label = company or header_para.text.strip() or f"paragraph {header_para.id}"
        if not company:
            warnings.append(f'experience entry at paragraph {header_para.id}: could not detect a company name')
        if not dates_text:
            warnings.append(f"{label}: no dates detected")
        if not bullet_paras:
            warnings.append(f"{label}: no bullets detected")

        entry_id = _fresh_id(company or "role", taken_ids)
        entries.append(
            Experience(
                id=entry_id,
                company=company,
                title=title,
                location=location,
                start=start,
                end=end,
                bullets=_import_bullets(bullet_paras, entry_id, vocabulary),
            )
        )
    return entries, warnings


def _import_project_entries(
    body: list[_Para], vocabulary: set[str], taken_ids: set[str]
) -> tuple[list[Project], list[str]]:
    warnings: list[str] = []
    entries: list[Project] = []
    for entry in template_analyze._split_entries(body):
        header_para = entry[0]
        text = header_para.text
        tab = text.find("\t")
        link, url, exclude_after = _paragraph_hyperlink_target(
            header_para, limit=None if tab < 0 else tab
        )

        header, _candidates = template_analyze._header_fields_from_text(
            header_para,
            primary="name",
            secondary="tech",
            date_field="date",
            exclude_after=exclude_after,
        )
        name = _field_text(header_para, header, "name")
        tech_text = _field_text(header_para, header, "tech")
        tech = [t.strip() for t in tech_text.split(",") if t.strip()]
        date_text = _field_text(header_para, header, "date")

        bullet_paras = [p for p in entry[1:] if p.is_bullet]

        label = name or header_para.text.strip() or f"paragraph {header_para.id}"
        if not name:
            warnings.append(f'project entry at paragraph {header_para.id}: could not detect a project name')
        if not bullet_paras:
            warnings.append(f"{label}: no bullets detected")

        entry_id = _fresh_id(name or "project", taken_ids)
        entries.append(
            Project(
                id=entry_id,
                name=name,
                tech=tech,
                date=date_text,
                link=link,
                url=url,
                bullets=_import_bullets(bullet_paras, entry_id, vocabulary),
            )
        )
    return entries, warnings


def _import_education_entries(body: list[_Para]) -> tuple[list[Education], list[str]]:
    warnings: list[str] = []
    entries: list[Education] = []
    for entry in template_analyze._split_entries(body):
        header_para = entry[0]
        header, _candidates = template_analyze._header_fields_from_text(
            header_para, primary="school", secondary="location", date_field="dates"
        )
        school = _field_text(header_para, header, "school")
        location = _field_text(header_para, header, "location")
        dates_text = _field_text(header_para, header, "dates")

        detail_paras = [p for p in entry[1:] if p.text.strip()]
        degree = ""
        gpa = ""
        show_gpa = False
        coursework: list[str] = []
        details: list[str] = []
        if detail_paras:
            degree_line = detail_paras[0].text.strip()
            gpa_m = _GPA_RE.search(degree_line)
            if gpa_m:
                degree = degree_line[: gpa_m.start()].strip()
                gpa = gpa_m.group(1).strip()
                show_gpa = True
            else:
                degree = degree_line
            for p in detail_paras[1:]:
                text = p.text.strip()
                cw_m = _COURSEWORK_RE.match(text)
                if cw_m:
                    coursework = [c.strip() for c in cw_m.group(1).split(",") if c.strip()]
                else:
                    details.append(text)

        label = school or header_para.text.strip() or f"paragraph {header_para.id}"
        if not school:
            warnings.append(f'education entry at paragraph {header_para.id}: could not detect a school name')
        if not degree:
            warnings.append(f"{label}: no degree line detected")

        entries.append(
            Education(
                school=school,
                degree=degree,
                dates=dates_text,
                location=location,
                coursework=coursework,
                gpa=gpa,
                show_gpa=show_gpa,
                details=details,
            )
        )
    return entries, warnings


def _import_skill_groups(body: list[_Para]) -> tuple[list[SkillGroup], list[str]]:
    warnings: list[str] = []
    groups: list[SkillGroup] = []
    for p in body:
        if not p.text.strip():
            continue
        spans = template_analyze._skills_spans(p)
        if spans is None:
            warnings.append(
                f"skills line at paragraph {p.id} ({p.text.strip()!r}) is not "
                "'Label: item, item' shaped and was skipped"
            )
            continue
        label_span, body_span, _sep = spans
        label = p.text[label_span.start : label_span.end].strip()
        items = [i.strip() for i in p.text[body_span.start : body_span.end].split(",") if i.strip()]
        if label and items:
            groups.append(SkillGroup(label=label, items=items))
    return groups, warnings


def _import_list_items(
    body: list[_Para], vocabulary: set[str], taken_ids: set[str]
) -> list[ListItem]:
    items: list[ListItem] = []
    for p in body:
        text = p.text.strip()
        if not text:
            continue
        item_id = _fresh_id(text, taken_ids)
        items.append(ListItem(id=item_id, text=text, tags=_seed_tags(text, vocabulary)))
    return items


def import_from_analysis(
    result: AnalyzeResult, doc, *, known_tags: set[str] | None = None
) -> ImportedResume:
    """Build a `MasterResume` draft from `result` (an already-run `analyze_docx` call)
    and the open `doc` it was computed from.

    `known_tags` seeds the deterministic tag matcher; defaults to the built-in alias
    table when the caller has no existing resume's vocabulary to union in (a brand new
    workspace's first import). Passing an existing resume's `tag_vocabulary` lets a
    re-import recognize that resume's own established tag spellings too.
    """
    warnings: list[str] = [i.message for i in result.issues if not i.blocking]
    paras = template_analyze._load_paras(doc)
    vocabulary = _default_vocabulary() if known_tags is None else set(known_tags)

    contact = _import_contact(paras)

    entry_ids: set[str] = set()
    section_ids: set[str] = set()
    sections: list[Section] = []

    for sec in result.sections:
        body = paras[sec.body_start : sec.body_end]
        section_id = _fresh_id(sec.heading_text, section_ids)
        if sec.key == "experience":
            entries, warns = _import_experience_entries(body, vocabulary, entry_ids)
            warnings.extend(warns)
            sections.append(
                ExperienceSection(id=section_id, title=sec.heading_text, entries=entries)
            )
        elif sec.key == "projects":
            entries, warns = _import_project_entries(body, vocabulary, entry_ids)
            warnings.extend(warns)
            sections.append(
                ProjectSection(id=section_id, title=sec.heading_text, entries=entries)
            )
        elif sec.key == "education":
            edu_entries, warns = _import_education_entries(body)
            warnings.extend(warns)
            sections.append(
                EducationSection(id=section_id, title=sec.heading_text, entries=edu_entries)
            )
        elif sec.key == "skills":
            groups, warns = _import_skill_groups(body)
            warnings.extend(warns)
            sections.append(
                SkillsSection(id=section_id, title=sec.heading_text, entries=groups)
            )
        elif sec.key == "list":
            list_items = _import_list_items(body, vocabulary, entry_ids)
            sections.append(
                ListSection(id=section_id, title=sec.heading_text, entries=list_items)
            )

    resume = MasterResume(contact=contact, sections=sections)
    used_tags = sorted({t for b in resume.all_bullets() for t in b.tags if t != UNTAGGED})
    resume = resume.model_copy(update={"tag_vocabulary": used_tags})

    untagged = sum(1 for b in resume.all_bullets() for t in b.tags if t == UNTAGGED)
    if untagged:
        warnings.append(
            f"{untagged} bullet(s) could not be matched to a known tag and were "
            f'marked "{UNTAGGED}" — retag them before saving, or run the optional '
            "tag suggestion pass."
        )

    return ImportedResume(resume=resume, warnings=warnings, untagged_bullet_count=untagged)
