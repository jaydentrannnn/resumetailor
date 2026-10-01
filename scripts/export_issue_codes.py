"""Write every template-analyzer issue code to frontend/src/lib/templateIssueCodes.json.

The Template page explains each code in plain language (`lib/templateIssues.ts`); a
vitest checks that every code in this file has an explanation, and
`tests/test_issue_codes.py` checks this file matches the analyzer. Re-run after adding
an `Issue(code=...)`:

    python scripts/export_issue_codes.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Modules that create analyzer issues: the analyzer itself and the upload clean-up.
SOURCES = (
    ROOT / "src" / "resume_tailor" / "document" / "template_analyze.py",
    ROOT / "src" / "resume_tailor" / "document" / "docx_normalize.py",
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
