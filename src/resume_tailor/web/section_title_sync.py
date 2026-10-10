"""Copy the live template's section headings into the active master resume's titles.

Under a generic-mode template each heading prints the resume's `section.title`, so
installing (or converting) a template copies its heading text over — the page keeps
reading the way the uploaded document did. The write goes through the versioned master
resume writer, so it can be undone from the resume history.
"""

from __future__ import annotations

import logging

from resume_tailor import config
from resume_tailor.content import data, section_titles
from resume_tailor.document import template_profile
from resume_tailor.document.template_profile import TemplateProfile
from resume_tailor.web import template_ops

_log = logging.getLogger(__name__)

#: Version-history note for a title sync.
NOTE = "Section titles from template"
#: Marker in a workspace's templates dir: its live template was converted while another
#: workspace was active, so its resume titles are synced on its next activation.
PENDING_MARKER = "title_sync_pending"


def sync_active(profile: TemplateProfile) -> list[tuple[str, str]]:
    """`sync_unlocked` under `template_ops.LOCK`."""
    with template_ops.LOCK:
        return sync_unlocked(profile)


def sync_unlocked(profile: TemplateProfile) -> list[tuple[str, str]]:
    """Rename the active workspace's resume sections to `profile`'s headings, returning
    the `(old, new)` changes. The caller holds `template_ops.LOCK`. A fixed-mode profile,
    a missing resume, or a resume that already matches writes nothing. Never raises: a
    failed sync leaves titles as they were and is logged, never failing whatever install
    or conversion triggered it."""
    if profile.section_mode != "generic" or not profile.sections:
        return []
    # Imported lazily: the route module owns the master-resume write path.
    from resume_tailor.web.routes import resume as resume_routes

    try:
        resume = data.load()
        synced, changes = section_titles.sync_titles(resume, profile.sections)
        if changes:
            resume_routes._write_master_resume(synced, note=NOTE)
        return changes
    except FileNotFoundError:
        return []
    except Exception:  # noqa: BLE001 - titles are a convenience; the template stands
        _log.warning("could not sync section titles from the template", exc_info=True)
        return []


def apply_pending_unlocked() -> list[tuple[str, str]]:
    """Run a sync deferred to this (now active) workspace's activation, if one is
    pending. The caller holds `template_ops.LOCK`."""
    marker = config.TEMPLATE_PROFILE_PATH.parent / PENDING_MARKER
    if not marker.exists():
        return []
    profile = template_profile.load_profile()
    changes = sync_unlocked(profile) if profile is not None else []
    marker.unlink(missing_ok=True)
    return changes
