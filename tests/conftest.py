"""Shared fixtures across the test suite.

`_no_workspace_bootstrap` exists because `web/app.py`'s FastAPI lifespan calls
`workspace.bootstrap()` on startup, and `TestClient(app)` used as a context manager
(the pattern every test in `test_web.py` uses) runs that lifespan. Without this stub,
`bootstrap()` would fire after each test's own `monkeypatch.setattr(config, ...)`
calls and clobber them — and on a developer's machine, with no other path
monkeypatched yet, it would migrate the real `data/` and `templates/` trees the very
first time any test imports `web.app`. Every existing test monkeypatches `config`'s
path globals directly and expects them to stick, which only holds as long as
`set_active_workspace` (bootstrap's only way of changing them) is never actually
called during collection or a bare test run.

`_isolated_libraries` exists for the same class of reason. `libraries.store_root()`
resolves under `config.DATA_ROOT`, which most tests never monkeypatch — without the
redirect, a bare test run on a developer machine would read *that developer's own*
approved packs and make `test_config.py::test_alias_hit` fail for a reason invisible
in the diff. It also resets `config.TAG_ALIASES` / `config.VERB_FAMILIES` (rebindable
module globals that `libraries` can reassign) so no test leaks its own library state
into the next one.

`_pinned_calibration` is the same reasoning again, applied to fit constants: without
it, a test asserting on rendered/estimated line counts would pass or fail depending on
whether *this* machine's `data/calibration/<backend>.json` happens to exist and what it
measured — invisible in the diff, and the exact failure mode a real corrupted
calibration file (`chars_per_line: 20`, see `docs/notes/fit-and-calibration.md`) produced before
anyone noticed. Pinned to the built-in fallback pair specifically, so the numbers a
test sees match what a fresh checkout with no calibration file at all would compute.

`built_template` (below) exists so tests needing a real, renderable tagged template
never depend on `config.DEFAULT_TEMPLATE_PATH` — a developer's own upload, which may
not exist at all on a clean checkout or in CI, and previously forced several tests in
`tests/test_render.py` into a conditional `pytest.skip`. `tests/fixtures.py` holds the
synthetic DOCX/`MasterResume` builders this fixture and the tests that use it share.

`_isolated_template_paths` closes a gap the same shape as `_isolated_libraries`, found
while building `built_template`: `render.build_context`/`template_profile.active_layout`
read `config.TEMPLATE_PROFILE_PATH` from disk whenever a caller does not pass an
explicit `layout=`, and on a developer machine that path is real — on this one, a stale
pre-workspace `templates/template_profile.json` with `enabled.projects: False`, which
made a synthetic project fixture render as empty for a reason invisible in the diff.
`DEFAULT_TEMPLATE_PATH`/`BASELINE_TEMPLATE_PATH` are redirected alongside it for the
same reason, even though every test migrated in this pass passes `template=` (or
`built_template`) explicitly: the failure mode this fixture prevents is a *future* test
that forgets to, silently reading whatever a developer's own `templates/` happens to
hold instead of failing closed.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

# Before any `resume_tailor` import: `config.OUTPUT_ROOT`/`CACHE_ROOT` are resolved at
# import time. A job/operation worker thread that outlives its test runs after that
# test's `monkeypatch` of `config.OUTPUT_DIR` is undone, and would otherwise write into
# the checkout's real `output/`. Overridden, not setdefault: a developer's own
# RESUME_TAILOR_OUTPUT_DIR must never receive test artifacts either.
_TEST_OUTPUT_ROOT = tempfile.mkdtemp(prefix="rt-test-output-")
atexit.register(shutil.rmtree, _TEST_OUTPUT_ROOT, ignore_errors=True)
os.environ["RESUME_TAILOR_OUTPUT_DIR"] = _TEST_OUTPUT_ROOT
os.environ.pop("RESUME_TAILOR_CACHE_DIR", None)
# The app log is on by default; the suite must never write one either.
os.environ.setdefault("RESUME_TAILOR_LOG_DIR", "off")
# Never the developer's keychain or data/secrets.enc: an in-memory store per test.
os.environ["RESUME_TAILOR_SECRETS_BACKEND"] = "memory"
# TestClient sends `Host: testserver` (the MCP tests `test`); the session token is off unless a test sets it.
os.environ["RESUME_TAILOR_ALLOWED_HOSTS"] = "testserver,test"
os.environ.pop("RESUME_TAILOR_TOKEN", None)

import pytest  # noqa: E402

from resume_tailor import (  # noqa: E402
    config,
    libraries,
    secret_store,
    style,
    template_analyze,
    template_build,
    workspace,
)
from resume_tailor.apply.forms import form_guards, submit_guard  # noqa: E402
from resume_tailor.web import extension as web_extension  # noqa: E402
from tests.fixtures import _docx_bytes, _full_featured_resume  # noqa: E402


@pytest.fixture(autouse=True)
def _no_workspace_bootstrap(monkeypatch):
    monkeypatch.setattr(workspace, "bootstrap", lambda **kwargs: None)


@pytest.fixture(autouse=True)
def _isolated_libraries(tmp_path, monkeypatch):
    """Redirect every store `libraries.py` reads from, and reset the resolved tables.

    `store_root()` (the central pack store) is monkeypatched directly rather than via
    `config.DATA_ROOT`, since that is how `libraries.py` itself resolves it.
    `config.LIBRARIES_PATH` is redirected the same way every other test monkeypatches
    `config.SETTINGS_PATH` / `config.MASTER_RESUME_PATH` — a dedicated global, not
    derived from `DATA_DIR`, so this cannot affect tests that rely on the real master
    resume at its own separately-set path.
    """
    monkeypatch.setattr(libraries, "store_root", lambda: tmp_path / "libraries")
    paths = {
        **config._DEFAULT.paths,
        "LIBRARIES_PATH": tmp_path / "workspace_data" / "libraries.json",
        "SETTINGS_PATH": tmp_path / "workspace_data" / "settings.json",
    }
    monkeypatch.setattr(config, "_DEFAULT", replace(config._DEFAULT, paths=paths, guidance=None))
    libraries.reset()
    yield
    libraries.reset()


@pytest.fixture(autouse=True)
def _fresh_secret_store():
    """A new, empty in-memory secret store for every test."""
    secret_store.reset_backend()
    yield
    secret_store.reset_backend()


@pytest.fixture(autouse=True)
def _reset_style():
    """Clear per-run style overrides so one test cannot leak into the next."""
    style.activate(rewrite=None, expand=None)
    yield
    style.activate(rewrite=None, expand=None)


@pytest.fixture(autouse=True)
def _pinned_calibration(monkeypatch):
    """Pin fit-constant globals to the built-in fallback pair for every test."""
    calibration = (config._FALLBACK_CHARS_PER_LINE, config._FALLBACK_LINES_PER_PAGE, "fallback", None)
    monkeypatch.setattr(config, "_DEFAULT", replace(config._DEFAULT, calibration=calibration))


@pytest.fixture(autouse=True)
def _isolated_apply_paths(tmp_path, monkeypatch):
    """Redirect apply-funnel paths so tests never touch a developer's applications.json
    or the per-source run status a daily run records."""
    apply_dir = tmp_path / "apply_workspace"
    apply_dir.mkdir(exist_ok=True)
    paths = {**config._DEFAULT.paths,
             "APPLICATIONS_PATH": apply_dir / "applications.json",
             "APPLICANT_PROFILE_PATH": apply_dir / "applicant_profile.json",
             "APPLICATIONS_OUTPUT_DIR": apply_dir / "applications_out",
             "SOURCE_STATUS_PATH": apply_dir / "source_status.json"}
    monkeypatch.setattr(config, "_DEFAULT", replace(config._DEFAULT, paths=paths))


@pytest.fixture(autouse=True)
def _isolated_resolver_choices(tmp_path, monkeypatch):
    """Per-test store of the resolver's remembered choices: one test's model answer must
    not be replayed into another (`CACHE_DIR` is shared by the whole session)."""
    from resume_tailor.apply.answers import hybrid_resolver

    monkeypatch.setattr(hybrid_resolver, "_choices_path", lambda: tmp_path / "resolver-choices.json")


@pytest.fixture(autouse=True)
def _isolated_submit_guard(tmp_path, monkeypatch):
    """Keep the pause switch, blocked hosts and extension pairings per test; never sleep."""
    monkeypatch.setattr(submit_guard, "pause_path", lambda: tmp_path / "automation.json")
    monkeypatch.setattr(submit_guard, "_sleep", lambda _seconds: None)
    submit_guard.reset()
    form_guards.reset_hosts()
    monkeypatch.setattr(web_extension, "store_path", lambda: tmp_path / "extensions.json")
    web_extension.reset()
    yield
    submit_guard.reset()
    form_guards.reset_hosts()
    web_extension.reset()


@pytest.fixture(autouse=True)
def _isolated_template_paths(tmp_path, monkeypatch):
    """Redirect the template path globals to nonexistent temp paths by default.

    A test that genuinely needs a specific value still monkeypatches these itself
    (`test_web.py`/`test_workspace.py` already do) — those patches win, since they run
    after this one.
    """
    paths = {**config._DEFAULT.paths,
             "TEMPLATE_PROFILE_PATH": tmp_path / "no-such-profile.json",
             "DEFAULT_TEMPLATE_PATH": tmp_path / "no-such-template.docx",
             "BASELINE_TEMPLATE_PATH": tmp_path / "no-such-baseline.docx",
             "COVER_TEMPLATE_PATH": tmp_path / "no-such-cover-template.docx",
             "COVER_TEMPLATE_META_PATH": tmp_path / "no-such-cover-meta.json"}
    monkeypatch.setattr(config, "_DEFAULT", replace(config._DEFAULT, paths=paths))


@pytest.fixture(scope="session")
def built_template(tmp_path_factory) -> Path:
    """Build the tagged template from `tests.fixtures._full_featured_resume` once for
    the whole session. `analyze_docx`/`build_from_profile` are pure functions of their
    explicit path/bytes arguments — neither touches `config`'s path globals — so the
    result is safe to reuse across every test rather than rebuilding it per test.
    """
    tmp_dir = tmp_path_factory.mktemp("built_template")
    src = tmp_dir / "original_export.docx"
    src.write_bytes(_docx_bytes(_full_featured_resume))
    result = template_analyze.analyze_docx(raw=src.read_bytes())
    assert result.ready, f"synthetic fixture failed to analyze cleanly: {result.issues}"
    dst = tmp_dir / "main_template.docx"
    template_build.build_from_profile(src, dst, result.suggested_profile)
    return dst


@pytest.fixture(autouse=True)
def _pinned_recency_today(monkeypatch):
    """Pin "today" for `rewrite.entry_recency` so rankings never drift with the calendar."""
    monkeypatch.setattr(config, "RECENCY_TODAY", "2026-09")
