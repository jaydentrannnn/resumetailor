"""Tag `TemplateProfile.custom_fields` / remove `dropped_paragraph_ids`.

Two passes, because paragraph ids are positions: `tag` runs first, alongside name and
contact tagging and before any section work, and only rewrites runs in place (no
paragraph is inserted or removed, so every later id still resolves). `finish` runs last,
once every id has been resolved: it inserts the `{%p if %}` wrappers and deletes dropped
lines through the `Paragraph` objects `tag` captured, never through ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docx.text.paragraph import Paragraph

from . import template_tagging, template_tags, template_xml
from .template_profile import TemplateProfile


@dataclass
class Pending:
    """Paragraphs `tag` resolved, kept for `finish`."""

    wrap: list[tuple[str, Paragraph]] = field(default_factory=list)
    drop: list[Paragraph] = field(default_factory=list)


def tag(doc, profile: TemplateProfile) -> Pending:
    """Collapse each custom line to its tag; resolve dropped lines. No structural edits."""
    pending = Pending()
    for slot in profile.custom_fields:
        paragraph = template_tagging._para_by_id(doc, slot.paragraph_id)
        template_xml.strip_hyperlinks(paragraph)
        expr = template_tags.CUSTOM_FIELD_TAG_FMT % slot.key
        runs = paragraph.runs
        if runs:
            template_xml.collapse_runs(runs, expr)
        else:
            paragraph.add_run(expr)
        if not _in_table_cell(paragraph):
            pending.wrap.append((slot.key, paragraph))
    pending.drop = [
        template_tagging._para_by_id(doc, pid) for pid in profile.dropped_paragraph_ids
    ]
    return pending


def finish(pending: Pending) -> None:
    """Wrap body-level custom lines in `{%p if %}`; remove dropped lines."""
    for key, paragraph in pending.wrap:
        paragraph._p.addprevious(template_xml.make_para(template_tags.CUSTOM_FIELD_IF_FMT % key))
        paragraph._p.addnext(template_xml.make_para(template_tags.CUSTOM_FIELD_ENDIF))
    for paragraph in pending.drop:
        if paragraph._p.getparent() is None:
            continue  # already removed with a section's victims
        if _in_table_cell(paragraph) and _only_paragraph_in_cell(paragraph):
            for run in paragraph.runs:  # a cell must keep one paragraph: empty it instead
                template_xml.set_run_text(run, "")
        else:
            template_xml.delete(paragraph)


def _in_table_cell(paragraph: Paragraph) -> bool:
    return paragraph._p.getparent().tag.endswith("}tc")


def _only_paragraph_in_cell(paragraph: Paragraph) -> bool:
    cell = paragraph._p.getparent()
    return sum(1 for child in cell if child.tag.endswith("}p")) == 1
