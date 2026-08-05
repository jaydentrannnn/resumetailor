"""Template filling and PDF measurement — the layout half of the pipeline.

This is the only module that touches the document, and it does so mechanically: it maps
already-final strings onto placeholders. No text is generated here, and nothing here is
ever shown to the model.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

from docxtpl import DocxTemplate, RichText

from . import config, convert
from .data import MasterResume
from .template_profile import ContactField, active_layout

#: Word renders hyperlinks in this blue by convention; matching it keeps a rendered
#: project link visually identical to the one in the original export.
_LINK_COLOR = "0000EE"

#: Character style LibreOffice requires on hyperlink runs to export them as PDF Link
#: annotations. Without the style *and* a matching definition in styles.xml, soffice
#: paints the blue underline but drops the click target (Word keeps links either way).
#: See https://bugs.documentfoundation.org/show_bug.cgi?id=146575 and the Stack Overflow
#: report that confirmed editing a link in LO injects this rStyle.
_HYPERLINK_STYLE = "InternetLink"

#: Contact-line separator matching the Google Docs export (U+2022 bullet).
_CONTACT_SEP = " \u2022 "


def _add_hyperlink(rt: RichText, text: str, url_id: str | None) -> None:
    """Append linked (or plain) text with the LibreOffice-safe InternetLink run style.

    `url_id` None means a labelled project with no URL — keep the label, skip the link.
    """
    if url_id:
        rt.add(
            text,
            url_id=url_id,
            style=_HYPERLINK_STYLE,
            color=_LINK_COLOR,
            underline=True,
        )
    else:
        rt.add(text)


def _ensure_pdf_hyperlink_styles(docx_path: Path) -> None:
    """Guarantee every hyperlink run carries InternetLink and the style is defined.

    Google Docs exports (and therefore our template) omit the Hyperlink/InternetLink
    character style. docxtpl can emit `w:rStyle` via RichText, but LibreOffice still
    ignores the link unless `styles.xml` defines that styleId. Patching after save keeps
    existing templates working without a rebuild.
    """
    import re

    raw = docx_path.read_bytes()
    out_buf = io.BytesIO()
    changed = False
    with zipfile.ZipFile(io.BytesIO(raw), "r") as zin, zipfile.ZipFile(
        out_buf, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "word/document.xml":
                xml = data.decode("utf-8")

                def inject(match: re.Match[str]) -> str:
                    """Add InternetLink rStyle to the first rPr inside one hyperlink."""
                    block = match.group(0)
                    if f'w:val="{_HYPERLINK_STYLE}"' in block:
                        return block
                    if "<w:rPr>" not in block:
                        # RichText always emits rPr when color/underline/style are set; a
                        # bare hyperlink still needs a property bag for the style.
                        block = block.replace(
                            "<w:r>",
                            f'<w:r><w:rPr><w:rStyle w:val="{_HYPERLINK_STYLE}"/></w:rPr>',
                            1,
                        )
                        return block
                    return re.sub(
                        r"(<w:rPr>)",
                        rf'\1<w:rStyle w:val="{_HYPERLINK_STYLE}"/>',
                        block,
                        count=1,
                    )

                new_xml = re.sub(
                    r"<w:hyperlink\b[^>]*>.*?</w:hyperlink>",
                    inject,
                    xml,
                    flags=re.S,
                )
                if new_xml != xml:
                    changed = True
                    data = new_xml.encode("utf-8")
            elif info.filename == "word/styles.xml":
                xml = data.decode("utf-8")
                if f'w:styleId="{_HYPERLINK_STYLE}"' not in xml:
                    style = (
                        f'<w:style w:type="character" w:styleId="{_HYPERLINK_STYLE}">'
                        f'<w:name w:val="Hyperlink"/>'
                        f"<w:rPr>"
                        f'<w:color w:val="{_LINK_COLOR}"/>'
                        f'<w:u w:val="single"/>'
                        f"</w:rPr>"
                        f"</w:style>"
                    )
                    if "</w:styles>" not in xml:
                        raise RuntimeError(
                            f"{docx_path.name}: styles.xml missing </w:styles>; "
                            "cannot register InternetLink for PDF hyperlinks."
                        )
                    xml = xml.replace("</w:styles>", style + "</w:styles>")
                    changed = True
                    data = xml.encode("utf-8")
            # ZipInfo date_time must stay valid; writestr(info, data) preserves metadata.
            zout.writestr(info, data)

    if changed:
        docx_path.write_bytes(out_buf.getvalue())


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


def _contact_richtext(
    resume: MasterResume,
    tpl: DocxTemplate,
    *,
    field_order: list[ContactField] | None = None,
    separator: str | None = None,
) -> RichText:
    """Build the contact line as RichText with labelled LinkedIn/GitHub hyperlinks.

    Empty fields (and their separators) are omitted so a missing phone or GitHub does
    not leave a dangling separator. Labels are short ("LinkedIn", "GitHub") to keep the
    centered line from wrapping when both profiles are present.

    `field_order` / `separator` come from the active template profile when present;
    otherwise the Google Docs defaults (`_CONTACT_SEP`, location→…→github) apply.
    """
    contact = resume.contact
    order = field_order or [
        "location",
        "email",
        "phone",
        "linkedin",
        "github",
    ]
    sep = _CONTACT_SEP if separator is None else separator

    value_for: dict[str, tuple[str, str | None]] = {
        "location": (contact.location.strip(), None),
        "email": (contact.email.strip(), None),
        "phone": (contact.phone.strip(), None),
        "linkedin": ("LinkedIn", contact.linkedin.strip() or None),
        "github": ("GitHub", contact.github.strip() or None),
    }

    parts: list[tuple[str, str | None]] = []
    for key in order:
        text, url = value_for[key]
        if key in ("linkedin", "github"):
            # Need both a label and a URL; skip when the URL is empty.
            if not url:
                continue
            parts.append((text, url))
        elif text:
            parts.append((text, None))

    rt = RichText()
    for i, (text, url) in enumerate(parts):
        if i:
            rt.add(sep)
        if url:
            _add_hyperlink(rt, text, tpl.build_url_id(url))
        else:
            rt.add(text)
    return rt


def build_context(
    resume: MasterResume,
    tpl: DocxTemplate,
    *,
    bullets: dict[str, str] | None = None,
    include_project_links: bool = True,
    layout: dict | None = None,
    contact_fields: list[ContactField] | None = None,
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

    `layout` is the active template profile summary from `template_profile.active_layout`
    (contact separator/order + enabled sections). When omitted, the active profile on
    disk is loaded, falling back to legacy defaults.

    `contact_fields`, when set, overrides `layout`'s contact field order — see
    `include.contact_order`, which is what callers use to resolve a per-run override
    against the template's own default.
    """
    layout = layout if layout is not None else active_layout()
    enabled = layout.get("enabled") or {
        "education": True,
        "experience": True,
        "projects": True,
        "skills": True,
        "list_section": False,
    }

    def lines(source) -> list[str]:
        if bullets is None:
            return [b.text for b in source]
        return [bullets[b.id] for b in source if b.id in bullets]

    def render_experience(entries) -> list[dict]:
        out = []
        for job in entries:
            rendered = lines(job.bullets)
            if not rendered:
                continue
            out.append(
                {
                    "company": job.company,
                    "location": job.location,
                    "title": job.title,
                    "dates": format_range(job.start, job.end),
                    "bullets": rendered,
                }
            )
        return out

    def render_projects(entries) -> list[dict]:
        out = []
        for proj in entries:
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
                _add_hyperlink(
                    link,
                    proj.link,
                    tpl.build_url_id(proj.url) if proj.url else None,
                )

            out.append(
                {
                    "name": proj.name,
                    "tech": ", ".join(proj.tech),
                    "link": link,
                    "date": proj.date,
                    "bullets": rendered,
                }
            )
        return out

    def render_list_items(entries) -> list[str]:
        # Never filtered by `bullets` — list items are never selected, rewritten, or
        # resized by the fit loop; they render in full, the same as skills/coursework.
        return [item.text for item in entries]

    def render_education(entries) -> list[dict]:
        return [
            {
                "school": edu.school,
                "location": edu.location,
                "dates": edu.dates,
                "degree_line": _degree_line(edu),
                "details": _education_details(edu),
            }
            for edu in entries
        ]

    def render_skills(entries) -> list[dict]:
        # Key is `entries`, never `items`: in Jinja, `group.items` resolves to the dict's
        # built-in method rather than the key, and rendering that method's repr injects
        # invalid markup into the document. Keep context keys clear of dict attribute names.
        return [{"label": g.label, "entries": ", ".join(g.items)} for g in entries]

    _kind_renderers = {
        "experience": render_experience,
        "project": render_projects,
        "list": render_list_items,
        "education": render_education,
        "skills": render_skills,
    }

    # Generic-mode section list — consumed only by a template tagged via
    # `template_build.build_generic`. A section whose kind the active template cannot
    # render (no prototype) is silently omitted here; `fit.py` is what turns that into a
    # warning, since this function has no result channel of its own to carry one.
    sections = []
    for section in resume.sections:
        key = config.SECTION_KIND_ENABLED_KEY[section.kind]
        if not enabled.get(key, config.SECTION_KIND_ENABLED_DEFAULT[section.kind]):
            continue
        rendered_entries = _kind_renderers[section.kind](section.entries)
        if not rendered_entries:
            continue
        sections.append(
            {
                "id": section.id,
                "title": section.title,
                "kind": section.kind,
                "entries": rendered_entries,
            }
        )

    # Legacy flattened keys — what a fixed-mode template consumes. Built from the same
    # renderers as `sections` above so the two can never disagree on what one entry
    # renders as.
    experience = render_experience(resume.experience)
    projects = render_projects(resume.projects) if enabled.get("projects", True) else []
    skills = render_skills(resume.skills) if enabled.get("skills", True) else []
    education = render_education(resume.education) if enabled.get("education", True) else []

    return {
        "name": resume.contact.name,
        "contact": _contact_richtext(
            resume,
            tpl,
            field_order=contact_fields if contact_fields is not None else layout.get(
                "contact_field_order"
            ),
            separator=layout.get("contact_separator"),
        ),
        "education": education,
        "experience": experience,
        "projects": projects,
        "skills": skills,
        "sections": sections,
    }


def render(
    resume: MasterResume,
    *,
    bullets: dict[str, str] | None = None,
    template: Path | None = None,
    out: Path | None = None,
    include_project_links: bool = True,
    contact_fields: list[ContactField] | None = None,
) -> Path:
    """Build the context and render it to a .docx.

    Context building and rendering share one `DocxTemplate` instance deliberately:
    `build_url_id` registers hyperlink relationships on the document, so it must run
    against the same object that is ultimately saved.

    `include_project_links=False` renders projects without their link label, separator,
    or hyperlink.

    `contact_fields`, when set, overrides the active template profile's contact field
    order/inclusion — see `build_context`.
    """
    template = template or config.DEFAULT_TEMPLATE_PATH
    if not template.exists():
        raise FileNotFoundError(
            f"Template not found: {template}\n"
            "Generate it with: python scripts/build_template.py"
        )
    tpl = DocxTemplate(template)
    context = build_context(
        resume,
        tpl,
        bullets=bullets,
        include_project_links=include_project_links,
        contact_fields=contact_fields,
    )

    # autoescape is required, not optional. Without it a literal "&" in the content
    # ("Tools & Languages") is emitted raw into the XML and swallowed as a malformed
    # entity, and RichText hyperlinks render as empty strings. With it, plain strings
    # are escaped and RichText is passed through untouched via its __html__ hook.
    tpl.render(context, autoescape=True)

    out = out or config.OUTPUT_DIR / "tailored.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(out)
    # LibreOffice PDF export needs InternetLink on hyperlink runs + in styles.xml;
    # without this the blue underline survives but clicks do not (Docker / soffice).
    _ensure_pdf_hyperlink_styles(out)
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
