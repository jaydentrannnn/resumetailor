"""The Edit-layout-in-Word skeleton: the live template with «tokens» for every field.

`make_skeleton` renders the installed tagged template with a *sentinel* resume — the
person's own sections (ids, titles, order), two entries each, every field a unique
letters-only marker — then swaps each marker for its «token» (`skeleton_tokens`). The
result has the template's real fonts, spacing, tables and borders; only the words are
placeholders. Headings carry an invisible bookmark (`rt_sec_<n>`) so the read-back
(`skeleton_parse.py`) finds each section even after its text is retyped, and Word
comments explain what repeats. No LLM, and no tag syntax ever reaches the file.
"""

from __future__ import annotations

import io
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ..content.data import (
    Bullet,
    Contact,
    CustomField,
    Education,
    EducationSection,
    Experience,
    ExperienceSection,
    ListItem,
    ListSection,
    MasterResume,
    Project,
    ProjectSection,
    SkillGroup,
    SkillsSection,
)
from . import docx_text, render, skeleton_tokens, template_tagging
from .skeleton_tokens import BY_SENTINEL, CUSTOM_SENTINEL, DATE_RANGE, label_text
from .template_profile import CharSpan, TemplateProfile, active_layout

BOOKMARK_PREFIX = "rt_sec_"
COMMENT_AUTHOR = "ResumeTailor"
_SECTION_KINDS = frozenset({"experience", "education", "project", "skills", "list"})
_ENTRY_NOUN = {"experience": "job", "education": "school", "project": "project",
               "skills": "skill group", "list": "line"}  # fmt: skip
_DEFAULT_SECTIONS = (("education", "Education", "education"),
                     ("experience", "Experience", "experience"),
                     ("projects", "Projects", "project"), ("skills", "Skills", "skills"))


@dataclass
class SkeletonSection:
    bookmark: str
    id: str
    title: str
    kind: str


@dataclass
class Skeleton:
    raw: bytes
    sections: list[SkeletonSection] = field(default_factory=list)
    #: The template's custom lines: key, label and the text the line had.
    custom: list[dict] = field(default_factory=list)
    #: "kind.field" -> sample text that must keep the template's own style (dates: the
    #: baseline's date text is what `date_style.detect` reads the month style from).
    samples: dict[str, str] = field(default_factory=dict)

    def meta(self) -> dict:
        """JSON-able description `skeleton_parse.parse_skeleton` reads back."""
        return {
            "sections": [vars(s) for s in self.sections],
            "custom": list(self.custom),
            "samples": dict(self.samples),
        }


def _sentinel_entries(kind: str, sid: str) -> list:
    """Two sentinel entries of `kind`: the second exists only so the layout file shows
    (and the read-back can measure) the spacing between entries."""
    out = []
    for n in (1, 2):
        uid = f"skel-{sid}-{n}"
        marker = "JOB" if kind == "experience" else "PROJ"
        bullet = [Bullet(id=f"{uid}-b", text=f"QQ{marker}BULLETQQ")]
        if kind == "experience":
            out.append(Experience(
                id=uid, company="QQCOMPANYQQ", title="QQJOBTITLEQQ", location="QQJOBLOCQQ",
                start="QQJOBSTARTQQ", end="QQJOBENDQQ", bullets=bullet,
            ))  # fmt: skip
        elif kind == "education":
            out.append(Education(
                school="QQSCHOOLQQ", degree="QQDEGREEQQ", dates="QQEDUDATESQQ",
                location="QQEDULOCQQ", details=["QQEDUDETAILQQ"],
            ))  # fmt: skip
        elif kind == "project":
            out.append(Project(
                id=uid, name="QQPROJECTQQ", tech=["QQTECHQQ"], date="QQPROJDATEQQ",
                link="QQLINKQQ", url="https://example.com", bullets=bullet,
            ))  # fmt: skip
        elif kind == "skills":
            out.append(SkillGroup(label="QQSKILLLABELQQ", items=["QQSKILLSQQ"]))
        elif kind == "list":
            out.append(ListItem(id=uid, text="QQLISTITEMQQ"))
    return out


_SECTION_MODEL = {"experience": ExperienceSection, "education": EducationSection,
                  "project": ProjectSection, "skills": SkillsSection, "list": ListSection}


def sentinel_resume(resume: MasterResume | None, profile: TemplateProfile) -> MasterResume:
    """The person's section list (or the template's, or a standard one), every entry and
    contact field replaced by sentinels; custom lines carry `QQCUSTOM<i>QQ`."""
    if resume is not None and resume.sections:
        shape = [(s.id, s.title, s.kind) for s in resume.sections]
    elif profile.sections:
        shape = [(s.id, s.title, s.kind) for s in profile.sections]
    else:
        shape = list(_DEFAULT_SECTIONS)
    sections = [
        _SECTION_MODEL[kind](id=sid, title=title, entries=_sentinel_entries(kind, sid))
        for sid, title, kind in shape
    ]
    contact = Contact(
        name="QQNAMEQQ", email="QQEMAILQQ", phone="QQPHONEQQ", location="QQLOCATIONQQ",
        linkedin="https://www.linkedin.com/in/example", github="https://github.com/example",
    )  # fmt: skip
    custom = [
        CustomField(key=slot.key, label=slot.label, value=f"QQCUSTOM{i}QQ")
        for i, slot in enumerate(profile.custom_fields)
    ]
    return MasterResume(contact=contact, sections=sections, custom_fields=custom)


def _unwrap_hyperlinks(paragraph: Paragraph) -> None:
    """Lift every hyperlink's runs into the paragraph in place: the link is a render-time
    detail, and a token inside one would carry a stray URL into the layout file."""
    for link in paragraph._p.findall(qn("w:hyperlink")):
        for child in list(link):
            link.addprevious(child)
        link.getparent().remove(link)


def sentinel_matches(text: str, *, header_zone: bool) -> list[tuple[int, int, str, str]]:
    """(start, end, kind, label) for every sentinel in `text`, left to right."""
    found: list[tuple[int, int, str, str]] = []
    taken: list[tuple[int, int]] = []

    def add(start: int, end: int, kind: str, label: str) -> None:
        if any(start < e and s < end for s, e in taken):
            return
        taken.append((start, end))
        found.append((start, end, kind, label))

    for m in DATE_RANGE.finditer(text):
        add(m.start(), m.end(), "experience", "Job dates")
    for m in CUSTOM_SENTINEL.finditer(text):
        add(m.start(), m.end(), "custom", m.group(1))
    for sentinel, token in BY_SENTINEL.items():
        if not sentinel.startswith("QQ") and not header_zone:
            continue  # "LinkedIn"/"GitHub" are tokens only in the contact block
        start = text.find(sentinel)
        while start != -1:
            add(start, start + len(sentinel), token.kind, token.label)
            start = text.find(sentinel, start + len(sentinel))
    return sorted(found)


def strip_bookmarks(doc) -> None:
    """Remove the skeleton's own `rt_sec_*` heading bookmarks (start and matching end).

    The read-back becomes a baseline, so it must not carry them: a later skeleton of that
    template would otherwise hold two marks of each name."""
    body = doc.element.body
    ids = set()
    for mark in list(body.iter(qn("w:bookmarkStart"))):
        if (mark.get(qn("w:name")) or "").startswith(BOOKMARK_PREFIX):
            ids.add(mark.get(qn("w:id")))
            mark.getparent().remove(mark)
    for mark in list(body.iter(qn("w:bookmarkEnd"))):
        if mark.get(qn("w:id")) in ids:
            mark.getparent().remove(mark)


def _add_bookmark(paragraph: Paragraph, name: str, bookmark_id: int) -> None:
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    p_pr = paragraph._p.find(qn("w:pPr"))
    if p_pr is not None:
        p_pr.addnext(start)
    else:
        paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _run_with(paragraph: Paragraph, text: str):
    """The run whose text contains `text`, else the paragraph's first run."""
    for run in paragraph.runs:
        if text in run.text:
            return run
    return paragraph.runs[0] if paragraph.runs else None


@dataclass
class _Para:
    id: int
    paragraph: Paragraph
    in_table: bool
    tokens: list[tuple[str, str]] = field(default_factory=list)  # (kind, label)

    @property
    def section_kinds(self) -> set[str]:
        return {k for k, _ in self.tokens if k in _SECTION_KINDS}


def _tokenise(doc, profile: TemplateProfile) -> list[_Para]:
    """Swap every sentinel for its «token»; returns the paragraphs with what they hold."""
    paras = [
        _Para(i, p, loc is not None)
        for i, (p, loc) in enumerate(docx_text.iter_document_paragraphs(doc))
    ]
    header_zone = True
    for para in paras:
        text = para.paragraph.text
        found = sentinel_matches(text, header_zone=header_zone)
        if not found:
            continue
        _unwrap_hyperlinks(para.paragraph)
        for start, end, kind, label in reversed(found):
            if kind == "custom":
                slot = profile.custom_fields[int(label)]
                label = f"custom: {slot.label or slot.key}"
            template_tagging.replace_span_with_tag(
                para.paragraph,
                CharSpan(paragraph_id=para.id, start=start, end=end),
                label_text(label),
            )
            para.tokens.insert(0, (kind, label))
        if para.section_kinds:
            header_zone = False
    return paras


def _headings(paras: list[_Para], sentinel: MasterResume) -> list[tuple[_Para, object]]:
    """Pair each rendered section heading with its section. A heading candidate is any
    non-empty paragraph without tokens; it owns the section-token paragraphs below it up
    to the next candidate, and is matched to the next unmatched section of that kind."""
    candidates: list[tuple[_Para, set[str]]] = []
    for para in paras:
        if para.tokens or not para.paragraph.text.strip():
            if candidates:
                candidates[-1][1].update(para.section_kinds)
            continue
        candidates.append((para, set()))
    pairs: list[tuple[_Para, object]] = []
    queue = list(candidates)
    for section in sentinel.sections:
        for i, (para, kinds) in enumerate(queue):
            if kinds == {section.kind}:
                pairs.append((para, section))
                del queue[: i + 1]
                break
    return pairs


_INTRO = (
    "This is your resume's layout. Change fonts, sizes, bold, spacing, alignment, margins "
    "or borders, or move a «field» — then save and close. Keep each «name» as it is; "
    "delete one you don't want printed. Type «custom: Label» on its own line above the "
    "first section to add a line you can edit in the app."
)
_HEADING_NOTE = (
    "Every section heading takes this heading's font, size, spacing and border — style "
    "this one. On the other headings only the words are read back."
)


def _comment(doc, paragraph: Paragraph, anchor: str, text: str) -> None:
    run = _run_with(paragraph, anchor)
    if run is not None:
        doc.add_comment(run, text=text, author=COMMENT_AUTHOR, initials="RT")


def _annotate(doc, paras: list[_Para], pairs: list[tuple[_Para, object]]) -> list[SkeletonSection]:
    """Bookmark every heading and comment what repeats; returns the section list."""
    sections: list[SkeletonSection] = []
    first_of_kind: dict[str, str] = {}
    name = next((p for p in paras if ("name", "Name") in p.tokens), None)
    if name is not None:
        _comment(doc, name.paragraph, label_text("Name"), _INTRO)
    bounds = [h.id for h, _ in pairs] + [len(paras)]
    for n, (heading, section) in enumerate(pairs):
        bookmark = f"{BOOKMARK_PREFIX}{n}"
        _add_bookmark(heading.paragraph, bookmark, 9000 + n)
        sections.append(SkeletonSection(bookmark, section.id, section.title, section.kind))
        if n == 0:
            _comment(doc, heading.paragraph, heading.paragraph.text[:1], _HEADING_NOTE)
        if section.kind in first_of_kind:
            _comment(
                doc, heading.paragraph, heading.paragraph.text[:1],
                f"Uses the layout of {first_of_kind[section.kind]} above — edit that "
                "section. Only the heading here is read back.",
            )
            continue
        first_of_kind[section.kind] = section.title
        body = paras[heading.id + 1 : bounds[n + 1]]
        lead = skeleton_tokens.ENTRY_LEAD[section.kind]
        leads = [p for p in body if any(lbl == _label(section.kind, lead) for _, lbl in p.tokens)]
        noun = _ENTRY_NOUN[section.kind]
        if leads:
            _comment(doc, leads[0].paragraph, label_text(_label(section.kind, lead)),
                     f"One {noun}: this layout repeats for every {noun} in the section.")
        if len(leads) > 1:
            _comment(doc, leads[1].paragraph, label_text(_label(section.kind, lead)),
                     f"A second {noun}, only to show the space between {noun}s. Edit the "
                     "first one — changes here are ignored.")  # fmt: skip
        bullet = next((p for p in body if any(lbl.endswith("bullet") for _, lbl in p.tokens)), None)
        if bullet is not None:
            _comment(doc, bullet.paragraph, "«", "Repeats for every bullet.")
    return sections


def _label(kind: str, field_name: str) -> str:
    return next(t.label for t in skeleton_tokens.TOKENS if t.kind == kind and t.field == field_name)


def make_skeleton(
    template: Path, profile: TemplateProfile, resume: MasterResume | None
) -> Skeleton:
    """The layout file for the template at `template` (built from `profile`)."""
    sentinel = sentinel_resume(resume, profile)
    layout = active_layout(profile)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "skeleton.docx"
        render.render(sentinel, template=template, out=out, layout=layout)
        doc = docx.Document(str(out))
    strip_bookmarks(doc)  # a template installed from an earlier read-back
    paras = _tokenise(doc, profile)
    sections = _annotate(doc, paras, _headings(paras, sentinel))
    buffer = io.BytesIO()
    doc.save(buffer)
    custom = [
        {"key": s.key, "label": s.label or s.key, "text": s.text} for s in profile.custom_fields
    ]
    style = layout.get("date_style")
    samples = {
        "experience.dates": render.format_range("2023-01", "Present", style),
        "education.dates": render.format_range("2019-09", "2023-06", style),
        "project.date": render.format_month("2024-03", style),
    }
    return Skeleton(raw=buffer.getvalue(), sections=sections, custom=custom, samples=samples)
