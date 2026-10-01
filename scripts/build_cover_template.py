"""CLI wrapper: generate ``templates/cover_template.docx`` from the baseline export.

    python scripts/build_cover_template.py
    python scripts/build_cover_template.py --workspace <id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor import config, workspace  # noqa: E402
from resume_tailor.document.cover_template import ensure_cover_template  # noqa: E402
from resume_tailor.document.template_profile import load_profile  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Build the active workspace's cover-letter template."""
    parser = argparse.ArgumentParser(description="Build cover_template.docx from baseline export")
    parser.add_argument(
        "--workspace",
        help="Workspace id override (does not change the active profile registry)",
    )
    parser.add_argument(
        "--src",
        type=Path,
        help="Baseline export path (default: active workspace BASELINE_TEMPLATE_PATH)",
    )
    parser.add_argument(
        "--dst",
        type=Path,
        help="Output path (default: active workspace COVER_TEMPLATE_PATH)",
    )
    args = parser.parse_args(argv)

    workspace.bootstrap()
    if args.workspace:
        config.set_active_workspace(args.workspace)

    src = args.src or config.BASELINE_TEMPLATE_PATH
    dst = args.dst or config.COVER_TEMPLATE_PATH
    if not src.exists():
        print(f"error: baseline not found at {src}", file=sys.stderr)
        return 1

    profile = load_profile()
    ensure_cover_template(src=src, dst=dst, profile=profile)
    print(f"Wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
