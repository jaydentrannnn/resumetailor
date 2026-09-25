# Web UI, API & MCP — implementation notes

Covers: SPA pages, job runner, Docker, downloads, settings, run history, theme, MCP server.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-07-26 ? Web UI serialises jobs; does not refactor `_ACTIVE`

**What:** The FastAPI job queue runs one tailoring job at a time. Concurrent submissions
queue and the UI shows position.

**Why:** `config._ACTIVE` is process-wide mutable routing state. Threading a context
object through every call site would be a large, risky diff for a single-user tool.

**Tradeoff:** No parallel runs. Documented follow-up if this becomes multi-user:
`contextvars` (or an explicit backend bag) instead of `_ACTIVE`.

**Also:** each job writes to `output/jobs/<job_id>/`; JD/score caches go to
`RESUME_TAILOR_CACHE_DIR` (default `output/`, Docker sets `output/cache`).

## 2026-07-26 ? Docker one-shot

**What:** Multi-stage `Dockerfile` + `docker-compose.yml`. Node builds the SPA; runtime
is `python:3.13-slim` + `libreoffice-writer` + vendored fonts. `docker compose up --build`
serves http://localhost:8000.

**Why:** Word/COM cannot run in Linux; LibreOffice is the measurement engine in the
container (`RESUME_TAILOR_PDF_BACKEND=soffice`). Native Windows CLI still defaults to
`word`.

**Impact:** Image ~1 GB. `data/` and `templates/` are bind-mounted (gitignored). Ollama
on the host is reached via `host.docker.internal`.

**Verified:** 13-bullet current-resume subset renders to 1 page / 49 lines inside the
container with the soffice calibration loaded.

## 2026-07-26 ? Master resume editor: add / remove / reorder

**What:** The SPA master-resume editor can add, remove, and reorder experience entries,
project entries, skill groups, and bullets. New bullets get client-generated ids; new
projects get `proj_<slug>` ids. Per-project GitHub URL + link label fields are editable
(schema already had `Project.link` / `Project.url`).

**Why:** The editor previously only mutated fields on fixed-length arrays. Growing the
store required hand-editing JSON. Experience keys used `${company}-${i}` and skill keys
used `g.label`, which remounted cards on every keystroke ? switched to index keys
because all state is controlled from the parent `resume` object.

**Bullet ids:** Reuse the entry's existing `_bN` prefix (e.g. `aol_b4`) rather than
slugifying the company name. Prefixes in `master_resume.json` are hand abbreviations and
are not name-derivable. Ids stay read-only in the UI; uniqueness is still enforced
server-side by `MasterResume._ids_unique`.

**GitHub links:** Typing a URL into an empty label auto-fills `"Github"`. A label with
no URL warns inline (already true for `proj_zotassistant` / `proj_fuzzy_street`).
Non-http URLs warn but do not block save ? matching the plain `str` schema.

**Impact:** Client completeness check blocks Save/Validate on blank bullet text/tags and
blank entry headers before the Pydantic path; server validation remains authoritative.

## 2026-07-27 ? Export filename = name + position

**What:** Downloads and CLI default output now use `<contact.name> Resume - <JD title>.docx` via `report.export_filename`. Web job dirs still store `tailored.docx` internally; only the `Content-Disposition` filename (and CLI `--out` default) changed.

**Why:** Owner wants application-ready names like `Alex Jordan Doe Resume - Software Engineer Intern`.

**Impact:** Characters illegal on Windows (`<>:"/\|?*`) are replaced with spaces in the stem. Restart the API / Docker container to pick up the download-name change.

## 2026-07-27 ? Tailor UI: full-width accordion, shared model list, tab persistence

**What:** (1) Application experience tile moved below the two-column grid at full container width; entries are an accordion (first open). (2) Rewrite/Expand model fields share one `localStorage`-backed list (`resumeTailor.modelSpecs`) via `useSyncExternalStore`. (3) `RunProvider` / `EditorProvider` sit above the router so JD text, settings, SSE, and editor drafts survive tab switches; JD + settings also survive reload.

**Why:** Narrow stacked entries made the page long; free-text model fields forced retyping; React Router unmounted pages and killed mid-run EventSource.

**Tradeoff:** Editor draft is memory-only across reloads (avoids shadowing disk). Persisted settings merge over `DEFAULT_SETTINGS` so older blobs missing newer fields stay valid.

**Impact:** Rebuild SPA (`npm run build` or `docker compose up --build`) to pick up the UI.

## 2026-08-01 ? PDF download button + auto-download on success

- **Decision:** Added `/api/jobs/{id}/download.pdf` (attachment) beside the existing
  inline `preview.pdf`; UI gets a `.pdf` button and one auto-download per succeeded
  `jobId` via blob fetch (`triggerPdfDownload`).
- **Why:** Jul 28 frontend drop of the preview iframe (plus inline disposition) removed
  the accidental auto-download; user wants both a manual PDF control and the old
  save-on-finish behavior without reintroducing iframe remount downloads.
- **Tradeoff:** Auto-download is silent if LibreOffice never produced a PDF (404).
  SPA is baked in Docker ? rebuild required for the UI half.
- **Follow-up:** Guard must live in `RunProvider`, not `RunPage` (see next entry).

## 2026-08-01 ? Auto-download guard moved to RunProvider

- **Decision:** Moved the `autoDownloadedFor` ref + `triggerPdfDownload` effect from
  `RunPage` into `RunProvider`.
- **Why:** Routes unmount `RunPage` on Tailor ? Master switches, so a page-local ref
  reset to `null` and re-fired the download whenever you came back to a succeeded job.
  Provider sits above the router and survives those remounts.
- **Tradeoff:** None ? same one-download-per-jobId semantics; just the correct lifetime.
- **Impact:** Rebuild Docker (or `npm run build`) for the SPA.

## 2026-08-01 ? Comma-list fields keep a draft while focused

- **Decision:** Replaced join/split-on-every-keystroke for skills items, project tech,
  and bullet tags with `CommaListField` (local draft + `parseCommaList` on change/blur).
- **Why:** `value={items.join(", ")}` plus `.split(",").filter(Boolean)` drops the
  empty trailing segment, so typing a comma immediately rewrites the field without it ?
  you could not add another skill/tag/tech item by typing.
- **Tradeoff:** Parent still gets a cleaned array on each keystroke; only the displayed
  string is drafty. Blur normalizes spacing (`a,b` ? `a, b`).
- **Impact:** Rebuild Docker for the Master resume editor.

## 2026-08-02 ? Settings regrouped + fill_target

- **Decision:** Run settings split into Output / Models / Rewriting quality / Advanced
  (collapsed). Added `fill_target` (0.80?0.95) through CLI `--fill-target`, web
  `JobSettings`, and `fit.fit(fill_target=?)`, defaulting to `UNDERFLOW_THRESHOLD`.
- **Why:** Flat checkbox list was hard to scan; fill target is the one fit constant with
  a documented running cost worth exposing.
- **Tradeoff:** Did not expose `SEMANTIC_WEIGHT` or calibration constants ? those are
  correctness levers, not preferences.

## 2026-08-25 � UI polish pass (dark mode, confirms, run history)

- **Decision:** Ship a broad SPA ergonomics pass without reflowing the Tailor page's settings-first layout: dark mode via `prefers-color-scheme` token overrides + `--color-on-accent`, shared `Modal` / promise-based `confirm`+`choice` dialogs, sticky master-resume action bar, section reordering in the editor, bullet length counters from server `bullet_char_*`, disk-backed run history (`run.json` + `GET /api/jobs` + `_resolve_run`), ReportCard grouped into Coverage gaps / Run warnings, Vocabulary route rename with `/settings` redirect.
- **Why:** Critique items 1/3�7 plus smaller a11y/theme fixes; Tailor settings stay on top at every width (user preference � dropped `order-first`).
- **Tradeoff:** Dark mode has no manual toggle; history is per active workspace via `Job.workspace_id`; section reorder invalidates the score cache once (surfaced as a hint). Download/preview routes now fall back to disk so history survives restart.
- **Follow-up:** Manual check dark mode OS preference across tabs; keyboard-only confirm dialogs; section reorder Save/reload.

## 2026-08-25 � In-app theme toggle

- **Decision:** Add System / Light / Dark preference (cycle button in the header), persisted as `resume-tailor-theme` in localStorage; resolve to `data-theme` on `<html>`. Dark CSS tokens key off `:root[data-theme="dark"]` only (no longer raw `prefers-color-scheme`). FOUC script in `index.html` applies the stored override before paint.
- **Why:** Users with a dark OS preference need Light without changing Windows settings; the polish pass had deferred a manual control.
- **Tradeoff:** Three-state cycle vs a dedicated picker � one control, no extra chrome. `System` still tracks OS changes live.

## 2026-08-29 — Delete selected runs from history

- **Decision:** `POST /api/jobs/history/delete` removes finished runs' `output/.../jobs/<id>/` directories and drops them from the in-memory queue; the Recent runs panel gets per-row checkboxes, Select all (deletable runs only), and Delete selected with a confirm dialog. Queued/running jobs are skipped (`still active`).
- **Why:** Users need to clear old runs without hunting files on disk; `DELETE /api/jobs/{id}` remains cancel-only and 409s on terminal jobs.
- **Tradeoff:** Deleting the run currently on screen clears the results tiles when not busy; active runs cannot be bulk-deleted (use Cancel instead).

## 2026-09-19 — MCP server over HTTP (Claude Desktop front door)

- **Decision:** Add `src/resume_tailor/mcp_server/` as a thin stdio MCP client of the existing
  FastAPI app, not an in-process mount. Package named `mcp_server` (not `mcp`) to avoid
  shadowing the third-party SDK. Pin `mcp>=1.2,<2` because mcp 2.x renamed FastMCP.
- **Why:** Keeps a single owner of `config._ACTIVE` / path rebinding / the job queue. An
  in-process `/mcp` mount would need a remote bridge for Claude Desktop and would expose a
  second unauthenticated PII surface — against the deliberate no-CORS choice in `web/app.py`.
- **Tradeoff:** uvicorn must already be running; the MCP process probes `/api/config` on
  startup and never spawns the backend itself.
- **Scope (read plus starting runs):** list/activate profiles, start/wait on runs, read
  artifacts and application answers, regenerate cover letter, resume facts, verify claim.
  **Not wrapped:** `PUT /api/master-resume`, merge/import writes, `/api/template/*`,
  `/api/libraries/*`, `DELETE /api/workspaces/{id}`, history delete.
- **Follow-up:** Copy `docs/claude_desktop_config.example.json` into
  `%APPDATA%\Claude\claude_desktop_config.json`, restart Claude Desktop, run one real JD
  via `tailor_application`, confirm the run appears in the Tailor tab, then `verify_claim`
  on a fabricated sentence.

## 2026-09-21 — MCP: binary artifacts return paths only, never base64

- **Decision:** Removed the `base64` branch (and `_MAX_INLINE_BYTES = 200_000`) from
  `mcp_server/tools.read_artifact`. `.docx` / `.pdf` now always return
  `disk_path` + `download_url` with `inline: False`; the three `.md` kinds still
  inline `text` and now set `inline: True` for symmetry.
- **Why:** The 200KB cap was sized against Claude Desktop's 1MB hard limit, not against
  token cost. Every `tailored.pdf` in `output/jobs` (46/46, median 47KB) fell *under* it,
  so every `read_artifact(kind="resume_pdf")` inlined ~64k base64 chars ≈ 20k tokens.
  A base64 zip/PDF is also unreadable to the model, and FastMCP serializes the returned
  dict as JSON text — not an MCP blob — so the host can't render it as a file either.
  The payload was pure cost with no consumer (nothing in the repo read the field).
- **Tradeoff:** No way to hand a small binary to a host that can't see the filesystem.
  `_artifact_disk_path` already returns `None` off-filesystem, leaving `download_url`
  as the only pointer. If a real need appears, return a proper MCP blob content type
  rather than reinstating the dict key.
- **Spec delta:** Extends the existing "prefer paths for large files" intent to *all*
  binaries. Tool docstrings in `server.py` and the `get_artifact_paths` hint no longer
  warn about the 1MB limit, since `read_artifact` can no longer trip it.
- **Note:** `read_artifact` still GETs the full bytes to populate `size_bytes` and to
  reuse the client's 404/409 error translation. `get_artifact_paths` likewise still
  downloads all seven artifacts (~1.5MB) purely as an existence check — costs latency,
  not tokens; deliberately left alone.

## 2026-09-24 — Two SPA gotchas found in the UI fix pass
- react-router 7's `setSearchParams` is memoised over the current params, so it changes
  identity on every URL change. An effect that lists it as a dependency re-runs on each
  navigation: RunPage's "reset result_tab on a new job" effect deleted the tab the user
  had just clicked. Key such effects on the real trigger (a ref holding the last jobId).
- `index.css`'s unlayered `button { font: inherit }` beats Tailwind's layered `text-*`
  utilities on `<button>` but not `<a>`, so mixed button/link rows rendered at different
  sizes. Put the font size on the container, and use `.rt-control` to give links the
  same 36px/44px min-height buttons get. (Moving the reset into `@layer base` would fix
  it globally but resize every button that has a `text-*` class — not done yet.)

## Request gate (B8, 2026-09)

- `web/security.py` `RequestGateMiddleware`, outermost. It always refuses a Host that is not loopback or listed in `RESUME_TAILOR_ALLOWED_HOSTS` (400, blocks DNS rebinding). It also refuses a non-GET whose Origin is foreign or `null`, or that the browser marks `Sec-Fetch-Site: cross-site` (403).
- The session token is opt-in (`RESUME_TAILOR_TOKEN`: a value, or `auto`), not always on as the plan said. On a local-first install any process that could steal a token can already read `data/`. Docker publishes on 127.0.0.1 only, and the tunnel sits behind Cloudflare Access, so a mandatory token would mostly add a sign-in step. The desktop shell (DK2) will set it.
- When the token is on, `/?t=<token>` sets an HttpOnly SameSite=Strict cookie. `/api/*` needs the cookie or `X-RT-Token`, except `/api/health`. The token is written to `<DATA_ROOT>/.session_token` (0600) for the MCP client, and `logs.redact` strips `?t=` values.
- Breaking for tunnel users: the public hostname has to go in `RESUME_TAILOR_ALLOWED_HOSTS`, as the README step now says. The 400 body names the variable.
- Not done: running the Docker image as a non-root user. With Linux bind mounts owned by the host uid, a fixed container uid cannot write `data/`, so it needs a uid-mapping decision first.
