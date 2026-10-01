"""The Template page's issue explanations cover every analyzer code (TP2)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location(
        "export_issue_codes", ROOT / "scripts" / "export_issue_codes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exported_codes_match_the_analyzer():
    script = _script()
    committed = json.loads(script.OUT.read_text(encoding="utf-8"))
    assert committed == script.issue_codes(), (
        "template_analyze.py issue codes changed: run `python scripts/export_issue_codes.py` "
        "and add an explanation in frontend/src/lib/templateIssues.ts"
    )


def test_templated_codes_expand():
    codes = _script().issue_codes('Issue(code="a_b")\nIssue(code=f"omit_{key}")')
    assert codes == ["a_b", "omit_education", "omit_projects", "omit_skills"]
