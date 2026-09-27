"""Regression test for dynamically resolved config paths and fit constants.

`set_active_workspace` and run contexts change the values returned by `config.__getattr__`.
Every reader must resolve them through `config.X` at read time. A
`from .config import X` anywhere else would bind a local name to whatever `X` pointed to
at *import* time, permanently decoupled from any later `set_active_workspace` call —
switching workspaces would silently leave that one caller reading the previous (or
default) workspace's path forever, with no error and no obvious symptom until someone
notices a job reading the wrong master resume.

This AST-scans every first-party module for that mistake using the names served by
`config.__getattr__`, so a newly added dynamic view is covered automatically.
"""

from __future__ import annotations

import ast
from pathlib import Path

from resume_tailor import config as config_mod

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_MODULE_NAMES = ("config", "resume_tailor.config")


def _rebound_globals() -> set[str]:
    """Names served dynamically from the current run context."""
    return set(config_mod._PATH_NAMES) | set(config_mod._CALIBRATION_NAMES)


def _first_party_python_files() -> list[Path]:
    """Every module `set_active_workspace`'s contract applies to: the package itself,
    the CLI entrypoint, and the standalone scripts — anywhere that could plausibly read
    a rebindable path constant."""
    files = list((_PROJECT_ROOT / "src").rglob("*.py"))
    files.append(_PROJECT_ROOT / "tailor.py")
    files.extend((_PROJECT_ROOT / "scripts").glob("*.py"))
    return [f for f in files if f.exists()]


def test_rebound_globals_extraction_finds_the_known_set():
    """Sanity check on the dynamic-name set, independent of the real test below — an
    empty or trivially small set would make that test vacuously pass and never catch
    anything."""
    rebound = _rebound_globals()
    assert len(rebound) >= 10
    # A handful of path names confirm the dynamic-name table is in use.
    assert {"DATA_DIR", "OUTPUT_DIR", "MASTER_RESUME_PATH", "TEMPLATE_PROFILE_PATH"} <= rebound


def test_no_module_imports_a_rebound_config_constant_by_name():
    """The actual discipline check: no `from config import <rebound constant>` anywhere
    outside `config.py` itself (which reassigning its own globals is not an import of)."""
    rebound = _rebound_globals()
    config_path = Path(config_mod.__file__).resolve()
    offenders: list[str] = []

    for path in _first_party_python_files():
        if path.resolve() == config_path:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module not in _CONFIG_MODULE_NAMES:
                continue
            for alias in node.names:
                if alias.name in rebound:
                    rel = path.relative_to(_PROJECT_ROOT)
                    offenders.append(f"{rel}:{node.lineno}: from {node.module} import {alias.name}")

    assert not offenders, (
        "Found `from config import <rebound constant>` — this binds a local name at "
        "import time that a later set_active_workspace() call can never reach, so "
        "switching profiles would silently leave that reader on the old workspace's "
        "path. Read the value through config.<NAME> at call time instead:\n"
        + "\n".join(offenders)
    )
