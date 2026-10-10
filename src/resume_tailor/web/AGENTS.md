# web/ — HTTP API + job queue (front door, not a second pipeline)

The SPA, the MCP server (`mcp_server/`, a thin httpx client over this API) and the browser
extension all go through here. Decision log: `docs/notes/web-ui-and-mcp.md` (grep it);
workspaces: `docs/REFERENCE.md` §2.

This file is mirrored byte-for-byte by `AGENTS.md` beside it: edit both together with the
same text (`tests/tooling/test_agent_docs.py` enforces it).

## Rules specific to this package

- **Single process is a hard requirement.** Jobs run one at a time because `config._ACTIVE`
  is process-wide and workspaces rebind `config` module globals.
- **`config._ACTIVE` is populated only by `job_tailor_run.py`'s runner.** A route calling an LLM
  outside a job must use `config.pinned(config.ONE_OFF_PROFILE)` or it hits the claude
  fallback. `style.activate()` sits beside `config.resolve()` in the runner.
- **Mutating workspace routes hold `get_queue().busy()` then `template_ops.LOCK`**, in that
  order.
- **Vocabulary edits never touch resume data**: additions/hides/approvals write the
  app-wide `libraries/vocabulary.json` only. Every master-resume save schedules
  `skill_refresh` (background `tag_infer`, under the saving profile + Tailor routing); a
  reader of the inferred cache must pin that routing too (`skill_refresh.pinned_tailor`).
- Client-side SPA routes rely on `_SPAStaticFiles`' 404 fallback (excludes `/api/*`).
- `security.py` gates every request (Host check, cross-site writes, optional token); the
  extension lane (`/api/extension/*`) authenticates with `X-RT-Extension` instead.

## Module map

- `app.py` — FastAPI app, router inclusion order, static serving.
- `jobs.py` — the bounded job queue (`JobQueue`, `get_queue`); the tailoring run is
  `job_tailor_run.py`, with `job_types`, `job_routing`, `job_outputs`, `job_followups`.
- `template_ops.py` — the Template tab's shared `LOCK`, limits and errors; the ops live in
  `template_info`, `template_library_store`, `template_library`, `template_preview`,
  `template_uploads`, `template_install`, `template_defaults`; `template_migration` (startup
  switch of fixed templates to generic, with backup/revert) and `section_title_sync`
  (template headings → resume section titles).
- `schemas.py` — request/response models (keep in sync with `frontend/src/api/`).
- `routes/` — one router module per area; `routes/run_lookup.py` is the shared run/artifact
  lookup (helpers, no router) used by `jobs` and `applications`. Routers: `jobs`,
  `applications`, `extension`, `resume`,
  `template`, `libraries`, `config`, `workspaces`, `system`, `setup`, `answers`,
  `automation`, `discovery`, `jd`, `onboarding`, `secrets`, `diagnostics`, `update`, `reference`
  (static Profile-page option lists).
- `extension.py` — pairing codes → tokens; `security.py` — request gate; `state.py` —
  process-wide flags shared by the lifespan and routers.

## Tests

`tests/web/test_web_*.py` + `conftest.py`/`helpers.py` (job path stubs the same LLM seams as the CLI; per-test stubs override
the `client` fixture defaults), `test_apply_api.py`, `test_extension*.py`, `test_mcp.py`.

## Template and model request consistency

- `template_state.snapshot()` returns metadata, library badges, starter badges and a preview revision together under `template_ops.LOCK`. The SPA commits this snapshot together.
- Revision previews render under the template lock, then convert their immutable document outside it. Gallery conversions also run outside this lock.
- Ordinary template activation never calibrates automatically. `calibration_cache` restores measurements only when template, profile, resume and PDF backend digests match; otherwise use Tune page fit.
- `infra/model_queue.py` admits each physical model request (including retries), shared across threads, async callers and profiles in this process. Settings are app-wide at `DATA_ROOT/model_queue.json`; `/api/model-queue` exposes limits and status.
