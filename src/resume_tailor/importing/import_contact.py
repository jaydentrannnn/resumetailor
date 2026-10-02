"""Importing the contact header from a .docx: inline paragraphs or mapped slots."""

from __future__ import annotations

from ..content.data import (
    Contact,
)
from ..document import (
    analysis_types,
    contact_detect,
    docx_text,
)
from ..document.analysis_types import _Para
from ..document.template_profile import ContactSlot


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

    email_m = analysis_types._EMAIL_RE.search(text)
    email = email_m.group(0) if email_m else ""

    phone = ""
    phone_m = analysis_types._PHONE_RE.search(text)
    if phone_m and not analysis_types._DATE_RE.search(phone_m.group(0)):
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
    # `contact_detect._contact_separator`'s own detection) rather than a bare
    # character class: a plain-text profile URL typed inline, not a real w:hyperlink
    # ("www.linkedin.com/in/…", common when an export loses its hyperlinks), contains
    # bare "/" and "." itself — splitting on those unconditionally shreds the URL into
    # unrelated fragments instead of treating it as one field.
    sep = contact_detect._contact_separator(text) if text.strip() else " • "
    segments = [s.strip() for s in text.split(sep) if s.strip()] if sep in text else (
        [text.strip()] if text.strip() else []
    )

    location = ""
    for seg in segments:
        if not seg or seg in (email, phone) or "@" in seg:
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
        if analysis_types._PHONE_RE.fullmatch(seg.replace(" ", "")):
            continue
        location = seg
        break

    return Contact(
        name=name, email=email, phone=phone, location=location, linkedin=linkedin, github=github
    )

def _import_contact_from_slots(
    name: str, slots: list[ContactSlot], by_id: dict[int, _Para]
) -> Contact:
    """One paragraph per contact field — a table layout's own cells, already
    classified by `contact_detect._detect_name_and_contact` — so each slot's text
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
                m = analysis_types._EMAIL_RE.search(text)
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
    name_id, contact_para, slots, _unmapped = contact_detect._detect_name_and_contact(
        paras, first_heading_id
    )
    by_id = {p.id: p for p in paras}
    name = by_id[name_id].text.strip() if name_id in by_id else ""
    if first_heading_id is not None and not any(
        p.text.strip() and not p.is_bullet for p in paras if p.id < first_heading_id
    ):
        name = ""  # nothing above the first heading: the name is in the page header

    if slots:
        return _import_contact_from_slots(name, slots, by_id)
    return _import_contact_from_paragraph(name, contact_para)
