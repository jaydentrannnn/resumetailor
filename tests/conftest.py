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
"""

from __future__ import annotations

import pytest

from resume_tailor import workspace


@pytest.fixture(autouse=True)
def _no_workspace_bootstrap(monkeypatch):
    monkeypatch.setattr(workspace, "bootstrap", lambda **kwargs: None)
