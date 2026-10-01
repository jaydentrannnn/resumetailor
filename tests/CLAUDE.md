# tests/ — conventions

The whole suite runs **without an API key, network, or Word** — keep it that way. Full
detail: `docs/REFERENCE.md` §11.

- **Stub at `llm.client_for`** with **hand-written fake clients**, not a mocking library
  (`_FakeClient` in `test_jd.py`; tests assert recorded `kwargs`; `test_llm.py` goes one
  level lower, `llm.httpx.post`). A stage that can call twice needs a **shared reply
  queue** in its fake — a per-client copy replays the first reply (`rewrite_calls`
  fixture, `test_rewrite.py`).
- **Patch where the name is looked up.** `monkeypatch.setattr(module, "name", ...)` only
  affects callers that resolve `module.name` at call time; after moving code, move the
  patch target with it, or the test silently stops covering anything.
- **`test_tailor_cli.py` autouse-stubs every API stage**; adding an API call to
  `cli.run.main` means extending them. `test_web.py` stubs the same seams on the job path
  (per-test stubs override the `client` fixture defaults).
- **Word/COM is monkeypatched at `fit_mod.render`** (`test_render.py` is the real-docx
  exception). **Assert on the specific warning**, not on warnings being empty —
  `FitResult` carries underflow *and* widow warnings.
- **Hermetic**: `fixtures.py`'s synthetic builders + `synthetic_resume()`, never
  `data.load()`; `conftest.py` autouse fixtures pin calibration, template paths and
  vocabulary packs. Fixture entry headers need real bold/italic/alignment or
  `_split_entries`' fingerprint re-split mis-splits them. Verify:
  `RESUME_TAILOR_DATA_DIR=<empty> RESUME_TAILOR_TEMPLATES_DIR=<empty> pytest`.
- **Real-`master_resume.json` tests are `@pytest.mark.owner`** (excluded by default;
  `pytest -m owner`). Staged template builds fall back in-process when the subprocess
  fails — see `test_web.py::_resume_upload_with_profile`.
- `browser/` holds real-browser tests (opt-in); `fixtures/forms/` holds captured ATS pages.
- Test files: aim for ≤ ~800 lines; split by feature/route when a file grows past that.
