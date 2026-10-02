# web/ — HTTP API + job queue (front door, not a second pipeline)

The SPA, the MCP server (`mcp_server/`, a thin httpx client over this API) and the browser
extension all go through here. Decision log: `docs/notes/web-ui-and-mcp.md` (grep it);
workspaces: `docs/REFERENCE.md` §2.

## Rules specific to this package

- **Single process is a hard requirement.** Jobs run one at a time because `config._ACTIVE`
  is process-wide and workspaces rebind `config` module globals.
- **`config._ACTIVE` is populated only by `jobs.py`'s runner.** A route calling an LLM
  outside a job must use `config.pinned(config.ONE_OFF_PROFILE)` or it hits the claude
  fallback. `style.activate()` sits beside `config.resolve()` in the runner.
- **Mutating workspace routes hold `get_queue().busy()` then `template_ops.LOCK`**, in that
  order.
- **Vocabulary-proposal approvals that rewrite an existing bullet tag 409** for explicit
  acknowledgement and back up the master resume first.
- Client-side SPA routes rely on `_SPAStaticFiles`' 404 fallback (excludes `/api/*`).
- `security.py` gates every request (Host check, cross-site writes, optional token); the
  extension lane (`/api/extension/*`) authenticates with `X-RT-Extension` instead.

## Module map

- `app.py` — FastAPI app, router inclusion order, static serving.
- `jobs.py` — the bounded job queue and the tailoring job runner.
- `template_ops.py` — the Template tab's shared `LOCK`, limits and errors; the ops live in
  `template_info`, `template_library_store`, `template_library`, `template_preview`,
  `template_uploads`, `template_install`, `template_defaults`.
- `schemas.py` — request/response models (keep in sync with `frontend/src/api.ts`).
- `routes/` — one router module per area (`jobs`, `applications`, `extension`, `resume`,
  `template`, `libraries`, `config`, `workspaces`, `system`, `setup`, ...).
- `extension.py` — pairing codes → tokens; `security.py` — request gate.

## Tests

`tests/web/test_web_*.py` + `conftest.py`/`helpers.py` (job path stubs the same LLM seams as the CLI; per-test stubs override
the `client` fixture defaults), `test_apply_api.py`, `test_extension*.py`, `test_mcp.py`.
