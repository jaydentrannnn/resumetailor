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
"""

from __future__ import annotations

import pytest

from resume_tailor import config, libraries, workspace


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
    monkeypatch.setattr(config, "LIBRARIES_PATH", tmp_path / "workspace_data" / "libraries.json")
    libraries.reset()
    yield
    libraries.reset()
