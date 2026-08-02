"""Template filling and PDF measurement — the layout half of the pipeline.

This is the only module that touches the document, and it does so mechanically: it maps
already-final strings onto placeholders. No text is generated here, and nothing here is
ever shown to the model.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from docxtpl import DocxTemplate, RichText

from . import config, convert
from .data import MasterResume

#: Word renders hyperlinks in this blue by convention; matching it keeps a rendered
#: project link visually identical to the one in the original export.
_LINK_COLOR = "0000EE"

#: Contact-line separator matching the Google Docs export (U+2022 bullet).
_CONTACT_SEP = " \u2022 "


def format_month(value: str) -> str:
    """Render a `YYYY-MM` month as `Mon YYYY`, passing anything else through.

    Free-text values like "present" are deliberately left alone rather than rejected —
    the master file is hand-maintained and should tolerate a human writing a date the
    way it appears on the resume.
    """
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%b %Y")
    except (ValueError, TypeError):
        return value


def format_range(start: str, end: str) -> str:
    """Format a start/end pair as `Mon YYYY - Mon YYYY` (or free text)."""
    return f"{format_month(start)} - {format_month(end)}"


def _degree_line(edu) -> str:
    """Degree text, optionally with ` | GPA: …` when the editor toggle is on."""
    if edu.show_gpa and edu.gpa.strip():
        return f"{edu.degree} | GPA: {edu.gpa.strip()}"
    return edu.degree


def _education_details(edu) -> list[str]:
    """Detail bullets for one education entry: coursework line first, then free-text."""
    details: list[str] = []
    if edu.coursework:
        details.append("Relevant Coursework: " + ", ".join(edu.coursework))
    details.extend(edu.details)
    return details


def _contact_richtext(resume: MasterResume, tpl: DocxTemplate) -> RichText:
    """Build the contact line as RichText with labelled LinkedIn/GitHub hyperlinks.

    Empty fields (and their separators) are omitted so a missing phone or GitHub does
    not leave a dangling bullet. Labels are short ("LinkedIn", "GitHub") to keep the
    centered line from wrapping when both profiles are present.
    """
    contact = resume.contact
    parts: list[tuple[str, str | None]] = []
    if contact.location.strip():
        parts.append((contact.location.strip(), None))
    if contact.email.strip():
        parts.append((contact.email.strip(), None))
    if contact.phone.strip():
        parts.append((contact.phone.strip(), None))
    if contact.linkedin.strip():
        parts.append(("LinkedIn", contact.linkedin.strip()))
    if contact.github.strip():
        parts.append(("GitHub", contact.github.strip()))

    rt = RichText()
    for i, (text, url) in enumerate(parts):
        if i:
            rt.add(_CONTACT_SEP)
        if url:
            rt.add(
                text,
                url_id=tpl.build_url_id(url),
                color=_LINK_COLOR,
                underline=True,
            )
        else:
            rt.add(text)
    return rt


def build_context(
    resume: MasterResume,
    tpl: DocxTemplate,
    *,
    bullets: dict[str, str] | None = None,
    include_project_links: bool = True,
) -> dict:
    """Assemble the Jinja context for the template.

    `bullets` maps bullet id -> final text and acts as both the content source and the
    selection filter: only bullets appearing in it are rendered. An entry whose bullets
    were all dropped is omitted entirely, which is how the fit loop sheds a whole job or
    project when trimming individual lines is not enough.

    Passing `None` renders the full master resume with its original text — the mode used
    for calibration and template smoke tests.

    `include_project_links=False` suppresses the link label, its hyperlink, and the
    ` | ` separator that precedes them — same empty `RichText` a project with no link
    already produces.
    """

    def lines(source) -> list[str]:
        if bullets is None:
            return [b.text for b in source]
        return [bullets[b.id] for b in source if b.id in bullets]

    experience = []
    for job in resume.experience:
        rendered = lines(job.bullets)
        if not rendered:
            continue
        experience.append(
            {
                "company": job.company,
                "location": job.location,
                "title": job.title,
                "dates": format_range(job.start, job.end),
                "bullets": rendered,
            }
        )

    projects = []
    for proj in resume.projects:
        rendered = lines(proj.bullets)
        if not rendered:
            continue

        # Each project carries its own URL, so the link is built per entry rather than
        # baked into the template — see scripts/build_template.py. The template uses a
        # `{{r }}` RichText tag, so this must always be a RichText even when there is no
        # URL: a bare string there would be injected as raw XML and break on any "&".
        # The " | " separator is part of this RichText so it vanishes with the link;
        # baking it into the tech run left a dangling pipe when links were suppressed.
        link = RichText()
        if include_project_links and proj.link:
            link.add(" | ")
            link.add(
                proj.link,
                url_id=tpl.build_url_id(proj.url) if proj.url else None,
                color=_LINK_COLOR if proj.url else None,
                underline=bool(proj.url),
            )

        projects.append(
            {
                "name": proj.name,
                "tech": ", ".join(proj.tech),
                "link": link,
                "date": proj.date,
                "bullets": rendered,
            }
        )

    # Key is `entries`, never `items`: in Jinja, `group.items` resolves to the dict's
    # built-in method rather than the key, and rendering that method's repr injects
    # invalid markup into the document. Keep context keys clear of dict attribute names.
    skills = [{"label": g.label, "entries": ", ".join(g.items)} for g in resume.skills]

    education = [
        {
            "school": edu.school,
            "location": edu.location,
            "dates": edu.dates,
            "degree_line": _degree_line(edu),
            "details": _education_details(edu),
        }
        for edu in resume.education
    ]

    return {
        "contact": _contact_richtext(resume, tpl),
        "education": education,
        "experience": experience,
        "projects": projects,
        "skills": skills,
    }


def render(
    resume: MasterResume,
    *,
    bullets: dict[str, str] | None = None,
    template: Path | None = None,
    out: Path | None = None,
    include_project_links: bool = True,
) -> Path:
    """Build the context and render it to a .docx.

    Context building and rendering share one `DocxTemplate` instance deliberately:
    `build_url_id` registers hyperlink relationships on the document, so it must run
    against the same object that is ultimately saved.

    `include_project_links=False` renders projects without their link label, separator,
    or hyperlink.
    """
    template = template or config.DEFAULT_TEMPLATE_PATH
    if not template.exists():
        raise FileNotFoundError(
            f"Template not found: {template}\n"
            "Generate it with: python scripts/build_template.py"
        )
    tpl = DocxTemplate(template)
    context = build_context(
        resume, tpl, bullets=bullets, include_project_links=include_project_links
    )

    # autoescape is required, not optional. Without it a literal "&" in the content
    # ("Tools & Languages") is emitted raw into the XML and swallowed as a malformed
    # entity, and RichText hyperlinks render as empty strings. With it, plain strings
    # are escaped and RichText is passed through untouched via its __html__ hook.
    tpl.render(context, autoescape=True)

    out = out or config.OUTPUT_DIR / "tailored.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(out)
    return out


def to_pdf(docx_path: Path, pdf_path: Path | None = None, *, keep_active: bool = False) -> Path:
    """Convert a .docx to PDF using the configured engine (Word or LibreOffice).

    Which engine runs is `config.PDF_BACKEND`; see `convert.py`. Callers that can degrade
    gracefully should catch `RuntimeError` and fall back to the character budget rather
    than failing the run — `fit.fit` does exactly that.

    `keep_active` asks the engine to stay resident between conversions. Word honours it
    (its ~9s startup would otherwise be paid on every fit iteration); LibreOffice ignores
    it, being a one-shot process.
    """
    pdf_path = pdf_path or docx_path.with_suffix(".pdf")
    return convert.convert(docx_path, pdf_path, keep_active=keep_active)


def page_count(pdf_path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(pdf_path)).pages)


def line_count(pdf_path: Path) -> int:
    """Total non-blank text lines in the PDF, as physically laid out.

    Layout-mode extraction preserves visual line breaks, so a wrapped bullet counts once
    per rendered line rather than once per paragraph. This is the same measurement
    `scripts/calibrate.py` used to derive `config.LINES_PER_PAGE`, so the two are directly
    comparable — which is what lets the fit loop judge how full a page really is instead
    of trusting the character-budget estimate.
    """
    from pypdf import PdfReader

    total = 0
    for page in PdfReader(str(pdf_path)).pages:
        text = page.extract_text(extraction_mode="layout")
        total += sum(1 for line in text.split("\n") if line.strip())
    return total


def measure(docx_path: Path, *, keep_active: bool = False) -> int:
    """Render `docx_path` to PDF and return its page count."""
    return page_count(to_pdf(docx_path, keep_active=keep_active))


def measure_detail(docx_path: Path, *, keep_active: bool = False) -> tuple[int, int]:
    """Render `docx_path` to PDF and return `(page_count, line_count)`.

    One conversion, both numbers: pages decide overflow, lines decide underflow.
    """
    pdf = to_pdf(docx_path, keep_active=keep_active)
    return page_count(pdf), line_count(pdf)
