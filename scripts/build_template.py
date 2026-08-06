"""CLI wrapper: generate `templates/main_template.docx` from a baseline export.

All transformation logic lives in `resume_tailor.template_build` so the web install
path and this script share one implementation. This file remains the documented
producer entry point (see CLAUDE.md).

    python scripts/build_template.py
    python scripts/build_template.py --profile templates/template_profile.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor.template_build import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
