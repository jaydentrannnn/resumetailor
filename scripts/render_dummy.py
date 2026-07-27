"""Template smoke test: render the full master resume, unmodified, and measure it.

This is the Phase 1 acceptance check. It exercises the parts of the template most likely
to break — variable numbers of entries and bullets, per-project hyperlinks, the tab-
aligned date column — and reports the page count so the calibration constants in
`config.py` can be sanity-checked against reality.

    python scripts/render_dummy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor import config, data, render  # noqa: E402


def main() -> int:
    resume = data.load()
    out = config.OUTPUT_DIR / "_smoke.docx"

    render.render(resume, out=out)
    print(f"rendered {out.name}")
    print(
        f"  {len(resume.experience)} experience entries, "
        f"{len(resume.projects)} projects, "
        f"{len(resume.all_bullets())} bullets"
    )

    try:
        pages = render.measure(out)
    except RuntimeError as exc:
        print(f"  PDF conversion unavailable: {exc}")
        return 0

    print(f"  renders to {pages} page(s)")
    print(
        "\nNote: this renders the FULL master superset, so more than one page is "
        "expected here.\nThe tailored output is what gets fitted to "
        f"{config.DEFAULT_PAGE_TARGET} page(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
