"""Generate a tagged `main_template.docx` from a baseline export.

This module is the ONLY producer of the tagged template (see CLAUDE.md); its `template_*`
siblings (`template_xml`, `template_tagging`, `template_generic`, ...) are helpers it
calls, never entry points. The CLI `scripts/build_template.py` is a thin wrapper.

Two modes:
- **Legacy** (no profile): exact all-caps headings and the original Google Docs layout.
- **Profile** (confirmed mapping): tags only mapped character spans so separators and
  tabs from the upload survive; optional sections may be omitted.
"""

from __future__ import annotations

from pathlib import Path

import docx

from .. import config
from . import (
    docx_text,
    template_bullets,
    template_generic,
    template_generic_table,
    template_profile_build,
    template_tagging,
    template_xml,
)
from .template_profile import TemplateProfile


def build_from_profile(
    src: Path,
    dst: Path,
    profile: TemplateProfile,
) -> None:
    """Tag `src` using `profile` and write the result to `dst`."""
    doc = docx.Document(str(src))

    if profile.paragraph_count is not None:
        actual = sum(1 for _ in docx_text.iter_document_paragraphs(doc))
        if actual != profile.paragraph_count:
            raise RuntimeError(
                f"Baseline paragraph count changed since analysis ({profile.paragraph_count} "
                f"-> {actual}); every mapped paragraph id would resolve to the wrong "
                "paragraph. Re-analyze the upload."
            )

    if profile.layout == "table":
        template_generic_table.build_generic_table(doc, profile)
    elif profile.section_mode == "generic":
        template_generic.build_generic(doc, profile)
    else:
        noto_num_id = None
        if profile.normalization.normalize_bullet_font:
            noto_num_id = template_bullets.discover_noto_num_id(doc)

        template_profile_build.build_name_profile(doc, profile)
        template_profile_build.build_contact_profile(doc, profile)

        # Build sections bottom-up (later headings first) so earlier paragraph indices
        # stay valid for still-pending sections. Deletion of a later section does not
        # shift earlier heading ids.
        builders: list[tuple[int, object]] = []
        if profile.enabled.experience and profile.experience is not None:
            builders.append((profile.experience.heading_paragraph_id, "experience"))
        if profile.enabled.education and profile.education is not None:
            builders.append((profile.education.heading_paragraph_id, "education"))
        if profile.enabled.projects and profile.projects is not None:
            builders.append((profile.projects.heading_paragraph_id, "projects"))
        if profile.enabled.skills and profile.skills is not None:
            builders.append((profile.skills.heading_paragraph_id, "skills"))
        builders.sort(key=lambda t: t[0], reverse=True)

        # Resolve every enabled kind's heading paragraph *object* once, before any
        # section's body is touched. `_section_body_paragraphs` then stops on object
        # identity rather than re-deriving indices (which insertions elsewhere would
        # go on to shift) or matching heading text (which an ordinary entry line could
        # coincidentally equal) — see its own docstring.
        heading_paragraphs = {
            hid: template_tagging._para_by_id(doc, hid) for hid, _kind in builders
        }

        for hid, kind in builders:
            other_headings = [p for h, p in heading_paragraphs.items() if h != hid]
            if kind == "experience":
                template_profile_build.build_experience_profile(
                    doc, profile, noto_num_id=noto_num_id, other_headings=other_headings
                )
            elif kind == "education":
                template_profile_build.build_education_profile(
                    doc, profile, noto_num_id=noto_num_id, other_headings=other_headings
                )
            elif kind == "projects":
                template_profile_build.build_projects_profile(
                    doc, profile, noto_num_id=noto_num_id, other_headings=other_headings
                )
            elif kind == "skills":
                template_profile_build.build_skills_profile(
                    doc, profile, other_headings=other_headings
                )

    if profile.normalization.normalize_bullet_font:
        template_bullets.normalize_bullet_numbering(doc)
    if profile.normalization.force_single_spacing:
        template_xml.normalize_single_spacing(doc)
    template_xml.clamp_tab_stops(doc)

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))


# --------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------


def build(
    src: Path | None = None,
    dst: Path | None = None,
    profile: TemplateProfile | None = None,
    profile_path: Path | None = None,
    verify: bool = True,
) -> int:
    """Build a tagged template from `profile`, or a readable profile file on disk.

    `verify` (default True) runs `template_verify.verify_tagged`/`verify_roundtrip`
    against the freshly-built template — the same check `web/template_ops.py`'s staged
    install runs before committing, exposed here so a CLI/scripted rebuild gets the
    same guarantee. Unlike the web install, this write is not staged/atomic — a
    verification failure is reported with a non-zero exit code, but the just-written
    `dst` is not rolled back; re-run after fixing the mapping.
    """
    from .template_profile import load_profile

    src = src or config.BASELINE_TEMPLATE_PATH
    dst = dst or config.DEFAULT_TEMPLATE_PATH
    if profile is None and profile_path is not None:
        profile = load_profile(profile_path)
    if profile is None:
        profile = load_profile()

    if profile is None:
        print(
            "ERROR: no template profile found (and none was passed in).\n"
            "Run the Template tab's analyze/confirm wizard, or pass --profile to "
            "point at a template_profile.json."
        )
        return 1

    try:
        build_from_profile(src, dst, profile)
    except Exception as exc:
        print(f"ERROR: profile build failed: {exc}")
        return 1

    if verify:
        from ..content import data
        from . import template_verify

        issues = template_verify.verify_tagged(dst, profile)
        try:
            resume = data.load()
        except (FileNotFoundError, ValueError) as exc:
            print(f"WARNING: could not load master resume to verify roundtrip: {exc}")
        else:
            issues += template_verify.verify_roundtrip(dst, profile, resume)
        blockers = [i for i in issues if i.blocking]
        if blockers:
            print(f"ERROR: build verification failed for {dst}:")
            for issue in blockers:
                print(f"  {issue.code}: {issue.message}")
            return 1

    print(
        f"wrote {dst} (profile v{profile.schema_version}; "
        "sections: "
        + "+".join(
            name
            for name, on in (
                ("experience", profile.enabled.experience),
                ("education", profile.enabled.education),
                ("projects", profile.enabled.projects),
                ("skills", profile.enabled.skills),
            )
            if on
        )
        + ")"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry: optional ``--from``, ``--profile``, ``--out``, ``--workspace``."""
    import argparse
    import sys

    from .. import workspace

    parser = argparse.ArgumentParser(description="Build main_template.docx from a baseline export.")
    parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=None,
        help="Baseline DOCX (default: templates/original_export.docx).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Tagged output path (default: templates/main_template.docx).",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Template profile JSON (default: templates/template_profile.json if present).",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="ID",
        help="Build against this profile instead of the active one (this invocation only).",
    )
    parser.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help=(
            "Skip post-build verification (tag presence + a real render's field "
            "values) that runs by default for a profile-based build."
        ),
    )
    args = parser.parse_args(argv)
    try:
        workspace.bootstrap(workspace_id=args.workspace)
    except workspace.WorkspaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return build(args.source, args.out, profile_path=args.profile, verify=args.verify)


if __name__ == "__main__":
    raise SystemExit(main())
