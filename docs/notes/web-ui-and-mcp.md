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

## Settings page (Phase 2H)
- `/settings` replaces the old redirect to `/vocabulary`. It has five tabs (AI model, Documents, Data, Advanced, About), picked with `?tab=`. Vocabulary left the top nav; Settings → Advanced links to it, and the `/vocabulary` route still exists.
- The model and key checks (`POST /api/models/test`, `GET /api/models/local`, `POST /api/pdf/test`) live in `web/routes/system.py`. They are live probes and never write settings.
- Export (`data_transfer.export_zip`) snapshots `app.db` with SQLite's online backup and skips `secrets.enc`, `.secret_key` and `.session_token`, so keys never travel with a zip. Import always creates a NEW profile and never overwrites the active one: "import" can't destroy data, and a user who wants a replacement deletes the old profile themselves. Import rejects unsafe member paths and enforces 2 GB / 50k-file caps.
- Reset (`POST /api/data/reset {confirm:"DELETE"}`) moves the profile's folders to `DATA_ROOT/.trash/<id>-<stamp>/` rather than deleting them. It then re-seeds defaults, so the profile is usable straight away.
- `storage/db.connect` forgets the "schema initialised" flag when the DB file is missing, so a DB recreated after a reset gets its schema again.
- Resume history restore calls `editorState.syncFromDisk`, because the server has already written the file; `loadDraft` would make the restore look like an unsaved draft.

## First-run onboarding (Phase 2B)
- `/welcome` is a six-step wizard: field, AI model (the Settings `ModelsSection`, embedded), resume (the Template page's `TemplateImportWizard`, with calibration on by default), review, application basics, done. Progress is `kv('onboarding')` in the profile's app.db, so it is per profile and resumes after the app closes.
- Page fit has no step of its own: the import wizard already calibrates on install ("Calibrate too" defaults on), and the review step reports whether fit was measured. A separate step would only repeat that.
- The field choice is applied on the client, through `libraryState.setEnabled` and `runState.setSettings`. Doing it on the server would let the SPA's cached, autosaving settings overwrite the new sources on its next save. The field owns only `core-tech` and `finance-consulting` and the three built-in sources; packs and sources the user added are left alone. Re-choosing the same field changes nothing, so tuning done since survives.
- The Simplify category names are copied from the live README headings (checked 2026-09); `sources.parse_readme` silently skips a category it cannot find, so a typo would mean "no jobs found", not an error.
- The redirect (`OnboardingGate` in `App.tsx`) runs once per page load and never from `/settings`, so a student can leave the wizard for the editor and come back through the setup checklist's "Open guided setup". Skipping records `skipped` and stops the redirect for good.
- A profile with an installed template or at least one resume entry and no onboarding row predates onboarding. It is recorded as complete the first time it is read, so an upgrade never sends an existing user through setup.

## Tailor page split and job-description input (Phase 2C, T1–T3)
- `pages/RunPage.tsx` became `pages/run/{RunPage,JobInput,RunOptions,ProgressPanel,ReportCard}.tsx`. Behaviour is unchanged apart from the items below.
- T1: `POST /api/jd/fetch {url}` and `POST /api/jd/extract-file` (`jd_input.py`) only fill the text box. The student sees and can edit the text before a run, so a bad extraction is visible instead of silently tailored against. LinkedIn and Handshake are refused up front, without a network call: they need a signed-in session, which only the browser extension (Phase 4) has. A 404/410 reads as "posting closed". Text under 200 characters is an error. Text over 50k characters is cut with a warning, never silently; the cap matches `JobCreateRequest.jd_text`.
- T2: the model choice left the Tailor page; the Options card names it and links to Settings → AI model. "Reset options to defaults" keeps the model, effort and apply settings, since those are set elsewhere. Whether "More options" is open is remembered per profile in localStorage (a convenience only).
- T3: `lib/runSteps.ts` groups pipeline stages into six plain steps. As with `runProgress`, the furthest step reached wins, because the fit loop repeats rewrite/render/measure. The time estimate is the median of the last five successful runs in history, and nothing is shown with fewer than two.

## Bullet review and AI-free re-render (Phase 2C, T4)
- Each run now saves `render_snapshot.json` and `template.docx` beside `bullets.json` (`rerender.save_snapshot`). The snapshot holds the resume the final render actually used (after exclusions and facet truncation), the layout, contact fields, target pages and merges. A re-render replays `render.render` with those inputs, so it uses the run's own template even if the live template has changed since. Runs from before this change return 409 with "Tailor again to edit bullets".
- A request states the full set of changes relative to the AI version (edits / reverted / removed), not relative to the last save. That makes it idempotent, and "Reset to AI version" is just an empty request. The AI's files are copied to `*.v1.*` the first time an edit is saved.
- Typed text goes through `rewrite._check_fabrication` for warnings only; it is the student's own claim. Each flagged bullet must be confirmed ("This is accurate") before anything renders, and the confirmation is recorded in `review.json`. "Use original" on a merged bullet restores every source bullet it absorbed, which may overflow.
- A result over the page target is never saved, and the response gives the lines over. That is the fit loop's never-truncate rule applied to manual edits. Without a PDF engine the page count is an estimate, reported as one.
- After a save, `packet.json` (when present) is rebuilt, because the packet records each file's sha256 and the next fill must upload the edited resume.
- The route holds `template_ops.LOCK` like a profile switch does, because the render reads config's per-profile fit constants.

## Tailor page T5–T6: plain-language report and run history search (2C)

- `ReportCard` leads with one headline (`lib/reportSummary.reportHeadline`: "Matched 8 of
  10 required skills · 1 page") and four tiles named from `lib/glossary.ts`; the page
  count lives in the headline, not a tile. Model, ranking, PDF engine, page-fit source
  and fit passes sit under "Technical details".
- Coverage gaps are three checklists from `gapGroups`: missing (`no_evidence` plus
  `missing_must_haves`, deduped: never added for the student, link to the editor),
  untagged (`untagged_evidence`, the evidence snippets reworded by `describeEvidence`),
  and named differently (`near_miss`, link to Vocabulary). The planned one-click "add tag
  X to bullet Y" was not built: gap evidence names a skills line, project tech or
  coursework, never a specific bullet, so there is no bullet to tag without guessing.
- Run history: `RunHistoryEntryOut.company` comes from the run's posting metadata ("" when
  the JD was pasted); search matches every word against role + company client-side.
  "View" is now "Open". "Compare selected" (exactly two finished runs) fetches both
  runs' `/bullets` and diffs the bullets each final document shows (`current_text`),
  keyed by master bullet id (`lib/runHistory.compareRuns`). Runs made before the render
  snapshot existed cannot be compared; the dialog shows the 409 text.

## Apply page 2D (A1–A8)

- `pages/ApplicationsDashboard.tsx` became `pages/apply/{ApplyPage, ApplicationsTable,
  ApplySettingsDrawer, OperationBanner, BrowserConnection, useApplicationTable}`; pure
  logic is in `lib/applyPage.ts` and `lib/applyNotify.ts`. `ProfileGapsNotice` moved to
  `components/`. `ApplicationProgress` was replaced by `OperationBanner`.
- Tabs (`?tab=needs|progress|done`) map to the existing list groups: review, working,
  archived. With no `tab` param the page waits for the review count (skeleton) and then
  opens Needs you if anything waits, so it never flips tabs after first paint. Done =
  archived. To make "Done" hold what students expect, `store.set_status` now archives on
  the transition to **skipped** as well as submitted (a restore still sticks).
- "Why it needs you" (`reviewReason`) is built client-side from the server's
  `review_summary` plus fill hand-off details, so no second copy of the store logic.
  The row's primary button names the step ("Sign in", "Answer 3", "Enter code",
  "Final check"); a blank profile fact links straight to its field. Continue/Reopen keep
  priority when the fill's tab state allows them. There is no in-app OTP entry: the code
  goes into the browser tab, then Continue.
- Settings drawer = `Modal placement="right"`. Modal now reads `onClose` through a ref
  (a parent re-render no longer re-runs the focus effect and steals focus mid-typing),
  and only the topmost open dialog handles Escape/Tab (a confirm over the drawer).
  Auto-submit asks for confirmation when turned on and exposes `auto_submit_ats`, which
  `fill.decide_submit_action` already required but no UI set, so enabling auto-submit
  used to do nothing. A warning shows when no platform is ticked. A cap of 0 reads "No
  auto-submits".
- Pause: `operations.control("pause")` sets `_PAUSE`; the worker checks it only at the
  top of the per-application loop (stage `paused_by_user`), so it never interrupts a
  form. `find` can't be paused. For a user pause, Skip is hidden: the server's skip at
  the top of the loop would just resume.
- "Run now" = `POST /api/applications/daily-run` → `scheduler.run_now` with app.py's own
  `_apply_busy`/`_start_daily_run`. It counts as today's scheduled run only when today's
  time has already passed, so a midday run never cancels tonight's.
- Desktop notifications use the browser Notification API (opt-in, per-browser
  localStorage `rt.apply.notify`). They come from `applyNotifications(prev, next)`
  diffs, and the first poll never notifies. Tauri native notifications replace this in
  Phase 5.
- Detail page tabs: Overview, Job description, Files (with the T4 bullet editor; the
  rerender route already rebuilds the packet), Answers (the fill's `long_text_answers` +
  packet), Form review, Timeline, Notes (`PUT /api/applications/{id}/notes`, via
  `store.patch`). Old `?tab=documents|content` links are aliased. Editing prepared
  answers is deferred to P3-A (answer memory). No screenshots exist yet
  (`FillResult.screenshot_path` is never written), so the Timeline shows status history
  only until SS5.

## Profile 2E: one save bar, student fields, validation (2026-09)

- `pages/profile/ProfilePage.tsx` owns a single sticky save bar across all three
  sub-tabs. The change count is `changedKeys(saved, draft)` plus one when the resume
  draft is dirty. Save runs `validateProfile` first. When a field is invalid, nothing is
  saved: the bar lists the problems and jumps to the first one (on the current tab when
  there is one), opening its tab and group. Otherwise it saves the resume and then the
  profile, and names the part that failed. `EditorPage embedded` hides the editor's own
  Save button and "Unsaved changes" pill.
- Groups are keyed by the backend section name (`packet.PROFILE_FIELDS`), so a gap chip
  opens the group that holds the field. Every group starts open, and the groups a
  student collapses are remembered in localStorage (`rt.profile.closedGroups`).
- New profile fields:
  - `visa_status`: the sponsorship defaults come from `sponsorship_from_visa`, and the
    UI mirrors that as "Auto from visa" hints, which also suppress the blank-gap note.
  - `graduation_date`, `class_year` (blank means it is derived by `class_year_for`),
    `gpa_display`, `school_email`, `security_clearance`, `drivers_license` and
    `hours_per_week_available`.
  - `transcript_path` is server-owned. Only `POST/DELETE /api/applicant-profile/transcript`
    set it (PDF only, 10 MB maximum); the PUT keeps the stored value. The upload response
    is adopted with the student's unsaved edits re-applied on top.
- `packet.profile_path(section, key)` sends `class_year` and `school_email` gaps to the
  application tab. Other education gaps still go to the resume.
- Inline errors appear after a field is blurred, or on every field after a Save attempt.
  A blank value is never an error.

## Resume editor 2F: split, presets, bullet coach, tag chips, history (2026-09)

- `pages/EditorPage.tsx` is now split into `pages/editor/*`, one component per file.
  `suggestMissingTags` moved to `lib/bulletLint.ts`.
- "Add section" offers familiar headings: Research, Leadership, Activities and
  Volunteering are experience-kind; Certifications, Awards, Publications and Languages
  are list-kind. There is also "Something else…" with a free title and a layout kind.
  No new section kinds were added.
- `lintBullet` gives non-blocking tips in the browser:
  - weak opener;
  - an opening verb repeated within the entry;
  - no number (hidden when "has metric" is ticked);
  - more than 2 lines at the calibrated `chars_per_line` (hidden when the character
    counter already warns);
  - no tags.
- Tag chips: vocabulary hits found locally show as "+ tag" buttons at once. "Suggest
  tags" calls `POST /api/master-resume/suggest-tags`, which is pure matching in
  `tag_suggest.py` over the draft vocabulary plus `config.TAG_ALIASES` (the active
  packs). The longest phrase wins, and names of 1–2 letters only match in capitals.
  Nothing is added without a click, because tags are the fabrication guard's whitelist.
- History: the editor has a History drawer (the shared `ResumeHistoryList`, also used by
  Settings → Advanced) with "Undo last save", which restores the previous version. A
  restore is itself a new version.

## Template page 2G: gallery, plain-language issues, page fit (2026-09)

- The saved-template list is now a card gallery. Each card shows page one of that
  entry's `original_export.docx`, served by
  `GET /api/template/library/{id}/thumb.png`. `thumbnails.py` converts the docx with the
  configured PDF engine, then rasterises page one with pdfium (new dependency
  `pypdfium2`, Apache/BSD). It writes the PNG with a small encoder, so Pillow isn't
  needed. The image is cached as `thumb.png` in the entry folder and re-rendered when the
  baseline is newer. With no PDF engine the route returns 503 and the card shows a
  placeholder. The thumbnail shows the design only: no tags, no resume content.
- `lib/templateIssues.ts` explains every analyzer issue code (title, why, steps in Word
  or Google Docs, or a fix in the app). `scripts/export_issue_codes.py` writes
  `lib/templateIssueCodes.json` from `template_analyze.py`. `tests/document/test_issue_codes.py`
  fails when that file is out of date, and a vitest fails when a code has no
  explanation. The raw analyzer message stays under "Details".
- The "Page fit tuning" card calls `POST /api/template/calibrate`
  (`template_ops.calibrate_now`, which returns 409 while a job runs). A failure comes
  back as `ok=False` with the reason and the old constants stay in effect.
  `CalibrationInfo.calibrated_at` is the calibration file's mtime. The stale/missing
  messages now point at this button instead of re-uploading.
- The "use a default template instead" action (`IssueHelp.useDefault`) is recorded in
  the data but not rendered until the P3-T default templates exist.

## Tests 2I: browser e2e on a fake model (2026-09)
- `RESUME_TAILOR_FAKE_LLM=1` makes `llm.client_for`/`async_client_for` return `fake_llm.FakeClient`: rewrite echoes each bullet's current text, scoring gives 6/10, extraction keeps the known tags the posting names, everything else gets the smallest valid instance. Replies are read off the prompt, so the fabrication guard stays clean. The server logs a warning at startup when it is on; it is never on by default.
- `scripts/e2e_server.py` runs a throwaway server (temp dirs, in-memory secrets, auth off) and seeds a synthetic resume, one template (via `tests.test_web._resume_upload_with_profile`) and three applications. Playwright's readiness URL is the last seeded application, so tests never start mid-seed.
- `frontend/e2e/app.spec.ts` covers tailor + bullet edit + re-render, profile save/validation, Apply tabs, template gallery, editor coach/preset, and onboarding/settings; `a11y.ts` fails on serious/critical axe violations. Page-fit steps still need LibreOffice, so CI installs it in the `e2e` job.
- Found by the suite: BulletReview fetched while the run was still going, got a 409 and never retried (now waits on `ready`); the light accent failed contrast on `accent-soft` (4.17:1), darkened to #077468.
- `frontend/.gitignore` gained `test-results/` and `playwright-report/` (Playwright output only).

## Desktop packaging, Phase 5 scaffold (2026-09)

- **Shape.** Tauri v2 shell (`desktop/src-tauri/`) + a PyInstaller `--onedir` build of the
  server (`desktop/sidecar/resumetailor.spec`, entry `src/resume_tailor/infra/desktop_main.py`).
  The shell spawns the server, reads stdout for `READY <port> <token>`, and navigates its
  window to `http://127.0.0.1:<port>/?t=<token>` — the existing B8 cookie bootstrap, so the
  web UI needs no desktop-specific code. The window starts on a bundled page
  (`desktop/ui/index.html`, "Starting…"); only that page has Tauri IPC (`log_folder`), the
  127.0.0.1 origin gets none.
- **`desktop_main` sets the environment before importing the app** because `config` reads
  `RESUME_TAILOR_*_DIR` at import. Storage defaults to the per-user app-data folder (own
  `app_data_dir()`, same paths as platformdirs, no new dependency); any variable already set
  wins. The token is always on: blank/`auto`/`off` get a fresh random token, because the
  shell must know the value the server will use. Ports 8000–8010 first (where the extension
  scans), else any; the socket is bound before uvicorn starts and handed over, so no race.
  READY is printed from `Server.startup` after `started`, never before the port listens.
- **`RESUME_TAILOR_FRONTEND_DIST`** (new, `web/app.py`): the frozen build points the SPA mount
  at `_MEIPASS/frontend/dist`; unset keeps `PROJECT_ROOT/frontend/dist`.
- **Orphans.** Killing the shell (not quitting) left the server holding its port. Fix:
  `--exit-with-stdin` — the shell holds a piped stdin it never writes; EOF (any shell exit,
  including SIGKILL) sets `server.should_exit`. Verified under Xvfb: 0 servers after killing
  the shell.
- **Crash restart.** stdout EOF = server exited → restart, at most 3 in a row without a READY
  in between (READY resets the count); then the start page's `#failed` state shows the log
  folder. Quit sets `quitting` first so the reader thread does not restart it.
- **Resources, not `externalBin`.** `externalBin` takes one executable; the onedir build is a
  folder (`_internal/` beside the exe). `bundle.resources` maps it to `server/`; the bundler
  copies the folder's *contents* flat, and `server_program` accepts either layout.
- **Verified here (Linux):** frozen sidecar 263 MB, READY, SPA and API served, token 401/200,
  Playwright driver, watchlists and seeds bundled; `desktop/sidecar/smoke.py` passes against
  it; shell spawn/restart/no-orphan under Xvfb; `cargo test` (READY parsing). Not verified:
  Windows/macOS installers (built only by `release.yml` on a `v*` tag).
- **Deviations from DK1–DK8:** no updater, signing or notarization (owner's decision; the
  release is a draft); macOS ships per-arch dmgs (arm64 + x64) instead of universal; tray is
  Open/Quit only (no Pause automation / Run discovery / autostart); failure screen shows the
  log folder rather than "Copy diagnostics"; not done — DK5 LibreOffice detection UI and font
  registration, DK6 data-folder import, DK8 store publishing; not verified on clean VMs.

### Desktop fixes found while writing the owner guide (2026-09)

- **Template install in the frozen app.** `template_ops._run_build` spawned
  `sys.executable scripts/build_template.py`; frozen, `sys.executable` is the server and
  `scripts/` is not bundled, so the "build" would have started a second server and hung
  the install. Frozen (or no script) now returns non-zero at once and the caller's
  in-process build runs — the same fallback tests already exercise.
- **`.env` in the frozen app.** `config` loads `PROJECT_ROOT/.env`, which frozen is the
  install folder. `desktop_main` now reads `<app data>/.env` for missing variables (a copy
  of a checkout's `.env` works) and defaults `CHROME_CDP_URL` to `http://127.0.0.1:9222`
  instead of the Docker host name.
- **Windows data folder is `%LOCALAPPDATA%\ResumeTailorData`.** Tauri's per-user NSIS
  installer puts the program in `%LOCALAPPDATA%\<productName>` = `...\ResumeTailor`; data
  must not share a folder with files updates replace (checked in the bundled NSIS
  template: uninstall deletes only its own files, but the overlap is fragile).
- **release.yml**: Windows only by default (macOS minutes cost 10x on a private repo; opt
  in per run or with `RELEASE_MACOS=true`); the macOS x64 job is gone (macos-13 runners
  retired); a tag `vX.Y.Z` sets the installer version so installs upgrade in place.
- Known limit: `transcript_path`/`portfolio_path` and packet artifacts are absolute paths,
  so moving the data folder needs a re-upload of those files (which also re-keys packets).

### In-app updates and the MIT license (2026-09-26)

- **License**: MIT (`LICENSE`); the repo goes public so installed apps can read Releases
  without credentials. `scripts/third_party_notices.py` writes THIRD-PARTY-NOTICES.txt
  (Python from `requirements.lock` for this platform, npm runtime deps, cargo crates;
  identical texts deduplicated) into the installed server folder, with `LICENSE.txt`.
  Attribution matters for docxtpl (LGPL-2.1; PyInstaller onedir keeps it replaceable),
  certifi and tqdm (MPL-2.0).
- **Updater**: tauri-plugin-updater, driven from Rust only. The SPA still gets no Tauri
  IPC; the server relays over the pipes the shell already held (`SHELL check|download|
  apply` on stdout, `UPDATE <json>` on stdin, which used to be read and discarded). The
  alternative, giving the 127.0.0.1 origin IPC, would hand every script on that origin
  the power to install software.
- **Never automatic**: check on start (+30 s) and every 12 h; download only on the
  user's click; `apply` only when `get_queue().busy()`, `daily_busy()` and
  `operations.active()` are all clear, after a zip of data + templates to
  `OUTPUT_ROOT/backups` (newest 3; output/ is never itself backed up and is gitignored in
  a checkout). A failed backup aborts the install.
- **Draft gate**: release.yml keeps releases as drafts and adds `latest.json`; the feed
  is `releases/latest/download/latest.json`, which ignores drafts, so publishing is the
  ship step. The workflow refuses to build while `plugins.updater.pubkey` is the
  placeholder or the signing secret is missing.
- **Shell restart bookkeeping**: `server_exited` now acts only if the child in the mutex
  is still the one whose stdout ended (pid), so a server restarted after a failed
  install is not mistaken for the old one exiting.
- Not verified here: no Rust toolchain on the dev PC, so `update.rs`/`lib.rs` compile
  and `cargo fmt` are first checked by CI's desktop job; the end-to-end install needs
  two signed builds (docs/GUIDE.md §6).

## 2026-09-27 - Per-request run context and mutable-state audit

RunContext now captures workspace paths, calibration, routing, vocabulary, and writing style. JobQueue enters one context per job; the worker remains serial. ContextVar values are copied explicitly by run_in_context/submit_in_context for child threads. A module subclass maps legacy config monkeypatch.setattr calls into the process default context, so test patches remain effective without shadowing context views. The path and fit names have no real module globals; config.__getattr__ serves them. resolve and style.activate update the active context, or the process default when none is active. Existing cache fingerprints and keys are unchanged.

| Module | Mutable state audited | Classification and disposition |
| --- | --- | --- |
| config | _DEFAULT, _RUN_CONTEXT, _ACTIVE, _PINNED | Workspace paths, calibration, backends, vocabulary, and style are per run in RunContext; _DEFAULT and _ACTIVE preserve legacy process defaults; _PINNED remains a ContextVar overlay. |
| config | _VERB_INDEX, _VERB_INDEX_SOURCE, _VERB_INDEX_LOCK | Process cache keyed by vocabulary dict identity; lock and captured local index prevent cross-context races. |
| style | _ACTIVE | Process default only; active run styles live in RunContext. |
| libraries | _ACTIVE_MEMO | Per-workspace memo now keyed by libraries path; writes invalidate all entries. |
| web/jobs | queue_singleton, JobQueue._jobs/_pending/_order/_lock/_worker | Process scheduler and job records, keyed by job id; each execution builds its own workspace context; single worker retained. |
| workspace | _LOCK | Process registry lock; shared by all workspace mutations. |
| convert | _profile_dir, _SOFFICE_LOCK | Process LibreOffice profile and converter lock; output arguments carry workspace paths. |
| desktop_update | _waiter, _state, _out, _lock, _write_lock | One application updater and output stream, intentionally process shared. |
| logs | _configured_dir and run-id ContextVar | Logger configuration is process wide under OUTPUT_ROOT; run id is already context local. |
| llm | _LEARNED_CEILING | Process measurement cache keyed by base URL and model, independent of workspace. |
| secret_store | _backend, _backend_lock | Process credential backend rooted at DATA_ROOT, independent of active workspace. |
| mcp_server/server | _client | Process client to one local web service, independent of workspace. |
| apply/operations | _ACTIVE_ID, _LOCK, _RUN_LOCK, _CANCEL, _RESUME, _SKIP, _PAUSE | One process Apply/browser operation at a time; the lock enforces that ownership. |
| apply/store | _cache, _imported, _LOCK | Snapshot cache includes database path and generation; import set is keyed by database path; lock covers shared access. |
| apply/submit_guard | _last_submit, _PACE_LOCK, _PAUSE_LOCK, _rng, _sleep, _clock | Installation-wide submit pacing and pause state; shared intentionally across profiles. Clock/sleep are test seams. |
| apply/ats_api | _ASHBY_BOARD_CACHE | External company board metadata keyed by company, independent of workspace. |
| apply/form_guards | _blocked, _blocked_lock | Process block list keyed by host, shared across Apply actions. |
| apply/daily, apply/scheduler | _DAILY_LOCK, _PROGRESS_LOCK, _STATE_LOCK | One process Apply scheduler and progress writer, intentionally shared. |
| apply/packet | _WRITE_LOCK | Serializes packet replacement for a job id; packet path resolves within the run context. |
| web/extension | _pending, _seen_written, _LOCK | Installation-wide extension pairing and token throttle; store is under DATA_ROOT. |
| web/security | _auto_token | Installation-wide session token, independent of workspace. |
| web/template_ops | LOCK | Shared template mutation lock; workspace-specific file paths are resolved per call. |
| web/routes/setup | _probe_cache | Connectivity probes keyed by endpoint/model, independent of workspace. |
| web/app | _scheduler_stop | Process scheduler lifecycle event, shared intentionally. |
| storage/db | _local, _initialised, _init_lock | Connections are thread local and keyed by database path; initialized set is path keyed. |
| Static lookup dictionaries across config, apply, render, and web modules | Provider tables, aliases, prices, ATS hints, schema maps, route registries | Process shared read-only reference data; no run mutation or workspace data is stored in them. |

The two legacy tests that assumed process-wide routing/rebound globals were updated to assert the new context contract. No queue parallelism, Apply concurrency, cache-key format, or process model changed.

### Profile .zip import and export size fix (2026-09-27)

- **Per-path request size limit in ASGI middleware**: `_RequestSizeLimitMiddleware` previously rejected every request with `Content-Length > 10 MB` before FastAPI parsing, blocking large profile imports despite `data_transfer.MAX_IMPORT_BYTES = 2 GiB`. The middleware now checks path and method: `POST /api/data/import` allows requests up to `data_transfer.MAX_IMPORT_BYTES` plus a 1 MiB multipart overhead allowance; all other paths retain the existing 10 MB limit (`template_ops._MAX_UPLOAD_BYTES`).
- **Streaming import without memory buffering**: `import_data` in `web/routes/system.py` previously buffered the entire uploaded zip into memory via `await file.read()`. It now inspects the spooled size via `file.file.seek(0, 2)` / `tell()` / `seek(0)` for the 413 check, and passes the underlying spooled file object directly to `data_transfer.import_zip(file.file)` under `template_ops.LOCK`. `data_transfer.import_zip` and `read_manifest` accept binary file-like objects (as well as `bytes` or `Path`), streaming member contents to disk with `shutil.copyfileobj`. All safety checks (`MAX_IMPORT_FILES`, zip-bomb uncompressed size cap, path validation, skipping `workspace.json`) are preserved.
- **Export written to temp file**: `data_transfer.export_zip` now writes the export archive to a temporary file (`tempfile.NamedTemporaryFile`) on disk rather than buffering in `io.BytesIO`. The `/api/data/export.zip` route returns a `FileResponse` holding `template_ops.LOCK` while building, and cleans up the temporary file via `BackgroundTask(path.unlink, missing_ok=True)`. `export_zip_bytes` provides a buffered-bytes wrapper for callers that need bytes.
- **Frontend error clarity and size limit indication**: `frontend/src/lib/errors.ts` maps 413 / oversized payload errors to plain English ("File is too large" / "This file is larger than the 2 GB import limit."). In `DataSection.tsx`, the card description indicates up to 2 GB and `onImport` validates `file.size <= 2 GB` before uploading.
- No deviations from the design specification.

 # #   2 0 2 6 - 0 9 - 2 7   -   B o u n d e d   p a r a l l e l   t a i l o r i n g   p i p e l i n e 
 
 J D   c o n s e n s u s   v o t e s   u s e   a   t h r e e - w o r k e r   p o o l   a n d   c o l l e c t   r e s u l t s   i n   s u b m i s s i o n   o r d e r ;   c a c h e   w r i t e s   p u b l i s h   v i a   t e m p o r a r y   f i l e   r e p l a c e m e n t   u n d e r   a   w r i t e   l o c k .   T h e   w e b   q u e u e   d i s p a t c h e s   u p   t o   e a c h   j o b ' s   ` m a x _ c o n c u r r e n t _ j o b s `   l i m i t   ( d e f a u l t   t w o )   w h i l e   c o n v e r s i o n   h a s   o n e   p r o c e s s   l o c k   f o r   W o r d   a n d   L i b r e O f f i c e .   D a i l y   r o w   w o r k e r s   i n h e r i t   R u n C o n t e x t ,   p r e s e r v e   s a m e - r o l e   g r o u p   o r d e r ,   a n d   g u a r d   s h a r e d   c o u n t e r s ,   i n d e x   r e g i s t r a t i o n ,   p r o g r e s s   s n a p s h o t s ,   a n d   l o g   a p p e n d s .   P D F   c o n v e r s i o n   r e m a i n s   s e r i a l i z e d   b e c a u s e   W o r d   C O M   a n d   t h e   s h a r e d   L i b r e O f f i c e   p r o f i l e   a r e   n o t   s a f e   t o   o v e r l a p . 
 
 
 
 # #   2 0 2 6 - 0 9 - 2 8   -   m a c O S   a d   h o c   s i g n i n g   f o r   A p p l e   S i l i c o n   r e l e a s e 
 
 
 
 * * W h a t : * *   T a u r i   n o w   s i g n s   t h e   m a c O S   a p p   a d   h o c   a n d   t h e   r e l e a s e   w o r k f l o w   v e r i f i e s   t h e   r e s u l t i n g   a p p   s i g n a t u r e   b e f o r e   u p l o a d i n g   t h e   D M G . 
 
 * * W h y : * *   v 0 . 2 . 4   m a c O S   b u n d l e   h a d   n o   T a u r i   s i g n i n g   i d e n t i t y ;   T a u r i   d o c u m e n t s   t h a t   A p p l e   S i l i c o n   d o w n l o a d s   f r o m   G i t H u b   R e l e a s e s   c a n   b e   r e p o r t e d   a s   d a m a g e d   w i t h o u t   a n   a d   h o c   s i g n a t u r e .   T h e   T a u r i   u p d a t e r   a r c h i v e   h a s   a   s e p a r a t e   m i n i s i g n   s i g n a t u r e . 
 
 * * I m p a c t : * *   T h e   a d   h o c   s i g n a t u r e   c h e c k s   b u n d l e   i n t e g r i t y   a n d   a d d r e s s e s   t h a t   G a t e k e e p e r   s y m p t o m ,   b u t   i t   d o e s   n o t   i d e n t i f y   t h e   d e v e l o p e r   o r   n o t a r i z e   t h e   a p p .   m a c O S   m a y   s t i l l   r e q u i r e   a p p r o v a l   i n   S y s t e m   S e t t i n g s   >   P r i v a c y   &   S e c u r i t y .   D e v e l o p e r   I D   s i g n i n g   a n d   n o t a r i z a t i o n   r e q u i r e   A p p l e   c r e d e n t i a l s . 
 
 
## 2026-10-02 — Shared model queue, resume quality review, and template switching

**What:** Limit physical model requests per endpoint (local 1, cloud 3), require version-bound acknowledgement of underfill/missing selected sections before Fill, and restore page-fit measurements only for matching template/profile/resume/PDF-backend inputs.
**Why:** Job and browser concurrency controls do not bound provider traffic. Preview, selection badges and metadata previously refreshed independently; saved-template activation also recalibrated by default.
**Impact:** Limits are process-wide across workspaces, with no fixed batch pause. Older resumes without sufficient saved measurement evidence require Prepare again. Application acknowledgement fields use the existing SQLite JSON column, so old rows acquire empty defaults without a destructive database migration. Previously measured calibrations without input fingerprints are preserved as unverified backups rather than reused across a switch.

### 2026-10-04 — post-fit stages run concurrently; expansion on demand

- `_TailorJobRun._bonus_artifacts`: expansion and skills run on worker threads
  (`config.submit_in_context`) while the cover letter drafts on the job thread (its
  render may drive Word over COM). Each stage already swallowed its own errors and
  wrote its own files; `infra/model_queue.py` still caps in-flight model requests
  (local 1, cloud 3), so local backends just serialise. The CLI stays sequential
  (it prints each artifact).
- `JobSettings.no_expand` now defaults to True: only Apply uses the expansion, and
  every Apply tailor run goes through `daily_rows._job_settings`, which forces it on;
  the MCP `tailor_application` tool forces it on too. Any finished run can make it
  later with `POST /api/jobs/{id}/expansion` (`job_followups.generate_expansion`:
  saved requirements/bullets/backends, unfiltered master resume, cached relevance
  scores, one expand call, packet rebuilt if present). Apply's Prepare calls the same
  function when `preparation.check` reports only `missing_expansion`, instead of
  re-tailoring the whole run. Existing profiles saved `no_expand: false` explicitly,
  so the new default only reaches new profiles until the user flips the run option.

## 2026-10-05 — Apply Find jobs progress and control alignment

**What:** Find jobs exposes optional structured phase/count progress through the existing operation API. Sources and postings each occupy half the bar; completed searches reach 100%, while older active operations show an indeterminate indicator. Activity renders newest first. Settings label rows reserve the help control's height, and header pills share desktop/touch control sizing.
**Why:** Find was previously one 0/1 task regardless of work performed. Logs remain human-readable activity rather than a source of parsed progress; source failures and completed posting futures count as attempted work. The existing unlayered row-action CSS makes help buttons 28px on desktop and 36px on touch.
**Impact:** The percentage reflects equally weighted stages, not time remaining; Find no longer shows the item-based ETA. Existing nightly progress and Prepare/Fill behavior are retained. Model control alignment and pill sizing are verified with browser geometry checks.

## 2026-10-05 — Header pill typography CSS cascade

**What:** Header pills now use a scoped unlayered typography rule in addition to shared control sizing.
**Why:** Browser inspection proved the global unlayered `button { font: inherit }` overrides layered Tailwind typography: Ready/Pause rendered at 16px/400 while the update link rendered at 12px/600 despite matching utility classes.
**Impact:** All three pills now render at 12px/600 with a 16px line height; unrelated button styles remain unchanged. Browser regressions check computed typography as well as geometry.
