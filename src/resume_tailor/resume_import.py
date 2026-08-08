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
from .template_profile import ContactSlot

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


def _field_text(entry: list[_Para], header: HeaderFieldMapping, field: str) -> str:
    """Slice `header`'s span for `field` out of its own paragraph, or "" when absent.

    Takes the whole entry, not just the header paragraph, because a table layout's
    location/dates fields live on a *different* paragraph than the header (the row's
    other cell) — `header.fields[field].span.paragraph_id` says which one; slicing the
    header paragraph's text unconditionally would silently read the wrong string (or
    the wrong offsets) the moment that's true.
    """
    opt = header.fields.get(field)
    if opt is None or not opt.present or opt.span is None:
        return ""
    para = next((p for p in entry if p.id == opt.span.paragraph_id), None)
    if para is None:
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


def _paragraph_hyperlink_url(para: _Para) -> str:
    """First resolvable `w:hyperlink` target on `para`, or ""."""
    for child in para.paragraph._p.xpath("w:hyperlink"):
        target = docx_text.hyperlink_target(para.paragraph, child)
        if target:
            return target
    return ""


def _import_contact_from_paragraph(name: str, contact_para: _Para | None) -> Contact:
    """One joined contact line, split on its own separator — today's exact contract,
    used whenever the contact block is a single paragraph (every paragraph-layout
    resume, and any table layout whose contact info still fits in one cell)."""
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


def _import_contact_from_slots(
    name: str, slots: list[ContactSlot], by_id: dict[int, _Para]
) -> Contact:
    """One paragraph per contact field — a table layout's own cells, already
    classified by `template_analyze._detect_name_and_contact` — so each slot's text
    supplies exactly the field(s) it was classified as, with no further splitting."""
    fields = {"email": "", "phone": "", "location": "", "linkedin": "", "github": ""}
    for slot in slots:
        para = by_id.get(slot.paragraph_id)
        if para is None:
            continue
        text = para.text.strip()
        for field in slot.fields:
            if fields.get(field):
                continue
            if field == "email":
                m = template_analyze._EMAIL_RE.search(text)
                fields["email"] = m.group(0) if m else text
            elif field in ("linkedin", "github"):
                fields[field] = _paragraph_hyperlink_url(para) or text
            elif field in fields:
                fields[field] = text
    return Contact(
        name=name,
        email=fields["email"],
        phone=fields["phone"],
        location=fields["location"],
        linkedin=fields["linkedin"],
        github=fields["github"],
    )


def _import_contact(paras: list[_Para], first_heading_id: int | None) -> Contact:
    """Best-effort contact extraction using the same name/contact-block detection
    `template_analyze` uses for template mapping (`_detect_name_and_contact`) rather
    than a fixed `paras[0]`/`paras[1]` convention — which breaks the moment the
    document opens with an empty body paragraph before its table (as this codebase's
    own table-layout documents do: the name lands at paragraph 1, not 0) or spreads
    name/address/email/phone across several paragraphs.
    """
    name_id, contact_para, slots, _unmapped = template_analyze._detect_name_and_contact(
        paras, first_heading_id
    )
    by_id = {p.id: p for p in paras}
    name = by_id[name_id].text.strip() if name_id in by_id else ""

    if slots:
        return _import_contact_from_slots(name, slots, by_id)
    return _import_contact_from_paragraph(name, contact_para)


def _import_experience_entries(
    body: list[_Para], vocabulary: set[str], taken_ids: set[str]
) -> tuple[list[Experience], list[str]]:
    warnings: list[str] = []
    entries: list[Experience] = []
    for entry in template_analyze._split_entries(body):
        header_para = entry[0]
        header, _candidates = template_analyze._entry_header_fields(
            entry, primary="company", secondary="location", date_field="dates"
        )
        company = _field_text(entry, header, "company")
        location = _field_text(entry, header, "location")
        dates_text = _field_text(entry, header, "dates")

        rest = entry[1:]
        main_rest = template_analyze._entry_main_paragraphs(entry)[1:]
        titles = [p for p in main_rest if not p.is_bullet and p.text.strip()]
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

        header, _candidates = template_analyze._entry_header_fields(
            entry,
            primary="name",
            secondary="tech",
            date_field="date",
            exclude_after=exclude_after,
        )
        name = _field_text(entry, header, "name")
        tech_text = _field_text(entry, header, "tech")
        tech = [t.strip() for t in tech_text.split(",") if t.strip()]
        date_text = _field_text(entry, header, "date")

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
        header, _candidates = template_analyze._entry_header_fields(
            entry, primary="school", secondary="location", date_field="dates"
        )
        school = _field_text(entry, header, "school")
        location = _field_text(entry, header, "location")
        dates_text = _field_text(entry, header, "dates")

        # Main-cell paragraphs only: a table layout's location/dates cell must not be
        # read as a degree line or a detail — see `_entry_main_paragraphs`.
        main_rest = template_analyze._entry_main_paragraphs(entry)[1:]
        detail_paras = [p for p in main_rest if p.text.strip()]
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

    non_blank = [p for p in body if p.text.strip()]
    cross_pairs = template_analyze._skills_rows_across_cells(non_blank)
    if cross_pairs is not None:
        # Table layout: a label cell and a value cell, side by side — every row is one
        # group, unlike the single-paragraph path below where one line is one group.
        for lp, rp in cross_pairs:
            label = lp.text.strip()
            if label.endswith(":"):
                label = label[:-1].rstrip()
            items = [i.strip() for i in rp.text.split(",") if i.strip()]
            if label and items:
                groups.append(SkillGroup(label=label, items=items))
            else:
                warnings.append(
                    f"skills row at paragraph {lp.id} ({lp.text.strip()!r}) could not "
                    "be read as a label/value pair and was skipped"
                )
        return groups, warnings

    for p in non_blank:
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

    first_heading_id = result.sections[0].heading_paragraph_id if result.sections else None
    contact = _import_contact(paras, first_heading_id)

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


# --------------------------------------------------------------------------------------
# Merging an imported draft into an existing master resume
# --------------------------------------------------------------------------------------


def _match_key(text: str) -> str:
    """Case/punctuation-insensitive identity key for merge matching.

    Deliberately not `config.slugify`: slugify caps its output at 40 characters, which
    is fine for minting a short id but wrong for an equality key — two distinct
    50-character company names sharing a 40-character prefix would slugify to the same
    string and one would silently overwrite the other on merge. This has no length cap.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class MergeStats(BaseModel):
    """What `merge_into` actually did, named rather than just counted — the caller
    surfaces these names so a near-miss duplicate (two spellings of the same school,
    say) is visible immediately instead of buried in a total."""

    updated: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    added_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _remint_bullets(bullets: list[Bullet], entry_id: str) -> list[Bullet]:
    """Bullets carry the id of the entry that owns them. On a merge match, the
    incoming bullets were minted under the incoming entry's own id — which is
    discarded, since the existing entry's id is what survives the merge — so they must
    be re-numbered under that surviving id instead."""
    return [b.model_copy(update={"id": f"{entry_id}_b{i}"}) for i, b in enumerate(bullets, start=1)]


def _target_section_index(sections: list[Section], kind: str, title: str) -> int | None:
    """Which existing section (by index) unmatched incoming entries of `kind` should
    be appended to, or `None` if a brand-new section must be created. First rule that
    applies:

    1. An existing section of `kind` whose title matches `title` (via `_match_key`).
    2. Else an existing *empty* section of `kind` — adopted, so a fresh workspace's
       default-titled placeholder sections (see `workspace._STARTER_RESUME`) receive
       the import instead of a same-kind duplicate being created beside them. The
       caller is responsible for actually renaming it.
    3. Else, if exactly one section of `kind` exists, use it — avoids splitting content
       across an ambiguous second section (e.g. skills vs. "additional information")
       when there is no real conflict to resolve.
    4. Else `None` — the caller creates a new section.

    By the time rule 3 is reached, rule 2 has already ruled out every same-kind section
    being empty, so rule 3 never silently claims an empty section under a different
    name than the caller would have picked via rule 2.
    """
    same_kind = [(i, s) for i, s in enumerate(sections) if s.kind == kind]
    for i, s in same_kind:
        if _match_key(s.title) == _match_key(title):
            return i
    for i, s in same_kind:
        if not s.entries:
            return i
    if len(same_kind) == 1:
        return same_kind[0][0]
    return None


def _place_leftovers(
    sections: list[Section],
    kind: str,
    inc_title: str,
    taken_section_ids: set[str],
    stats: MergeStats,
    section_cls: type,
) -> int:
    """Resolve (creating if needed) the section leftover incoming entries of `kind`
    should be appended to, and return its index. Shared tail end of every per-kind
    merge function once it has a non-empty `leftovers` list."""
    target_idx = _target_section_index(sections, kind, inc_title)
    if target_idx is None:
        new_section = section_cls(id=_fresh_id(inc_title, taken_section_ids), title=inc_title, entries=[])
        sections.append(new_section)
        stats.added_sections.append(inc_title)
        return len(sections) - 1
    if not sections[target_idx].entries:
        sections[target_idx] = sections[target_idx].model_copy(update={"title": inc_title})
    return target_idx


def _merge_experience(
    sections: list[Section],
    incoming_sections: list[Section],
    taken_entry_ids: set[str],
    taken_section_ids: set[str],
    stats: MergeStats,
) -> None:
    existing_by_key: dict[str, list[tuple[int, int]]] = {}
    for si, sec in enumerate(sections):
        if sec.kind != "experience":
            continue
        for ei, e in enumerate(sec.entries):
            existing_by_key.setdefault(_match_key(e.company), []).append((si, ei))

    for inc_sec in incoming_sections:
        if inc_sec.kind != "experience":
            continue
        leftovers: list[Experience] = []
        for inc in inc_sec.entries:
            queue = existing_by_key.get(_match_key(inc.company))
            if queue:
                si, ei = queue.pop(0)
                existing = sections[si].entries[ei]
                sections[si].entries[ei] = existing.model_copy(
                    update={
                        "company": inc.company,
                        "title": inc.title,
                        "location": inc.location,
                        "start": inc.start,
                        "end": inc.end,
                        "bullets": _remint_bullets(inc.bullets, existing.id),
                    }
                )
                stats.updated.append(inc.company)
            else:
                leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = _place_leftovers(
            sections, "experience", inc_sec.title, taken_section_ids, stats, ExperienceSection
        )
        for inc in leftovers:
            entry_id = _fresh_id(inc.company or "role", taken_entry_ids)
            sections[target_idx].entries.append(
                inc.model_copy(update={"id": entry_id, "bullets": _remint_bullets(inc.bullets, entry_id)})
            )
            stats.added.append(inc.company)


def _merge_projects(
    sections: list[Section],
    incoming_sections: list[Section],
    taken_entry_ids: set[str],
    taken_section_ids: set[str],
    stats: MergeStats,
) -> None:
    existing_by_key: dict[str, list[tuple[int, int]]] = {}
    for si, sec in enumerate(sections):
        if sec.kind != "project":
            continue
        for ei, e in enumerate(sec.entries):
            existing_by_key.setdefault(_match_key(e.name), []).append((si, ei))

    for inc_sec in incoming_sections:
        if inc_sec.kind != "project":
            continue
        leftovers: list[Project] = []
        for inc in inc_sec.entries:
            queue = existing_by_key.get(_match_key(inc.name))
            if queue:
                si, ei = queue.pop(0)
                existing = sections[si].entries[ei]
                sections[si].entries[ei] = existing.model_copy(
                    update={
                        "name": inc.name,
                        "tech": inc.tech,
                        "date": inc.date,
                        "link": inc.link,
                        "url": inc.url,
                        "bullets": _remint_bullets(inc.bullets, existing.id),
                    }
                )
                stats.updated.append(inc.name)
            else:
                leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = _place_leftovers(
            sections, "project", inc_sec.title, taken_section_ids, stats, ProjectSection
        )
        for inc in leftovers:
            entry_id = _fresh_id(inc.name or "project", taken_entry_ids)
            sections[target_idx].entries.append(
                inc.model_copy(update={"id": entry_id, "bullets": _remint_bullets(inc.bullets, entry_id)})
            )
            stats.added.append(inc.name)


def _merge_education(
    sections: list[Section], incoming_sections: list[Section], taken_section_ids: set[str], stats: MergeStats
) -> None:
    existing_by_key: dict[str, list[tuple[int, int]]] = {}
    for si, sec in enumerate(sections):
        if sec.kind != "education":
            continue
        for ei, e in enumerate(sec.entries):
            existing_by_key.setdefault(_match_key(e.school), []).append((si, ei))

    for inc_sec in incoming_sections:
        if inc_sec.kind != "education":
            continue
        leftovers: list[Education] = []
        for inc in inc_sec.entries:
            queue = existing_by_key.get(_match_key(inc.school))
            if queue:
                si, ei = queue.pop(0)
                sections[si].entries[ei] = inc.model_copy()
                stats.updated.append(inc.school)
            else:
                leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = _place_leftovers(
            sections, "education", inc_sec.title, taken_section_ids, stats, EducationSection
        )
        for inc in leftovers:
            sections[target_idx].entries.append(inc.model_copy())
            stats.added.append(inc.school)


def _merge_skills(
    sections: list[Section], incoming_sections: list[Section], taken_section_ids: set[str], stats: MergeStats
) -> None:
    existing_by_key: dict[str, list[tuple[int, int]]] = {}
    for si, sec in enumerate(sections):
        if sec.kind != "skills":
            continue
        for ei, e in enumerate(sec.entries):
            existing_by_key.setdefault(_match_key(e.label), []).append((si, ei))

    for inc_sec in incoming_sections:
        if inc_sec.kind != "skills":
            continue
        leftovers: list[SkillGroup] = []
        for inc in inc_sec.entries:
            queue = existing_by_key.get(_match_key(inc.label))
            if queue:
                si, ei = queue.pop(0)
                existing = sections[si].entries[ei]
                # Keep the existing label's own casing/wording — its match key already
                # equals the incoming one, so only the items are actually "refreshed".
                sections[si].entries[ei] = existing.model_copy(update={"items": inc.items})
                stats.updated.append(existing.label)
            else:
                leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = _place_leftovers(
            sections, "skills", inc_sec.title, taken_section_ids, stats, SkillsSection
        )
        for inc in leftovers:
            sections[target_idx].entries.append(inc.model_copy())
            stats.added.append(inc.label)


def _merge_list_items(
    sections: list[Section],
    incoming_sections: list[Section],
    taken_entry_ids: set[str],
    taken_section_ids: set[str],
    stats: MergeStats,
) -> None:
    existing_keys: set[str] = set()
    for sec in sections:
        if sec.kind != "list":
            continue
        for e in sec.entries:
            existing_keys.add(_match_key(e.text))

    for inc_sec in incoming_sections:
        if inc_sec.kind != "list":
            continue
        leftovers: list[ListItem] = []
        for inc in inc_sec.entries:
            key = _match_key(inc.text)
            if key in existing_keys:
                continue
            existing_keys.add(key)  # a repeat within this same incoming batch is still a dup
            leftovers.append(inc)

        if not leftovers:
            continue
        target_idx = _place_leftovers(
            sections, "list", inc_sec.title, taken_section_ids, stats, ListSection
        )
        for inc in leftovers:
            entry_id = _fresh_id(inc.text, taken_entry_ids)
            sections[target_idx].entries.append(inc.model_copy(update={"id": entry_id}))
            stats.added.append(inc.text)


def _merge_contact(existing: Contact, incoming: Contact) -> Contact:
    """Field-by-field merge, only overwriting where `incoming` actually has a value.

    A blanket overwrite would blank a manually-curated LinkedIn URL the moment an
    export loses its hyperlink (a documented gotcha in this codebase) even though
    nothing about that field genuinely changed.
    """
    updates = {
        field_name: value
        for field_name in ("name", "email", "phone", "location", "linkedin", "github", "links")
        if (value := getattr(incoming, field_name))
    }
    return existing.model_copy(update=updates)


def merge_into(existing: MasterResume, incoming: MasterResume) -> tuple[MasterResume, MergeStats]:
    """Fold `incoming` (typically the `.resume` of an `ImportedResume`) into `existing`
    by matching entries on company/project name, school, skills label, or exact list
    text — never by section. An incoming section whose title doesn't match an existing
    one (e.g. "LEADERSHIP" vs. an existing "LEADERSHIP EXPERIENCE") must not cause an
    entry that already lives in that differently-titled section to be duplicated.

    A matched entry is updated *in place*, keeping its existing id (and, for
    experience/project, its bullets re-minted under that id) so nothing referencing it
    elsewhere breaks. An unmatched incoming entry is added — see
    `_target_section_index` for where. Anything in `existing` with no counterpart in
    `incoming` is left completely untouched, including its id, bullets, and tags.

    Pure: no I/O, no LLM call. `MasterResume.tag_vocabulary` is the union of both
    sides; `summary_variants` and `_comment` are carried over from `existing` verbatim,
    since `incoming` (an import) never produces them.
    """
    sections: list[Section] = [s.model_copy(deep=True) for s in existing.sections]
    stats = MergeStats()

    taken_entry_ids: set[str] = {
        e.id for s in sections if s.kind in ("experience", "project", "list") for e in s.entries
    }
    taken_section_ids: set[str] = {s.id for s in sections}

    _merge_experience(sections, incoming.sections, taken_entry_ids, taken_section_ids, stats)
    _merge_projects(sections, incoming.sections, taken_entry_ids, taken_section_ids, stats)
    _merge_education(sections, incoming.sections, taken_section_ids, stats)
    _merge_skills(sections, incoming.sections, taken_section_ids, stats)
    _merge_list_items(sections, incoming.sections, taken_entry_ids, taken_section_ids, stats)

    merged = MasterResume(
        comment=existing.comment,
        contact=_merge_contact(existing.contact, incoming.contact),
        summary_variants=existing.summary_variants,
        sections=sections,
        tag_vocabulary=sorted(set(existing.tag_vocabulary) | set(incoming.tag_vocabulary)),
    )
    return merged, stats
