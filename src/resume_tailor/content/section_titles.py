"""Copy a template's section heading text into the resume's section titles.

Under a generic-mode template every heading prints `section.title` from the resume, not
the text the template was built from. When a template is installed or converted, its
headings are copied over so the page keeps reading the way the original did; the user
edits titles in the editor afterwards. Pure: no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from .data import MasterResume

if TYPE_CHECKING:
    from ..document.template_profile import DetectedSection


def sync_titles(
    resume: MasterResume, detected_sections: list[DetectedSection]
) -> tuple[MasterResume, list[tuple[str, str]]]:
    """Return a copy of `resume` with section titles taken from `detected_sections` (a
    generic-mode `TemplateProfile.sections`), plus the `(old, new)` title changes made.

    The n-th resume section of a kind is paired with the n-th detected heading of that
    kind. Sections with no partner keep their title; an empty list changes nothing.
    """
    headings: dict[str, list[str]] = defaultdict(list)
    for detected in detected_sections:
        headings[detected.kind].append(detected.title)

    copy = resume.model_copy(deep=True)
    seen: dict[str, int] = defaultdict(int)
    changes: list[tuple[str, str]] = []
    for section in copy.sections:
        index = seen[section.kind]
        seen[section.kind] += 1
        titles = headings.get(section.kind, [])
        if index >= len(titles):
            continue
        new = titles[index]
        if new and new != section.title:
            changes.append((section.title, new))
            section.title = new
    return copy, changes
