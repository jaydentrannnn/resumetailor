"""Cover-letter layout preview: a sample letter through the live cover template.

Renders the master resume's letterhead with placeholder body text, so the Template page's
cover-letter settings can be seen before any run. No model call — the body is fixed text.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from resume_tailor import config
from resume_tailor.content import data
from resume_tailor.content.data import MasterResume
from resume_tailor.document import (
    cover_settings,
    cover_template,
    render,
    template_profile,
    thumbnails,
)
from resume_tailor.document.cover_settings import CONTACT_FIELDS, CoverSettings
from resume_tailor.pipeline import coverletter_format
from resume_tailor.pipeline.coverletter_models import CoverLetter

from . import template_ops
from .schemas import CoverLetterFieldOut

_SAMPLE_BODY = [
    "This is a preview of your cover letter's layout. When you tailor for a job, these "
    "paragraphs are written from your resume and the posting.",
    "The letterhead, date, recipient, subject line, greeting and sign-off above and below "
    "follow your cover-letter settings.",
]
_FIELD_LABELS = {
    "location": "Location",
    "email": "Email",
    "phone": "Phone",
    "linkedin": "LinkedIn",
    "github": "GitHub",
}


def letterhead_fields(resume: MasterResume | None = None) -> list[CoverLetterFieldOut]:
    """The contact fields and the active template's custom lines, in letterhead order."""
    try:
        resume = resume or data.load()
    except (FileNotFoundError, ValueError):
        resume = None
    contact = resume.contact if resume is not None else None
    values = {f.key: f.value for f in resume.custom_fields} if resume is not None else {}
    out = [
        CoverLetterFieldOut(
            id=name,
            label=_FIELD_LABELS[name],
            has_value=bool(contact and str(getattr(contact, name, "")).strip()),
        )
        for name in CONTACT_FIELDS
    ]
    profile = template_profile.load_profile()
    for slot in profile.custom_fields if profile is not None else []:
        out.append(
            CoverLetterFieldOut(
                id=f"{cover_settings.CUSTOM_PREFIX}{slot.key}",
                label=slot.label or slot.key,
                has_value=bool(values.get(slot.key, slot.text).strip()),
            )
        )
    return out


def _sample_letter(resume: MasterResume) -> CoverLetter:
    return CoverLetter(
        company="Example Company",
        company_location="City, ST",
        paragraphs=list(_SAMPLE_BODY),
        salutation="Dear Hiring Manager,",
        signature=resume.contact.name,
        inside_address=coverletter_format._build_inside_address("Example Company", "City, ST"),
        date=coverletter_format._format_date_long(date.today()),
        job_title="Job Title",
    )


#: Wide enough to read at the drawer's width on a high-density screen.
PREVIEW_WIDTH = 1100


def preview(settings: CoverSettings) -> Path:
    """PNG of the sample letter's page one under `settings` (saved or not) — an image,
    not a PDF frame: Chrome/Edge's single PDF plugin would blank the Template page's own
    preview behind the drawer. Raises
    `FileNotFoundError` with no template or resume, `RuntimeError` with no PDF backend."""
    if not config.BASELINE_TEMPLATE_PATH.exists():
        raise FileNotFoundError("No resume template is installed yet.")
    resume = data.load()
    directory = config.CACHE_DIR / "cover_preview"
    directory.mkdir(parents=True, exist_ok=True)
    with template_ops.LOCK:
        # Built into the cache, not the live cover template: the preview may show a
        # letter design that hasn't been saved yet.
        template = cover_template.ensure_cover_template(
            dst=directory / f"cover_{settings.design}.docx",
            meta_path=directory / f"cover_{settings.design}.meta.json",
            settings=settings,
        )
        digest = hashlib.sha256(settings.model_dump_json().encode())
        for path in (template, config.MASTER_RESUME_PATH, config.TEMPLATE_PROFILE_PATH,
                     config.COVER_OWN_PATH):
            digest.update(path.read_bytes() if path.is_file() else b"missing")
        digest.update(date.today().isoformat().encode())
        key = digest.hexdigest()[:24]
        png_path = directory / f"{key}.png"
        if png_path.exists():
            return png_path
        docx_path, pdf_path = directory / f"{key}.docx", directory / f"{key}.pdf"
        render.render_letter(
            resume, _sample_letter(resume), template=template, out=docx_path, settings=settings
        )
        render.to_pdf(docx_path, pdf_path)
        thumbnails.pdf_first_page_png(pdf_path, png_path, width=PREVIEW_WIDTH)
        docx_path.unlink(missing_ok=True)
        pdf_path.unlink(missing_ok=True)
    return png_path
