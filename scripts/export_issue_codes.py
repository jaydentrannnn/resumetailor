"""Write every template-analyzer issue code to frontend/src/lib/templateIssueCodes.json.

The Template page explains each code in plain language (`lib/templateIssues.ts`); a
vitest checks that every code in this file has an explanation, and
`tests/document/test_issue_codes.py` checks this file matches the analyzer. Re-run after adding
an `Issue(code=...)`:

    python scripts/export_issue_codes.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Modules that create analyzer issues: the analyzer (`template_analyze` and the modules
#: split out of it) and the upload clean-up. Add a module here when it starts creating
#: `Issue`s, or its codes go unexplained on the Template page.
_DOCUMENT = ROOT / "src" / "resume_tailor" / "document"
SOURCES = tuple(
    _DOCUMENT / f"{name}.py"
    for name in (
        "template_analyze",
        "analysis_types",
        "table_layout",
        "entry_structure",
        "contact_detect",
        "header_fields",
        "field_candidates",
        "profile_validation",
        "section_mapping",
        "docx_normalize",
    )
)
OUT = ROOT / "frontend" / "src" / "lib" / "templateIssueCodes.json"

#: Expansions of the f-string codes (`code=f"omit_{key}"`).
_TEMPLATED = {"omit_": ("education", "projects", "skills")}


def issue_codes(source: str | None = None) -> list[str]:
    text = (
        source
        if source is not None
        else "\n".join(path.read_text(encoding="utf-8") for path in SOURCES)
    )
    codes = set(re.findall(r'code="([a-z_]+)"', text))
    for prefix in re.findall(r'code=f"([a-z_]+)\{', text):
        codes.update(prefix + key for key in _TEMPLATED.get(prefix, ()))
    return sorted(codes)


def main() -> None:
    OUT.write_text(json.dumps(issue_codes(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
