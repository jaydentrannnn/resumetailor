"""The Jinja tag strings template building writes, shared with `template_verify`."""

from __future__ import annotations

from docx.oxml.ns import qn

W = qn("w:p")

NOTO_MARKER_FONT = "Noto Sans Symbols"

# --------------------------------------------------------------------------------------
# Jinja tag strings
#
# Hoisted to module constants — not just inlined at each tagging call site — so
# `template_verify.py` can assert a built template actually contains what tagging
# claims to have produced, reading the exact same source rather than a second,
# driftable copy of this list.
# --------------------------------------------------------------------------------------
NAME_TAG = "{{ name }}"

CONTACT_TAG = "{{r contact }}"

#: One RichText per table-layout contact slot — named keys (`contact_slot_0`, …), not
#: a subscript into a list: a subscript past the end of a short list renders as a
#: silent empty string under Jinja's `Undefined`, where a missing named key would at
#: least be a KeyError during development. See `TemplateProfile.contact.slots`.
CONTACT_SLOT_TAG_FMT = "{{r contact_slot_%d }}"

EXPERIENCE_HEADER_TAGS: dict[str, str] = {
    "company": "{{ job.company }}",
    "location": "{{ job.location }}",
    "dates": "{{ job.dates }}",
}

EXPERIENCE_TITLE_TAG = "{{ job.title }}"

#: Shared with `PROJECT_BULLET_TAG` deliberately — each is a different `{%p for bullet
#: in ... %}` loop's own variable, so the identical tag *text* is not evidence of one
#: loop leaking into another; `expected_tags` treats it as presence-only, never an
#: exactly-once count, for this reason.
BULLET_TAG = "{{ bullet }}"

EDUCATION_HEADER_TAGS: dict[str, str] = {
    "school": "{{ edu.school }}",
    "location": "{{ edu.location }}",
    "dates": "{{ edu.dates }}",
}

EDUCATION_DEGREE_TAG = "{{ edu.degree_line }}"

EDUCATION_DETAIL_TAG = "{{ detail }}"

PROJECT_HEADER_TAGS: dict[str, str] = {
    "name": "{{ proj.name }}",
    "tech": "{{ proj.tech }}",
    "date": "{{ proj.date }}",
}

PROJECT_LINK_TAG = "{{r proj.link }}"

PROJECT_BULLET_TAG = BULLET_TAG

SKILLS_LABEL_TAG = "{{ group.label }}"

SKILLS_BODY_TAG = "{{ group.entries }}"

LIST_ITEM_TAG = "{{ item }}"

#: Generic-mode only: the shared heading clone's tag, and the outer per-section loop.
SECTION_TITLE_TAG = "{{ section.title }}"

SECTION_LOOP_OPEN = "{%p for section in sections %}"

#: Table-layout counterpart of `SECTION_LOOP_OPEN` — a ROW-level loop, since a table
#: layout's shared block repeats table rows, not paragraphs. See `build_generic_table`.
SECTION_LOOP_OPEN_TR = "{%tr for section in sections %}"
