# Apply funnel — implementation notes

Covers: discovery sources, screening, packet, ATS hints, browser/filler, Workday/Greenhouse, daily run, Apply page.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-09-21 — Apply Phase 1: packet, ats_hints, answer

- **Decision:** Added `apply/packet.py`, `apply/ats_hints.py`, and `apply/answer.py` as pure
  disk assembly plus one guarded `"answer"` LLM stage. Packet booleans serialise as `"Yes"` /
  `"No"` with `None` omitted; `confirmation_text` hint rows carry page text, not field keys;
  F-1/OPT/CPT synonyms precede generic sponsorship in `SYNONYMS`.
- **Why:** Phase 4's deterministic filler needs a stable packet and per-ATS selector map
  before any CDP runner exists; free-text leftovers reuse `coverletter.check_claims` rather
  than a new guard.
- **Tradeoff:** `build_packet` reads optional artifacts only — missing cover/skills never fail
  assembly; guard failures return `answer=""` instead of raising.
- **Follow-up:** Wire `write_packet` into `web/jobs.py` on success, add API/MCP routes per
  plan Phase 1 todos `p1-packet` / `p1-answer`.

## 2026-09-21 — Apply Phase 2: store and sources

- **Decision:** Added `apply/store.py` (`applications.json` keyed by `source_job_id`, atomic
  `.json.tmp` writes) and `apply/sources.py` (SimplifyJobs README parse/filter ported from
  the internship-tracker script). `ApplySettings` nests on `JobSettings` with
  `exclude_citizenship_required` mapped to `filter_rows(..., exclude_citizenship=...)`.
- **Why:** Discovery needs a durable funnel registry and deterministic README ingestion
  before orchestration or the UI can schedule daily runs.
- **Tradeoff:** `set_status` blocks terminal → pre-ready transitions only (not terminal →
  `ready`/`filling`); `FillResult` is a stub until Phase 4. Rows without a Simplify job id
  are dropped at dedupe time.
- **Follow-up:** Wire store upserts into the discover job; expose apply settings in the SPA.

## 2026-09-21 — Apply Phase 4–5: filler, fill, daily pipeline

- **Decision:** Added packaged `filler.js` / `filler_readiness.js`, `apply/fill.py` (CDP
  runner with `decide_submit_action` policy A/B), `apply/daily.py` (discover → fetch →
  screen → reuse or queue tailor), and `scripts/apply_daily.py`. `FillResult.filled` /
  `leftovers` are now `list[Any]` for structured dict rows.
- **Why:** Deterministic fill must stay in injected JS; Python only orchestrates packet
  fields, guarded long-text answers, submit policy, and persistence. Daily holds
  `template_ops.LOCK` only around `get_queue().submit`.
- **Tradeoff:** `run_daily` skips when `apply.enabled` is false unless the caller passes an
  explicit `ApplySettings` (CLI forces `enabled=True`). Reuse links `job_id` to the prior
  run rather than copying artifacts. Fill iterates all Playwright frames — cross-origin
  frames increment `frames_skipped`.
- **Follow-up:** Browser-marked integration test against `tests/fixtures/forms/greenhouse.html`;
  wire scheduled `run_daily` from the SPA when apply is enabled.

## 2026-09-21 — Apply funnel SPA and docs close-out

- **Decision:** Added `/applications` SPA page (queue table, CDP status pill, packet
  drawer, applicant-profile editor), nav link **Apply**, README Automation section
  (Chrome CDP launch flags + `scripts/apply_daily.py`), CLAUDE.md Application
  automation section (fourteen path globals, `"answer"` purpose), and Cowork fallback
  skill at `docs/skills/apply-from-queue/SKILL.md`. Autouse fixture isolates
  `APPLICATIONS_PATH` / `APPLICANT_PROFILE_PATH` / `APPLICATIONS_OUTPUT_DIR`.
- **Why:** Policy A (review-all) needs a review queue in the UI; host Chrome over CDP
  keeps Docker as the only long-running process.
- **Tradeoff:** Profile editor on the Apply page is a short field list; full EEO/custom
  answers still edit via JSON or PUT API. `auto_submit_ats` starts empty.
- **Follow-up:** After a week of clean Greenhouse fills, add `"greenhouse"` to
  `apply.auto_submit_ats`; expand synonym table from leftovers logs.

## 2026-09-21 — Apply funnel HTTP API, MCP, and scheduler

- **Decision:** Added `/api/applicant-profile`, job packet/answer routes, applications CRUD
  (list/get/status/retry/fill/export/run-daily), optional `job_id` on verify-claim, MCP
  mirrors (`get_application_packet`, `answer_application_question`, `list_applications`,
  `get_application`, `mark_application`), `packet_json` artifact kind, and a 60s lifespan
  daemon that fires `run_daily` once per local day at `settings.apply.schedule_time`.
- **Why:** Agents and the SPA need the same apply surface as tailoring without a second
  pipeline; scheduler matches the CLI's scheduled discover intent while staying
  non-blocking on shutdown (`join(timeout=2)`).
- **Tradeoff:** `POST .../fill` returns immediately after starting the async CDP worker;
  `GET .../fill` reads persisted `FillResult`. Retry only covers fetch-JD and tailor-failed
  paths. Scheduled daily uses process-local `_last_daily_run_date` (resets on restart).
- **Spec delta:** Extends Phase 4–5 orchestration with read/write HTTP + MCP.

## 2026-09-21 — Multi-source discovery, ATS dedupe, bachelor-only eligibility

- **Decision / change:** Extended the apply funnel with (A) `age_days` + multi-`SourceConfig`
  defaults (Simplify internships, New-Grad-Positions, speedyapply), (B) `identity.py`
  canonical/group keys and schema-v2 `applications.json` keyed by ATS requisition,
  (C) `eligibility.py` bachelor-rescue prefilter before `extract_consensus`, (D) depth-aware
  pipe-table parser + `--list-sections`, (E) ETag README cache + Greenhouse/Lever/SR/Ashby
  JSON JD fetch, (F) SPA badges for sources/group size/salary/flags.
- **Why:** Cut LLM spend by filtering/deduping on plain text and ATS identity; cover
  internship + new-grad without inventing content; hard-reject advanced-degree-only posts
  while keeping inclusive "Bachelor's, Master's, or PhD" wording.
- **Tradeoffs:** Regex eligibility will need tuning from `screened_out` notes; Workday
  still needs CDP; zapply skipped (noisy). Canonical fallback is `other:{host}:{sha1[:12]}`.
- **Spec delta:** Extends the single-Simplify apply funnel from the earlier Automation work.
- **Follow-up:** Confirm live speedyapply section names with `--list-sections` if headings
  drift; tune `EligibilitySettings.hard_reject_years` after a week of notes.

## 2026-09-21 — Docker CDP Host header vs Chrome DevTools

- **Decision:** `apply/browser.effective_cdp_url` resolves `host.docker.internal` to an
  IP before `/json/version` probes and Playwright `connect_over_cdp`.
- **Why:** Chrome DevTools returns HTTP 500 when `Host` is a non-localhost hostname
  ("Host header is specified and is not an IP address or localhost"). That made the
  Apply page show CDP offline even with Chrome correctly launched on the host.
- **Tradeoff:** Relies on `gethostbyname` for the gateway; fine on Docker Desktop.
- **Follow-up:** Rebuild the app image so the container picks up the fix (`src/` is not bind-mounted).

## 2026-09-21 — Live daily-run progress on the Apply page

- **Decision:** `run_daily` publishes a `DailyProgress` snapshot (`phase`,
  `source_id`, `current`, `processed`/`total`, `dry_run`, live `summary`) guarded by a
  dedicated `_PROGRESS_LOCK`; `GET /api/applications/daily-status` returns a deep copy,
  and `POST /api/applications/run-daily` now accepts `{limit, dry_run}` mirroring
  `scripts/apply_daily.py`. The Apply page polls every 2s, shows phase + progress bar +
  counters, and gains Dry-run/Limit controls next to the button.
- **Why:** "Run daily now" previously gave no feedback — the run is a bare daemon thread,
  and a `--dry-run` CLI pass (the user's first test) writes nothing, so the empty queue
  looked like a broken button.
- **Tradeoffs:** Polling (user-chosen over SSE) costs one cheap JSON request per 2s; the
  progress bar is indeterminate during discovery because the row count is unknown until
  every source has been fetched. `daily_status.running` is derived from `_DAILY_LOCK`,
  not a stored flag, so a crashed run can't wedge the UI into "running".
- **Spec delta:** Manual "Run daily now" now ignores `apply.enabled` (passes the profile's
  apply settings explicitly), matching the CLI; that flag still gates only the nightly
  scheduler. `/api/applications/daily-status` is declared before the
  `/{source_job_id}` route — route order matters in Starlette.
- **Follow-up:** A Stop/cancel control was considered and deferred; killing a run
  mid-tailor would leave `JobQueue` jobs orphaned.

## 2026-09-21 — Recommend Edge, not Chrome, for the apply-automation debug profile

- **Decision:** Docs (`README.md`, `CLAUDE.md`) and in-app copy
  (`ApplicationsPage.tsx`'s pill/instructions, `docker-compose.yml`/`requirements.txt`
  comments, docstrings in `apply/browser.py`/`fill.py`/`__init__.py`/`fetch_jd.py`,
  `config.py`) now recommend launching **Microsoft Edge** with
  `--remote-debugging-port=9222` instead of Chrome. `CHROME_CDP_URL`'s name is
  unchanged — it has no `.env.example` entry, so there was nothing to migrate, and the
  value was always browser-agnostic (Playwright's CDP connection and the
  `/json/version` probe never inspected which browser answered).
- **Why:** Live-diagnosed this session: Chrome refuses to open its remote-debugging
  port whenever *any* other Chrome window — any profile — is already running under the
  same account (confirmed directly: Chrome running, port 9222 never bound, no second
  Chrome process anywhere). For a user whose daily browser is Chrome, that meant fully
  quitting Chrome every time before using the apply feature. Edge is a separate
  binary/process, so it isn't subject to Chrome's singleton-while-debugging check and
  can run the automation profile in the background indefinitely without touching normal
  Chrome browsing.
- **Tradeoff:** If a user's daily browser is Edge instead of Chrome, the identical
  restriction applies there — this swaps which browser needs to stay free, it doesn't
  eliminate the underlying restriction. The dedicated profile directory also had to move
  (`%LOCALAPPDATA%\ResumeTailorEdge`, was `...\ResumeTailorChrome`) since Edge and Chrome
  profile directories aren't interchangeable.
- **Follow-up:** None of `browser.py`/`fill.py`'s runtime logic changed — only
  docstrings/error-message wording — so this shipped with zero test changes required.

## 2026-09-21 — Pin the apply funnel's own LLM calls to a configurable model

- **Decision:** Added `ApplySettings.model_provider`/`model_name` (default
  `ollama`/`nemotron-3-super:cloud`, exposed via a provider dropdown + model-name field
  on the Applications page, mirroring `RunPage.tsx`'s Tailor model control) and a
  `model_spec` property building the `provider:model` string `config.pinned()` expects.
  `daily.py::_process_one` now wraps its `jd.extract_consensus` call, and
  `fill.py::fill_application` wraps its `answer.answer_question` call, each in
  `with config.pinned(settings.model_spec):`.
- **Why:** A fresh test run's first two postings failed with a real Anthropic billing
  error even though this workspace's Tailor model is `ollama`. Root cause:
  `daily.py`/`fill.py` call `jd.extract_consensus`/`answer.answer_question` directly,
  outside `web/jobs.py`'s job queue — the only place `config.resolve()` runs. Per
  `config.backend_for()`'s documented fallback, an empty `_ACTIVE` (true on every cold
  process, before the first tailor job) silently resolves to `resolve("claude")`,
  regardless of the saved model setting. Also fixed in the same pass: two `_process_one`
  branches (`no application link`, an `extract_consensus` exception) updated
  `status_history` but never called `_append_log`, so a failing posting just vanished
  from the visible daily log instead of showing why.
- **Tradeoff:** Deliberately narrow scope — this setting governs only the funnel's own
  pre-tailor screening extraction and free-text answer drafting. The actual
  resume-tailoring stage the funnel submits via `get_queue().submit(...)` keeps using
  the workspace's existing Tailor model settings unchanged, since that path already
  resolves correctly through the job queue.
- **Follow-up:** `test_daily_status_reflects_progress` had to gain a `time.sleep(0.2)`
  inside its own stubbed `fetch_jd.fetch_jd` — once `extract_consensus` was properly
  stubbed (it wasn't before, and silently made a real, slow, un-hermetic Ollama call
  under the old fallback-to-Claude-then-fail-fast behavior), the whole run finished
  faster than the test's 0.1s poll interval could reliably observe an in-flight phase.

## 2026-09-23 — Apply became a three-stage, observable operation workflow

- **What:** Split the Apply controls into **Find jobs**, **Prepare selected**, and **Fill
  selected**. Added persistent operation records with live stage, current application,
  counts, event history, cancel, and blocker pause/resume/skip controls. Selection is
  explicit and action buttons count only eligible selected rows.
- **Submission policy:** Added an independent auto-submit switch and blocker behavior.
  Verified forms submit only when the switch is enabled, the ATS is allowed, and the
  per-operation cap remains; Workday follows the same rule. Attachment inputs are matched
  by purpose and verified from the browser's retained filename before a form is ready.
- **Reliability:** Dropdown fill ignores blank placeholder options, checkbox/radio changes
  are idempotent, submission success requires new post-click evidence, and fill results
  expose missing fields plus upload outcomes. Hybrid resolution can no longer issue
  arbitrary clicks and never receives Workday credentials.
- **Model scope and privacy:** The Apply model now governs extraction, tailoring, answers,
  and hybrid resolution. Applicant-profile responses redact stored Workday passwords;
  saving a response with a blank password preserves the stored value.

## 2026-09-23 — Greenhouse attachment names, cover detection, and fill checkpoints

- **Observed:** National Life job `4410899009` completed the full Tailor pipeline and
  produced `tailored.docx/.pdf` plus `cover.docx/.pdf`, but the ATS saw the internal
  `tailored.pdf` filename and the proactive cover lookup missed Greenhouse controls
  identified by `name="job_application[cover_letter]"`. The operation's last event stayed
  at one broad `navigating` message, obscuring which browser wait had stalled.
- **Fix:** Stage copies under descriptive applicant/role filenames before upload, detect
  resume and cover inputs by both `id` and `name`, verify the staged filename retained by
  the browser, and emit checkpoints for browser connection, posting load, form discovery,
  each form step, each upload, screenshot capture, and readiness verification. Initial
  navigation now bounds network-idle waiting instead of treating it as a required state.

## 2026-09-23 — Semi-automated Apply handoff and observed upload behavior

- **Workflow:** Fill selected processes prepared applications sequentially and hands each
  browser tab to the user while continuing the batch. Review tab, Continue fill, and
  explicit Reopen and fill use persisted CDP target IDs; Continue preserves existing
  answers and attached files. Workday OTP is completed in its tab and no longer blocks
  the batch worker. Interrupted fills return to a retryable status after restart.
- **Field safety:** Phone calling code and address country are separate packet fields.
  Native selects require a unique exact or declared alias match; country-specific +1
  choices require an explicit phone region. Custom combobox actions must refer to
  observed options and verify a selected value. Optional blanks and unsupported facts
  remain visible for manual review.
- **Live evidence:** National Life Greenhouse removes each file input after upload and
  displays the filename in the form. Input-only verification falsely reported failures
  and retried through duplicate selectors. The updated verifier accepts the displayed
  retained filename; a fill-only acceptance pass confirmed both resume and cover letter
  visible in the same tab. That form's phone country menu offers multiple +1 countries,
  so the blank phone-region profile field appropriately leaves it for review. The saved
  Booz Allen Workday posting currently displays a page-not-found message, preventing a
  live authentication check; no account action or submission took place.

## 2026-09-23 — Apply verified-engine migration, still gated

The replacement async scanner, matcher, executor, and Greenhouse row adapter are staged
behind `APPLY_FILL_ENGINE=verified`; the default remains the established legacy filler.
Preparation now records source employment count with expansion output, and Fill uses one
captured profile/settings snapshot per batch. Review refresh recognizes Greenhouse's
filename display after a successful upload, preserves completed-step evidence, and
supports stale-checked explicit corrections. The default Workday authentication path
requires visible success evidence and leaves unchecked account terms for the applicant.

Offline checks: 1,047 Python tests, 98 frontend tests, typecheck, lint, and production
build passed. The browser suite passed seven tests using local Edge.
Read-only inspection of the open National Life form confirmed committed education and
demographic controls plus retained resume and cover-letter displays. A Charter Workday
acceptance tab reached Create Account and returned `terms_needed` with the terms unchecked;
no account was created and no application was submitted. Remaining migration gates include
the async Workday adapter, conditional form rescans, submission parity, and a fresh
end-to-end Fill acceptance run before changing the engine default.

## 2026-09-23 — Apply page and API made to agree (audit follow-up)

A whole-codebase audit found the Applications page and the backend disagreeing about
statuses, retries, and which routes exist. All of it passed the suite, so each fix below
comes with a regression test.

- **Terminal statuses have one definition.** `store.TERMINAL_STATUSES` is public and
  used by `preparation.check` and `daily.prepare_application` (both had their own copies).
  The SPA had a fourth copy missing `interview`/`ghosted`/`skipped`, so those rows showed
  "Prepare again" and were counted into bulk Prepare, then failed server-side. The SPA
  now reads the server's `terminal_application` preparation reason
  (`lib/applicationRows.isTerminalRow`) instead of keeping a list, and no longer shows the
  "Needs Prepare" hint on terminal rows.
- **Bulk Fill stays `ready`-only on purpose** (so a test batch never fills every row);
  documented beside both `FILLABLE_STATUSES` and `preparation._FILLABLE`.
- **Retry is server-driven.** `daily.retry_kind(app)` is the single definition of
  "retryable" (`fetch` / `prefilter` / `tailor` / None); `ApplicationOut.retry_kind`
  carries it, and the SPA shows one button labelled by what it does. Previously a
  screen-rejected `screened_out` row offered Retry and got a 409, and "Fetch JD" claimed
  to screen. The retry route now 409s while an Apply operation or daily pass owns the
  browser, and the button is disabled while an operation runs.
- **Tailor retry no longer blocks a request for up to an hour.** It queues the job and
  returns at `tailoring`; a daemon thread records `ready` / `tailor_failed`, re-reading the
  row first and doing nothing if it moved on. The page's existing poll also refreshes the
  table while any visible row is `tailoring`.
- **Retired routes:** `POST /api/applications/{id}/otp` (nothing ever called
  `otp_bus.request_otp` since Workday switched to handoff), `POST`/`GET
  /api/applications/{id}/fill`, and `POST /api/applications/run-daily` — superseded by
  Apply operations; neither the SPA nor MCP called them. Removed with them: `otp_bus.py`,
  `fill.start_fill_async` / `get_fill_result` / `fill_busy` / `FillBusyError` / `_progress`
  (`fill_busy` was only ever set by `start_fill_async`), `daily.try_start_daily`, and their
  `api.ts` helpers. `Application.otp_prompt` stays so existing rows load.
- **Resuming a paused Fill reuses the retained tab.** The worker re-called
  `fill_application` with the batch's original `fill_mode` (usually `initial`), which opened
  a new tab and discarded what the user had just done there; it now continues with
  `continue`. `needs_input` is decremented on resume too, and the per-application budget
  restarts. Idempotent correction operations are capped at the 200 most recent.
- **Guard-failed answers are not cached.** The sync `answer_question` wrote an empty
  answer to the cache after two guard failures, pinning that question to `""` until a
  prompt-version bump; it now matches the async path. The two paths' length policies
  differ on purpose (sync trims at a sentence for copy-paste; async rejects rather than
  truncate into a live form field) and are documented as such.
- **Smaller:** the `propose` stage has its own progress band and label; template remap
  overrides are typed to the five heading kinds (422 on anything else);
  `config.apply_fill_engine()` owns the `APPLY_FILL_ENGINE` read; `.env.example` documents
  `CHROME_CDP_URL`, `APPLY_FILL_ENGINE`, the remaining `LLM_EFFORT_*` and
  `LLM_EXTRACT_CONSENSUS_RUNS`; CLAUDE.md lists the apply modules that call the LLM.
- **Dependencies:** test/lint tools moved to `requirements-dev.txt` (runtime-only
  `requirements.txt` is what Docker installs). `uv.lock` and the two identical scratch
  files `_sources_full.py` / `_src_sources_ascii.py` were deleted.

Checks: 1,062 Python tests passed (1 skipped); 102 frontend tests across 13 files,
typecheck, lint (18 warnings, down from 19), and production build passed. Live check
against a temp copy of the data: each seeded status showed the right button (or none),
bulk Prepare counted 0 for a selected skipped row, a tailor retry returned in about 1.6s
and the row settled on its own, and the retired routes returned 404/405. Known leftover:
`test_extract_consensus_pinned_to_apply_settings_model` reads the real
`data/master_resume.json` and fails under the empty-data-dir hermetic run.

## 2026-09-23 — Workday JD fetching, and a canonical-key bug it exposed

Two symptoms on the Applications page: every ATS-"workday" row was stuck at "Browser
needed", and other `myworkdayjobs.com` rows sat at "discovered" showing ATS "unknown".

- **Workday now has a JSON feed**, like the existing Greenhouse/Lever/SmartRecruiters/Ashby
  ones. `ats_api.workday_posting_text` hits `/wday/cxs/<tenant>/<path>` (dropping a leading
  locale segment such as `en-US`) and reads `jobPostingInfo.jobDescription`.
  `fetch_jd.fetch_jd` tries it before the HTTP/CDP fallback, which is why the ATS-detected
  rows were failing: the HTTP download only ever got Workday's empty JS shell, and the CDP
  browser read the page before the description had loaded — now polled for up to 10s.
- **Fixed a Workday canonical-key bug found while checking the fetch.** `identity.canonical_key`
  matched the first letters-plus-year pattern anywhere in the path, so
  `…Intern-2027_R39474` became `workday:amfam:ERN-2027` and `…Summer-2027…` became
  `MER-2027` for *every* company — a live collision risk, since the registry is keyed by
  canonical key. It now takes the id after the URL's final `_`. `store.SCHEMA_VERSION` is
  now 3; `_migrate_v2` re-keys existing Workday rows (rewriting any `duplicate_of` that
  pointed at the old key, and never colliding two rows into one), backfills `Application.ats`
  for rows still at "unknown", and backs the file up once before rewriting it.
- **`_application_from_row` now sets `ats` at discovery**, not just after the first fetch —
  that's why freshly-discovered Workday rows showed "unknown".
- **The fetch retry now uses the same 100-character floor as the nightly run**
  (`daily._MIN_USABLE_JD_CHARS`), so a retry can't move a row to `jd_fetched` with a scrap
  of text the nightly run would have rejected.

Checks: full suite green (1,083 passed, 1 skipped — 25 new tests over the prior 1,058);
the two `test_web.py` skills-download failures are pre-existing and reproduce on
unmodified `main`, unrelated to this change. Verified the canonical-key fix and the
Workday JSON feed against seven real posting URLs (CAI, AmFam, MFS, GEHC, Fidelity,
Nebraska Medicine, GM) without touching `data/`.

## 2026-09-23 (later) — the Workday fix above lost most of the JD text

Watching a live "Prepare selected" run on the CAI posting from the entry above surfaced
two more bugs, one in that fix and one pre-existing:

- **`extract_text`'s "largest block only" heuristic doesn't belong on an ATS feed's
  JD-only HTML field.** It exists so an HTTP page download can throw away nav/footer
  chrome; reused on Greenhouse's `content`, Ashby's `descriptionHtml`, and the new
  Workday `jobDescription` (all three are the JD and nothing else already), a single
  outsized paragraph — an EEO/boilerplate block is a common case — ate the whole
  extraction. CAI: 6,886 real characters became a 957-character EEO paragraph, and the
  row went on to `tailoring` against that alone. Added `extract_fragment_text` (join
  every block, keep nothing back) and moved the three feed call sites onto it;
  `extract_text` keeps the largest-block heuristic for its one real caller, the raw
  HTTP page download.
- **A successful fetch never cleared `Application.error`.** `_process_one`'s
  `needs_browser` branch never set `app.error` itself (only `retry_application`'s
  fetch branch did, and it already cleared it on success) — but a row that had been
  through a failed retry before a later `_process_one` fetch succeeded kept showing
  the retry's stale error message on the Applications page indefinitely. Now cleared
  the moment a fetch succeeds, right before `jd_fetched`.
- **No progress during the tailor wait.** `_process_one`'s `log` callback (which
  `operations.py` turns into the Applications page's "Last activity" line) only fires
  on each step's *terminal* outcome (`[needs_browser]`, `[tailor_failed]`, `[ready]`,
  …), never mid-step — so the entire tailor call (extract → score → facets → rewrite →
  render, one `_wait_for_job` poll loop) showed one static message the whole time. The
  tailor job already emits `ProgressEvent`s for exactly this (the Tailor tab's own SSE
  stream reads them); `_wait_for_job` now takes an `on_progress` callback and relays
  `job.events[-1].message` each time it changes, so "Prepare selected" surfaces the
  same stage names as a normal Tailor run instead of going dark for minutes.
- **Not a bug, but worth recording:** a `tailoring` row left behind by a server
  restart mid-run has no dedicated recovery, but does not need one — `prepare_application`
  resets any non-terminal status back to `discovered` before re-running the funnel, so
  selecting the row again and clicking "Prepare selected" self-heals it. Checked this
  is genuinely true rather than assumed.

Checks: full suite green (1,088 passed, 1 skipped — 2 new tests over the prior 1,083).
Rebuilt and restarted the Docker image (`src/` is baked in, not bind-mounted, so a
plain container restart does not pick up a source change) and re-verified the CAI
fetch inside the running container end to end: `fetch_jd.fetch_jd` returns
`method="api"`, 6,886 characters, both the responsibilities section and the EEO
paragraph present. Did not touch the real `applications.json`; a direct edit to reset
the stuck CAI row's status was denied by the harness's own "modify shared resources"
guard, so that row still needs the user to click "Prepare selected" on it themselves.

## 2026-09-23 (evening) — Prepare now tailors with the Tailor tab's model settings

"Prepare selected" was taking 20+ minutes a posting while a Tailor-tab run took under a
minute. The cause was model routing, not the pipeline: `daily._job_settings` overwrote every
model field on the submitted tailor job with the Apply page's picker
(`ApplySettings.model_spec`, `ollama:nemotron-3-super:cloud` — a reasoning model, ~80s per
call and more fabrication retries), clearing `model_name` and every per-stage override. The
Tailor tab was running `ollama:gemma4:cloud`. Yesterday's Prepare runs on gemma4 took 38–105s.

- **Routing.** The job runner's `JobSettings` → `(profile, overrides, effort)` block moved out
  of `JobQueue._execute` into `web.jobs.model_routing`. `_job_settings` no longer touches model
  fields, and `_process_one`'s screening `jd.extract_consensus` is pinned with the same routing
  through `config.pinned(profile, overrides=..., effort=...)`; `pinned` gained the `overrides`
  keyword for this. This reverses the earlier "Apply model is authoritative for every Apply
  call" design at the user's request.
- **The Apply picker stays, renamed "Autofill model".** It still drives Fill's
  `answer`/`model_resolver`/`hybrid_resolver` calls (`fill.py`, `engine.py` keep
  `config.pinned(settings.model_spec)`). Next to it, the page shows a read-only
  "Tailoring: <profile> · <model> (Tailor tab)" line (`frontend/src/lib/modelLabel.ts`,
  shared with RunPage's placeholder). The operation's `effective_model` now names the Tailor
  routing for Find/Prepare (`web.jobs.model_label`) and the autofill model for Fill.
- **The fourth JD read is gone.** Screening called `extract_consensus` with the default
  `runs=1` (cache file `<slug>.requirements.json`) on different routing, so the tailor job's
  `runs=extract_runs` lookup (`<slug>-consensus3…`, a different `fingerprint("extract")`) always
  missed and read the JD three more times. Screening now passes
  `runs=job_defaults.extract_runs` and `use_cache=not no_cache` with the same routing, so the
  tailor job reuses it. That's 3 JD reads per posting instead of 4.

## 2026-09-23 (night) — years-of-experience false positive, and stuck "tailoring" rows

- **Symptom.** CAI's Data Analyst Intern (Workday R8551) failed Prepare with
  `requires_40_years`. The phrase was company history ("over 40 years of excellence"), newly
  visible because the full-JD fix above keeps the "Who we are" paragraph.
- **`eligibility.min_required_years` is stricter.** A match counts only when "experience"/"exp"
  follows within 40 characters (`_EXPERIENCE_AFTER`), and numbers over
  `MAX_PLAUSIBLE_YEARS = 5` are ignored. The user chose 5 because every source is an intern or
  new-grad board, so a larger floor is a misparse. `check_text` takes `role=`: an
  intern / new-grad / entry / student title downgrades a years floor from a hard reject to a
  `years_N` flag. Both daily callers pass `app.role`.
- **A failed "Prepare again" no longer resurrects an orphaned row.** `prepare_application` used to
  restore `previous` on any failure, and here `previous` was a `tailoring` row whose job died
  with a container restart. So the row showed "tailoring" (plus a stale fetch error) forever.
  `_settle_failed_prepare` now restores `previous` only when it had a packet (status outside
  `store.PRE_READY_STATUSES`, which went public for this). Otherwise it keeps the new outcome,
  e.g. `screened_out` with its reasons. An exception mid-tailor moves `tailoring` to
  `tailor_failed` and records the error.
- **Startup recovery.** Tailor jobs are in-memory, so `lifespan` calls
  `daily.recover_orphaned_tailoring()`: any `tailoring` row whose `job_id` the queue doesn't
  know becomes `tailor_failed` ("interrupted by a server restart"), which gets a Retry button.
  It checks the queue rather than "no active operation", because a per-row tailor retry runs
  outside any operation.

## 2026-09-23 (late night) — Workday autofill rebuilt on observed screens

Workday fills always ended in "1 need input" with nothing filled. Evidence from the live CAI
tenant (read-only CDP dumps plus an isolated signed-out context): every attempt stopped at
`handle_workday_auth` → `failed` within ~4 s, because its "logged in" selectors
(`legalNameSection_firstName`, `applicationForm`, `signOut`, ...) no longer exist; auth submit
buttons are covered by a `click_filter` overlay that swallows direct clicks; the Apply control
is a link opening a Start dialog; and form hints/repeater selectors used the same stale names.

- **`workday_flow.py`** — screen state machine from visible automation ids (pure `classify`,
  fixtures captured live); `wait_for_state` / `wait_for_step_ready` (stable marker set, since
  Workday renders Country first, applies a locale default — Vietnam here — then the rest) /
  `wait_for_step_change` after Save and Continue. Only Apply / Continue Application / Apply
  Manually are clicked — never "Autofill with Resume" or "Use My Last Application".
- **Auth** — existing session wins; unknown tenant creates an account; vault `created` marks a
  tool-made account; "already exists" with an unknown password is a handoff
  (`sign_in_failed`), never a retry. Readable `AUTH_HANDOFF` texts replace bare codes.
- **Fields** — `filler.js` only sees input/select/textarea, so Workday listbox buttons get a
  deterministic pass (`select_listbox`: one evaluate for ~250 options, verified by polling the
  button text — Workday repaints it after ~300 ms, which is also why `hybrid_resolver`'s own
  check now polls). Radios come from their legend question; "ever employed by <company>" is
  answered from the resume's employers. The resolver now reads a Workday field's label/legend
  instead of the button's aria-label ("Select One Required"), which previously left the
  model answering questions it could not see. "Phone Extension" no longer matches `phone`.
- **My Experience** — rows are `workExperience-N--*` / `education-N--*`; dates are 0-px
  spinbuttons typed via their display divs; prompts (Field of Study) commit a chip; a row an
  earlier run started is completed rather than duplicated. Resume upload is skipped when the
  filename is already listed (Workday's input empties after each upload, so every rerun was
  attaching another copy). File inputs fall back to the section heading ("Resume/CV").
- **Auto-submit** — `schemas.py` documented Workday as excluded but the code allowed it; the
  guard now exists in `decide_submit_action` (the test that asserted the opposite was flipped).
- Verified live on CAI via the Apply API: posting → draft resume → My Information → My
  Experience (resume, 5 jobs, education) → Application Questions → Voluntary Disclosures,
  stopping only at the required terms-consent checkbox. Several tabs on one draft produced
  Workday's "Something went wrong" (VPS) page; fill now reloads once, then hands over.
- **Follow-up (AmFam, same night).** Some tenants open the Create Account/Sign In step with a
  chooser (Google / LinkedIn / "Sign in with email", `SignInWithEmailButton`) and no password
  field, and every tenant paints that step's progress bar before its form — which
  `classify` read as `apply_form`, so auth was skipped and Fill failed with "no controls".
  Now: `auth_chooser` is its own state (auth clicks email only, never a third-party login),
  and an apply shell whose active step is Create Account/Sign In (or shows `signInContent`)
  is `unknown` until its form renders. AmFam's Sign In overlay is labelled "Submit", not
  "Sign In", so `click_control` finds the `click_filter` by `elementFromPoint` at the
  button's centre; the label match remains only as a fallback.

## 2026-09-24 — Workday Sign In never clicked; two false prepare failures

The first batch run after the Workday rebuild left AmFam, Capital Group and CAI on the Sign In
form, filled but never submitted, each handed over as "the saved password was not accepted";
and the Prepare operation reported 3 failures when only one row had genuinely stopped.

- **Sign In click race.** Live inspection (CDP, read-only) showed the `click_filter` overlay
  holds the only click listener; the real `<button type=submit>` has none. The run filled and
  clicked in the same second the form appeared, before the overlay painted, so
  `click_control` fell back to the bare button — a silent no-op — and auth waited 20s and
  blamed the password. Zoom/DPR/smooth-scroll offsets were ruled out. Now
  `wait_for_auth_form_ready` waits for inputs + submit + a stable overlay (a tenant with no
  overlay is accepted after 2s), `click_control(expect_overlay=True)` keeps looking for it
  briefly, and `_submit` verifies a reaction (screen, URL, alert, loading marker, or an
  outgoing POST). An ignored click is retried once; a click that sent a request never is —
  AmFam's real rejection took ~20s, and the first version of the retry double-submitted a
  wrong password. Focus-ring and overlay-appearing changes are not counted as a reaction.
  No error on screen now yields `no_response`; `sign_in_failed` needs Workday's own message.
- **Verified live:** Capital Group and CAI signed in through the overlay (`overlay-point`).
  AmFam's click now reaches Workday, which answers "wrong email address or password or your
  account might be locked" — the profile's Workday password is not AmFam's.
- **Also found on Capital Group:** "How Did You Hear About Us?" is a hierarchical prompt on
  My Information that nothing filled (`fill_prompts` now does, from `how_heard`; a leaf listed
  under two categories is one answer, and committed chips such as the phone code's are
  excluded from the options). `select_listbox` read `aria-controls` once right after the
  click, but Workday sets it only once the list opens — re-read while polling (My
  Information's State had worked by timing luck). Capital Group's My Experience has no Work
  Experience or Education section; rows are now skipped, not flagged, when the section is
  absent.
- **Degree prefilter:** "seeking a baccalaureate, masters, or doctoral degree" was rejected as
  advanced-degree-only; `_BACHELOR` now knows baccalaureate, associate's, four-year and
  college/university degree.
- **Re-prepare status:** a successful Prepare again restored a stale `fill_failed` (from before
  the Workday rebuild) and the operation counted any non-`ready` result as failed. Only a live
  hand-off (`awaiting_review` / `awaiting_otp`) is retained now, and it counts as completed.
- **Open, not changed:** the hybrid resolver answers profile-less yes/no questions itself
  (Capital Group: work authorization "Yes", criminal history and FINRA "No"). That is
  pre-existing behaviour on every ATS; the tab still stops for review before any submit.

- **2026-09-24 UI redesign:** Shared semantic surfaces now use warm neutral/teal tokens and IBM Plex Sans. Tailor settings collapse behind an always-visible summary. Apply has independently queried working and archived tables (each with URL search/filter/sort/page state, current-page selection, top/bottom pagination, compact mobile cards, one primary action plus an overflow menu). Application details have their own route with saved overview, documents, application content, and form review; viewing does not launch generation. The Profile area separates resume contact from explicit application overrides and keeps their saves separate. Vocabulary uses tabs, with additions kept mounted so a pending debounce survives tab changes. Template preview leads, with metadata in Details. The backend adds an optional `archived_at` field, a batch archive/restore endpoint, scoped listing/search/sort, and archive exclusion at preparation, Fill, retry, daily selection, and rediscovery. Status/history/files are preserved across archive/restore. No tailoring or form automation algorithms changed.
- **Autosave safety:** Tailor settings and vocabulary additions now have provider-owned unsaved/saving/saved/failed state and retry actions. Their pending writes survive page navigation. Profile activation through either the selector or manager flushes both drafts before switching; a failure offers Retry, Stay, or Discard. Hard reload warns while manual drafts or autosaves are unresolved. Serialized writes prevent a slower earlier save from overwriting a newer edit.
- **Resume editing navigation:** The Profile resume editor now has a desktop section index, a mobile section picker, and a collapsed import action. Section order and entry IDs remain unchanged.
- **Tailor results:** The result area now exposes URL-backed Overview, Documents, and Application content tabs; changing the active run returns to Overview. Skills and experience content remain available when a run has no report.

## 2026-09-24 — Submitted applications auto-archive (registry schema v4)
- `store.set_status` sets `archived_at` on the transition *into* `submitted` (not on a
  same-status note, so a row the user restored stays restored). Every status write goes
  through `set_status`, so fill, engine, daily, operations, and the web route all get it.
  `submit_unconfirmed` is deliberately not archived — it still needs the user.
- The schema v3→v4 upgrade (`_migrate_v3`) archives existing submitted rows once, using
  the submission's own history timestamp for `archived_at`. It runs only on upgrade, so
  a later restore is not undone. `load_all` now chains v1→v2→v3→v4 instead of returning
  early from each branch.
- Consequence: status changes on an archived row still 409 ("Restore … first"), so
  moving a submitted row to interview/rejected needs a restore first.
- Profile gained `education_start_month`, fed into the packet's profile education row
  (`start`) and matched by `filler.js` on Greenhouse-style `start-year--N` ids only — no
  label synonym, since "start date" already means `earliest_start`.

## 2026-09-24 — Workday Skills, stray file pickers, whole-page retries, account terms

User-reported: Skills never filled; the OS file picker opened on dropdown-heavy steps; a stuck
field made the fill go over the whole page again; Create Account stopped at its terms box.

- **File picker / whole-page retries had one root.** `hybrid_resolver`'s scan matched
  `[data-automation-id*="select"]`, which on Workday also hits `select-files` (upload button),
  `multiSelectContainer` ("0 items selected"), `promptSelectionLabel` and `selectedItemList`
  (live read-only CDP dump, Capital Group My Information). Each "unresolved" control was
  *clicked open* to read its options on every resolver pass (up to 3 passes × 2 attempts per
  stuck step), so the page visibly redid itself and "Select files" raised the picker. Logs had
  "found 3 unresolved controls … applied 0/3" on a step with no dropdowns. Now: only
  `[role=combobox]` / `[aria-haspopup=listbox]`, one per `formField-*`, upload widgets and
  multiselect containers excluded (`*="file"` only as a word part — `profile…` containers hold
  real dropdowns); `_select_combobox_option` refuses upload widgets; a `filechooser` listener
  on the fill tab intercepts any picker. `StepLedger` (per step, per frame) caches options and
  records what was resolved or already asked; post-advance passes use `only_invalid`. Errors
  with no actionable control no longer call the model at all.
- **Skills.** `Packet.skills` (the tailored `skills.json` list) was never used by Fill. New
  `workday_flow.fill_skills`: one search per skill; `field_matcher.match_skill_option` takes
  exact text, else a `Name (ABBR)` option matching on name or abbreviation (keeps `#`/`.`, so
  C# ≠ C); ties and substrings are no match. Leftovers with options go to ONE
  `choose_skill_options` call (user's proposal; guard-rails added: only observed options,
  "same skill, never related" prompt, code rejects anything not offered, one option per skill);
  commit is verified by one new chip. `fill_prompts` no longer touches the Skills prompt.
  The live Skills DOM was not captured (would have meant advancing the user's draft); the
  fixture mirrors the How Did You Hear prompt markup — confirm on the next live Capital Group
  fill.
- **Account terms** (user decision): `createAccountCheckbox` is now ticked (check → label →
  forced click, verified); only an un-tickable box is `terms_needed`. Application consent
  boxes are unchanged (left to the applicant).
- **Extra Chrome tab — not changed.** The backend only drives Edge over CDP and cannot open a
  Chrome tab; no code calls `window.open`. The only same-origin new-tab links are the PDF links
  ("Tailored PDF" in the row menu, View/Download PDF on the detail page), which open
  `127.0.0.1:8000/api/jobs/<id>/preview.pdf` in a new tab. User could not reproduce; awaiting
  their call on whether those links should change.
- **Noticed, not fixed:** AmFam's fill record typed "First Name" into
  `name--legalName--lastNameLocal` and "Last Name" into `…firstNameLocal`.
- **Verified live (Capital Group Charlotte, reopen-and-fill, Docker rebuilt):** Skills prompt
  found on My Experience; 10 skills entered one search each — 7 exact/qualifier matches
  (Python → "Python (Programming Language)", machine learning → "Machine Learning (ML)",
  Pandas → "Pandas (Software)"), one model call for 3 leftovers (Matplotlib → "Python
  Matplotlib"; two course titles correctly null → one review line). Resume upload verified, no
  file picker, no resolver pass on My Experience. Application Questions: one resolver pass
  (5/5), stopped only at the required salary question (reserved for the applicant).
- **Still open (pre-existing):** the resolver answered "Are you currently authorized to work in
  the U.S.?" = No because `authorized_to_work` is blank in the profile (`visa_holder`, F-1 OPT);
  and `FillResult.filled` holds only values `filler.js` can re-read (inputs), so Workday
  listbox/prompt answers — Skills chips included — are absent from the saved record even
  though they are on the form.

## 2026-09-24 — Screened-out reasons, restriction check before extraction, re-check

Audit of the 11 screened-out rows: 6 were genuine work restrictions (citizenship / ITAR
U.S.-person / security clearance) for a `visa_holder` profile, but the stored reason was
the regex source (`blocked by pattern '\bU\.?S\.? citizen'`). The listing feed's
`citizenship_required` was "No" for all of them, so they paid for LLM JD extraction before
a free regex rejected them. 4 were stale rejections from since-fixed rules
(`requires_30_years`, `requires_17_years`, coverage) that nothing ever re-checked, and one
was an "Analytics Intern" rejected because the model labelled seniority `mid`.

- `screen.check_blocks` runs in the prefilter stage (`daily.prefilter_screen`), before
  extraction; default patterns record named reasons and the matching sentence
  (`ScreenResult.evidence`). Sentence splitting ignores single-letter abbreviations
  (`U.S.`), which otherwise cut every quote mid-sentence.
- An early-career title (`eligibility.is_early_career_title`) outranks the model's
  seniority: flag `seniority_mismatch`, never a rejection.
- `screen.screen_label` → `ApplicationOut.screen_label`, shown under the Status pill;
  the detail Overview lists reasons and quoted evidence.
- `retry_kind` is "prefilter" for every screened-out row with saved JD text (was only
  `prefilter:`-noted rows); the re-check uses the stored `screen.seniority`, no LLM.

## 2026-09-24 — Six Apply fixes: Workday sign-up order, salary answers, review table

- **Workday auth keyed on the site, not the password.** A saved profile password sent every
  first visit straight to Sign In; on a site with no account yet (Excellus, `lthc`) Workday
  answered "wrong email or password" and the hand-off wrongly said an account existed. The
  vault's `created`/`signed_in` flags now decide: a new site creates first (creating never
  spends a lockout attempt), "already exists" gets one Sign In with the profile password, then
  `account_exists_other_password`.
- **Salary is answered, deterministically.** The applicant asked for `min(posted top, my top)`
  in the posting's unit (their three cases — below/within/above the range — reduce to that),
  and their top when no pay is posted. Structured min/max fields replace parsing the sentence
  each time; they seed once from it (`mode="before"` validator on absent keys, so a cleared
  range stays cleared). EEO stays reserved; salary never reaches a model.
- **Unlabelled Workday questionnaire textareas.** `labelFor` returned '' for Excellus's
  questions (multi-id `aria-labelledby`, label in the `formField-*` container), so even
  the salary rule never saw them.
- **Preferred-name checkbox.** A lone checkbox is now a yes/no switch (`has_preferred_name`
  emitted only when the preferred name differs from the first name); a tick reports
  `revealed` and the frame is scanned once more — the Greenhouse-only reveal rescan, generalised.
- **Applications page.** "Only sorts the current page" was ties: the server always sorted the
  whole list, but 104 Workday rows tie-broken by `canonical_key` read as unsorted. Ties now
  fall back to newest-discovered, and Status sorts in pipeline order. Refresh-on-finish missed
  operations that began and ended between two 2s polls and tailor retries (not operations);
  the poll now compares operation id+state signatures and keeps polling while a row is
  `tailoring`/`filling`. Review rows moved to their own top table with `review_summary`.
  Header profile switcher/Manage/theme became one gear menu (design.md updated; the manager
  dialog is portaled because the header's `backdrop-filter` is a containing block for `fixed`).
- **Live Excellus follow-ups (same day).** (1) "Minimum $18.00 - Maximum $20.00" parsed as two
  singles (answer $18); `_DASH` now allows a "Maximum"/"max"/"up to" word, case-insensitive.
  (2) Once Workday questions had labels, "Indicate any other names under which your school…"
  matched the `school` synonym; text controls with labels over 60 chars no longer use
  short-field synonyms (id hints still apply). (3) Workday's questionnaire textarea showed the
  JS-set "$18/hour" yet validated as empty; `fill._commit_workday_textareas` re-enters textarea
  answers with Playwright `fill` + blur on Workday (text inputs accept the JS value). After
  that the run passed both Application Questions steps and stopped only at the legal consent
  checkbox, which stays the applicant's.

## 2026-09-24 — Preferred name, education year, Workday consent, and email route

- Apply packet assembly now inherits a missing university start date from a unique matching master-resume education row. Explicit profile dates win; ambiguous resume rows do not supply a date. The active default workspace resolves to 2023-09 from its master resume without changing its profile file.
- The legacy filler and verified field catalog identify preferred first name from control identity, explicit label, or local Preferred Name group. Continue fill corrects a preferred field containing the configured legal first name and preserves other entries. Legacy year selects use the year from a YYYY-MM answer. Workday repeaters handle split dates and ordinary year controls; the verified engine also handles Workday's hidden year spinbuttons.
- Shared browser actions select an explicit email sign-in or registration route, with social-only and ambiguous choosers handed to the applicant. Both engines check visible required Workday application consent and accuracy declarations, verify the checked state, and proceed to the Review step. Optional marketing consent is untouched; Workday submission remains manual.
- Focused DOM tests ran in installed Edge. Full suite: 1249 passed, 1 skipped, 18 deselected. The configured local CDP endpoint timed out, so no live Workday draft was resumed during this change.
- Final regression run after the year-select and consent-record adjustments: 1251 passed, 1 skipped, 18 deselected (Starlette deprecation warning only).

## 2026-09-24 (evening) — How-heard "Other", Workday Country/phone code, Epic labels, upload purpose, school search; Review never advanced

- **Workday Review Submit was clicked as "advance" (incident).** Review's footer Submit carries
  the same `pageFooterNextButton` automation id as Next; `_find_advance_button`'s selector
  fallback returned it and a verification fill **submitted the Philips application**
  (`b298f4dc…`, final URL `?Job_Application_ID=ce8f71f8cc62900191ee0e6ac43c0000`, fill.png shows
  "Congratulations! Thank you for applying"). The record still says `awaiting_review`. Pre-existing
  bug, reached for the first time once the earlier steps filled. Fix: the step loop stops on
  `workday_flow.is_review_step` before looking for an advance button, and `_find_advance_button`
  rejects any button whose text/aria reads submit/finish. The verified engine's `advance` already
  matched exact Next/Continue names only.
- **Country "Vietnam" (Live Oak, Upbound).** Not a virtualised listbox as first guessed (all 250
  options render; `select_listbox` corrects it live). The saved value re-appears after the fill, so
  Country is re-checked (`country_mismatch`) just before a step advances and the step is rescanned
  once. A failed correction is a review line.
- **Phone code.** `ensure_phone_code` matched "United States" + "+1" by substring, so "United States
  Minor Outlying Islands (+1)" made it ambiguous; it now uses `_phone_option` (whole region name;
  "united states of america" aliased).
- **Resume upload "Upload a file (5MB max)".** The Workday hint `input[data-automation-id='file-upload-input-ref']`
  never equalled filler's double-quoted selector string. `filler.js` now reports `hint_key`
  (`el.matches`) and `section` ("Resume/CV"); `_attachment_purpose` uses both.
- **Upbound school.** The tenant's control is `education-N--school` (a prompt), not `--schoolName`,
  so no row was found at all; `error1-education-N--school` also shares the suffix. Rows now accept
  either name and only `<kind>-<n>--` prefixes. `select_prompt` searches `field_matcher.search_terms`
  (full name, then campus "Irvine"), picks by `closest_option`, accepts a chip that Enter committed
  itself (Field of Study "Computer Science" → "Computer and Information Science"), and closes a
  single-select list before verifying. Row fields are attempted individually; absent GPA is not a gap.
- **Epic Games.** Labels are bare ancestor text (placeholder "Enter"); names are `questions.*`;
  React Select lacks `role=combobox`; radios are wrapped by `<label>`; education dates are
  `educations[0].start_date.year`. `containerLabel`, name normalisation, React Select detection,
  `optionText`, and an education-date name rule cover them. A long question never takes a
  short-field key; `\bcity\b`/`\bstate\b`/`\bf-?1\b|\bopt\b|\bcpt\b` stop "capacity"/"optionID"
  false matches (the F-1 rule was keying Epic's gender radios).
- **How did you hear.** `fallback_values` tries "Other" after LinkedIn (Workday prompts, native
  selects, React Select); `how_heard_detail` (= profile source) fills a "please specify" field that
  follows it; Greenhouse-style rescans also run after an "Other" pick.
- **Verified live:** Upbound Digital Commerce — Country Vietnam → United States of America, step
  advanced (phone code OK), resume verified; education row (school chip "University of
  California-Irvine", Field of Study, years 2023/2027, degree) filled by the repeater on the live
  tab. Epic — names, email, phone, title, employer, LinkedIn, portfolio, education dates filled;
  resume + cover verified; dropdown questions now carry clean labels. Not yet re-run end-to-end
  after the Review guard and the last label fixes.

## 2026-09-24 (night) — Workday: an unlabelled auth shell read as the form; Sign In first

- **Excellus (`lthc`) filled only the email into Create Account.** Below ~800px wide
  Workday's progress bar drops its step names, and for ~3s after Apply Manually the
  page is just the shell (`applyFlowPage` and `progressBar`, no `signInContent`, no
  label). `classify` called that `apply_form`, so `enter_application` stopped waiting and
  auth said "authenticated" without signing in. `wait_for_step_ready` then spent its 20s
  timeout on a screen with no footer, and filler.js typed the email. Reproduced in
  headless Edge at 768/695px (not at 900px and up). `apply_form` now needs a footer
  (`pageFooter*`) or a `formField-*`; a bare shell is `unknown`.
- **Sign In first (applicant's request).** This reverses the earlier "new site creates
  first" rule. With a vault entry or a profile password, Sign In gets one attempt.
  A rejection on a never-used site goes to Create Account, which answers the question
  the rejection can't: "already exists" means a wrong password, and that is handed
  over with no second attempt. The earlier false "account exists" handoff came from
  treating that first rejection as final. With no profile password, a new site still
  creates first.
- `_submit` stops waiting as soon as the form shows an error. It used to wait out 30s on
  a rejection, which would have made Sign-In-first slow.

## 2026-09-24 (late) — Degree abbreviations answered without the model

- Profile `degree_level` is the bare level ("Bachelors"), so a "BS / BA / MS" list had no
  deterministic answer and went to the resolver LLM. The packet now carries `degree_name`
  ("Bachelor of Science", from the one resume degree at that level; "" when rows disagree),
  tried first by `field_matcher.choice_values` (also the race_detail → race order, replacing
  three inline copies). `match_option(key="degree_level")` falls back to `_match_degree`:
  named degree → same name/abbreviation, else the unique bare-level option; a bare level
  never picks a named degree. "BA/BS" is the level, not BA. `filler.js` mirrors the table
  (`degreeOf`); `fill.py` backfills `degree_name` for packets prepared before it existed.

### 2026-09-24 (late) — Workday "verify your account" is not a wrong password (Jabil)

Jabil's Workday sends a verification link after Create Account and returns to its `/login`
chooser. `_submit` never waited for `auth_chooser`, so the first run sat out the 30s settle
and returned `failed` silently without recording the account. The next run's Sign In got
"Verify your account before you sign in…", which read as a rejection and led to a second
Create Account. Now, in `workday_auth.handle_workday_auth`:
- a Sign In or Create Account alert matching `workday_flow.VERIFY_EMAIL` marks the site
  `created` and hands over as `verification_needed` (the handoff text now covers the email link);
- Create Account landing on `sign_in`/`auth_chooser` marks `created` and signs the new
  account in once with its own password, unless this run already spent its Sign In attempt
  (then it hands over as `verification_needed`, never a second attempt);
- `classify` reads verify text inside the auth step shell as `verify_email`.
An unrecognised end screen is now logged. Tests: `tests/test_workday_flow.py`.

### 2026-09-24 — Applications page: tab liveness, review-table bulk actions
"Continue" used to be offered whenever `fill.browser_target_id` was recorded, so a closed tab
only failed at run time ("Review tab was closed…"). CDP's HTTP `/json/list` ids are the same
targetIds `Target.getTargetInfo` returns, so `browser.open_target_ids()` checks liveness with one
lock-free HTTP call (safe while a fill owns the browser). `None` (unreachable) is kept distinct
from an empty set: unknown must not hide Continue. The stored target id is never cleared — a live
check is cheap and a stale id is harmless. "Continue fill selected" moved from the working table
to "Needs your review", since every stopped fill is in `REVIEW_STATUSES`; that table also gained
"Reopen and fill selected", which confirms once and only if some selected tab may still be open.

### 2026-09-24 — Workday error page: refresh everywhere, not once
CACI fill ended `fill_failed` "No application form controls detected" with the tab on
Workday's "Something went wrong / Please refresh the page / Error Code: VPS|…" page. The
old single reload only ran when `wait_for_step_ready` failed, so an error that replaced the
form at entry (Continue fill on a broken tab), after sign-in, or after Save and Continue
fell through to the zero-controls guard. Now `workday_flow.recover_site_error` reloads
(up to `SITE_ERROR_RELOADS`=3, backing off, waiting for a recognisable screen or the
error again) at: `enter_application` start and after Apply/Apply Manually, after auth, the
top of every step, and after each advance (then re-scans that step, since the draft reopens
on whichever step it saved). A fill spends at most 6 refreshes; if the error persists it
hands over (`awaiting_review`, tab kept) instead of `fill_failed`. `SITE_ERROR` also
matches "Error Code: VPS|" alone.

### 2026-09-24 — Self Identify, Voluntary Disclosures, Languages

Self-identification answers were exact-match only, so the profile's "No" never matched
Workday's "No, I do not have a disability and have not had one in the past" or "I am not a
protected veteran", and `packet._eeo_value` dropped "decline" entirely. Now
`field_matcher.eeo_pattern` maps Yes/No/decline (and race/gender prefixes) to deterministic
regexes over normalized option text, used by `match_option` (so listboxes, radios and
filler.js via its `eeo` payload all share it); more than one hit is no answer. "decline" is
sent as a literal sentinel and never typed into a text box (filler.js and engine guard).
The CC-305 disability form's unnamed per-answer checkboxes were read by filler.js as yes/no
switches (a "No" answer left every box unticked but reported filled);
`workday_flow.fill_choice_checkboxes` ticks the one matching option per group, and
`fill_self_identify` signs Name (full name) and Date (today, MM/DD/YYYY via
`workday_repeaters.fill_date_sections`), leaving Employee ID blank. Languages:
`ApplicantProfile.languages` (language, fluent, level per Overall/Reading/Speaking/Writing/
Comprehension) → `Packet.languages` → `workday_repeaters` `language-N--*` rows; levels match by
rank, falling to the highest lower rank, never higher. The row/field ids were not captured
live (no tab was open); the code finds controls by label with `language-N--language` as the
row anchor, so a tenant that names it differently lands in review, not a wrong fill.

CACI's veteran listbox (2026-09-24) offers both "I identify as a veteran, just not a
protected veteran" and "I am not a veteran"; the "No" rule matched both, so the required
question was left unanswered. "No" now excludes options that say the applicant is a veteran.

## 2026-09-24 — Philips: a Workday step scanned in its re-render gap is left blank

Philips (591991) My Information: the account's saved country (Vietnam) is applied after
the step first paints, and Workday re-renders the whole step for it ("Family Name -
Vietnamese", "District or Town"). `wait_for_step_ready` saw stable fields, but every pass
(dropdowns, radios, filler.js, `country_mismatch`) ran in the re-render gap and found
nothing; the loop then pressed Next and handed over "No application form controls
detected". Offline, filler.js on a saved copy of the DOM with the real packet fields fills
name/address/email/phone, and the read-only helpers on the live tab see Country=Vietnam.
Fix (`fill.py`): a Workday step whose passes saw no control at all (`_scanned_nothing`)
is rescanned once after 1.5 s instead of advanced (`MAX_WIZARD_STEPS` 8 -> 9 to keep the
advance budget), and a main-frame filler.js exception is now reported in progress instead
of silently counted as a skipped frame.

## 2026-09-24 (night) — Blank profile facts: warn before a fill, report after it

- **Problem.** "Are you currently legally authorized to work in the United States?" and
  "Phone Device Type" were recognised correctly (`authorized_to_work`, `phone_device_type`),
  but the profile left both blank, so every pass skipped them silently and Workday rejected
  the step. The only fallback was the Autofill model, which is told never to guess work
  authorization and can time out.
- **Registry.** `packet.PROFILE_FIELDS` maps each profile-backed canonical key to its Profile
  page label and section, with `common` for facts forms routinely ask. Keys outside it
  (preferred-name tick, resume-derived employer) are never reported as blank.
- **After a fill.** filler.js's blank-fact leftover now carries `key` and reason "Profile field
  is blank"; `fill_dropdowns`/`fill_radios` take `blank=` (salary and phone code exempt; an
  already-answered dropdown is not a blank); the engine uses `unsupported_fact`.
  `packet.missing_profile` groups them per key into `FillResult.missing_profile`, `answered`
  when the model or a saved answer filled every such question anyway.
- **Before a fill.** `/api/applicant-profile` returns `gaps` from `build_fields` (so resume
  contact fallbacks and defaults count as answered) plus keys stored fills met blank, ranked
  by `seen_in`. Shown as a Profile page banner (opens the group) and an Applications notice.
- **Defaults.** Only `phone_device_type` → "Mobile" (`packet.DEFAULTS`), with option
  fallbacks Mobile/Cell/Mobile Phone/Cell Phone. Legal and EEO answers never default.
- **Rejected.** Saving manual review answers back as `custom_answers` only helps oddly worded
  questions; synonym-mapped questions are fixed once at the profile field instead.

## 2026-09-25 — Eligibility questions answered from the profile; resolver follows reveals

A Workday step asked "Are you over the age of 18?", "Are you legally permitted to work in the
country where this job is located?", then (only after Yes) "If hired, can you provide proof of
eligibility?". The model answered the first two and missed the third. Causes: no synonym for
"permitted"/"proof of eligibility"/"over 18"; the permitted question matched the country rule
(first match wins), so ill_dropdowns tried "United States" in a Yes/No list and
country_mismatch read the later "Yes" as a wrong Country; profile.over_18 was never emitted;
and esolve_step_blockers returned as soon as the page showed no errors, which on Workday is
always true before Save and Continue, so a question revealed by the model's own answer was
never seen. Fix: ts_hints.AUTHORIZED_TO_WORK/OVER_18 before the Country rule (proof of
eligibility reads the same fact as authorization: provable follows from authorised; exclusions
for veteran/degree/licence/clearance proof and "under 18"); uild_fields emits over_18
(registered, common); ield_catalog reuses the patterns but leaves "sponsor" wording alone;
the resolver runs up to 2 extra rounds on controls revealed after its actions (not counted
against max_retries). Also packet.authorization_mismatch: a posting whose location names
another country drops uthorized_to_work (fill + engine), with a review line, not a blank.
Not chosen: a second model pass. It would still have no fact to answer from.

### 2026-09-25 — Stray popup cleanup at Workday handoff and Continue start
Handed-off Workday tabs (most often after Continue fill) sometimes would not scroll with the
mouse wheel. Likely cause (not confirmed in DevTools on a live tab): fill steps close
dropdown/prompt popups with a best-effort Escape on the trigger that can miss (and
`select_prompt`'s exception path presses none), leaving the popup plus Workday's
full-viewport `click_filter` dismiss layer up. Continue reattaches to the existing tab
without a reload, so it inherits leftovers and re-opens popups on already-answered fields.
`workday_flow.close_stray_popups` now runs at every `_workday_handoff`, at the start of a
Workday Continue fill, and before the final evidence screenshot: page-level Escape, then a
click on the dismiss layer's corner only if a `click_filter` is on top there. It never acts
while a real dialog is up (start dialog / OTP / terms handoffs need it open). A reload at
Continue start was rejected: it drops unsaved answers on the current step.

## 2026-09-25 — Education has one source: the master resume

- Workday filled education twice (second row missing Field of Study). The packet carried a
  profile row ("University of California - Irvine", "Bachelor of Science", major) and a
  resume row (comma form, "Bachelor of Science in ... & Minor ...", no major); the fuzzy
  merge in `_build_education` only collapsed a *generic* profile "Bachelors", so a named
  profile degree kept both. The repeater correctly added a row per packet entry.
- Fix is structural, not a better matcher: the profile's `school`, `major`, `degree_level`,
  `gpa`, `education_start_month`, `graduation_month` are gone. `Education.major` (never
  rendered) is new; `_build_education(resume)` is one row per resume entry, degree level
  from `degree_of` on the degree line, dates from `parse_range`. Single-field forms answer
  from the first entry. The merge heuristics, UCI alias table and start-month backfill
  are deleted. `highest_education_obtained` stays on the profile (free text).
- `profile.load_profile` migrates a legacy profile once: blank `major`/`gpa` on the
  uniquely matching resume entry (`closest_option(key="school")`) are filled, both files
  backed up as `.<stamp>.bak.json`, profile rewritten without the keys. No readable resume
  → untouched, retried next load. Owner's default workspace migrated 2026-09-25 (major
  added; GPA already present).
- Education gaps now link to `/profile/resume` (`packet.profile_path`), where a banner
  lists them; the resume editor has a "Major (field of study)" input. Fills rebuild the
  packet every run, so already-prepared applications need no re-prepare.

## Store: merge-on-write instead of compare-and-set (B1/B2, 2026-09)

- Lost updates came from `load_all -> mutate -> save_all` with no lock, and from fill holding a row for minutes and writing the whole row back. The plan was a `revision` compare-and-set with every one of the 44 `upsert` call sites rewritten to `update(key, fn)`. Chosen instead: `upsert` is a field-level three-way merge. Rows handed out by `get`/`load_all`/`list_applications`/`build_index()` remember the stored version they came from (`Application._base`, a PrivateAttr), and `upsert` writes only the fields that differ from it onto the row as stored now, under a process-wide `RLock`. That fixes every existing call site at once and leaves nothing that can raise mid-fill.
- Conflict rule: the caller wins, except that a row someone moved to a terminal status keeps it, and a note records the late result (a fill finishing after "Mark submitted"). `status_history` and `source_refs` are append-merged.
- After a write the caller's object is refreshed in place to the merged row. Without that, its next write would diff stale fields against the new base and revert other writers.
- Restoring an earlier snapshot (failed Prepare refresh) needs the opposite of a diff, so it goes through `store.restore(previous)`, which keeps the stored notes and any terminal status.
- `revision` is bumped on every row write, for the UI (ETag, "changed elsewhere") and the SQLite move.
- B2 interim: `_snapshot()` caches parsed rows keyed on the file's bytes. A byte compare is robust to the coarse mtime granularity that made an mtime key flaky in tests. `get()` on 2,000 rows went from 24 ms to 0.4 ms.

## Nightly scheduler (B3, 2026-09)

- `apply/scheduler.py` replaces the exact-minute check in `web/app.py`. That check skipped a day whenever a 60 s wake drifted past the scheduled minute, and never ran when the machine was asleep at the time. A run is now due any time from `schedule_time` until 12 hours after it (`CATCH_UP_WINDOW`), including on the first tick after startup. Later than that the day is recorded as missed rather than starting mid-afternoon unannounced.
- The last run date lives in `<DATA_DIR>/apply_scheduler.json` per profile and is written before the run starts, so a crash mid-run does not restart it on each boot.
- A tick waits while a daily pass or an Apply operation is running, and retries 30 s later.
- Only the active profile is scheduled. Scheduling others would rebind config paths under the user; that waits for S6.
- `GET /api/applications/daily-status` carries `scheduler` (last run, next run, `missed_today`, `last_error`) for the Apply settings drawer.

## Secrets out of the JSON files (B7, 2026-09)

- `secret_store.py` keeps the Workday profile password, the per-tenant Workday vault passwords, and API keys saved in the app. Backends: the OS keychain via `keyring`; else `<DATA_ROOT>/secrets.enc` (Fernet, key in `RESUME_TAILOR_SECRET_KEY` or `.secret_key` 0600); `memory` for tests (forced in `tests/conftest.py`).
- The file fallback is honest about its limit: with the key beside the data it protects a copied or synced JSON file, not a stolen data folder.
- Migration is lazy and one-way. `profile.load_profile` moves a plaintext `workday_password` into the store after a backup; `workday_auth._save_vault` drops passwords from `workday_vault.json`. If the store refuses a write (a locked keychain), the password stays in the file and a warning is logged, so it is never lost.
- `save_profile` with an empty password leaves the stored one alone, because `_migrate_education` and similar paths rebuild a profile from the file, which never has it. `clear_workday_password()` is the explicit delete.
- API keys: `config.credential(name)` reads the environment first, then `api_key:<NAME>` in the store, only for `SAVABLE_CREDENTIALS`. `/api/secrets` is write-only: GET reports set/source, never a value.
- Secret names are namespaced per profile (`profile:<workspace id>:...`), so the store is shared across profiles without collisions.

## Click guard (B13, 2026-09)

- Every Apply click goes through `apply/clicks.py`, and `tests/test_click_guard.py` fails on any `.click(` elsewhere under `apply/`. The 49 call sites were rewritten mechanically (AST) with a purpose each: `enter` (Apply / Apply Manually / resume draft), `advance` (Next / Save and Continue), `dismiss` (stray popup), `select` (options, labels, dropdown triggers, repeater Add), `auth` (Sign In, Create Account, email-route chooser, Workday click-filter overlay).
- `enter`/`advance`/`dismiss` refuse text, aria-label, value or title matching `SUBMIT_TEXT`, and refuse when the text cannot be read. `select` refuses a submit input or a button-like control whose text reads as submit, but not options: an option may legitimately say "Complete". `auth` is unchecked because some Workday tenants label the sign-in overlay "Submit"; only the auth code uses it.
- `submit_click(loc, decision=action)` is the only path to a final submit, used once in `fill.py`, and raises unless the decision is `auto_submit`.
- Checked by hand against Chromium: a Workday Review "Submit" (no form), Greenhouse "Submit Application" and an iCIMS `input[type=submit]` are refused for both `advance` and `select`. The same checks live in the test file and run where Playwright's bundled browser exists.

## Application store on SQLite (S1–S3, 2026-09)
`apply/store.py` keeps its whole public API but persists to the `applications` table of
`<DATA_DIR>/app.db` (`storage/db.py`: per-thread connections, WAL, `BEGIN IMMEDIATE`
for every read-modify-write, a per-table change counter in `meta`). The DB path derives
from `config.APPLICATIONS_PATH.parent`, so workspace switches and tests' monkeypatched
path need no new plumbing, and there is one file per workspace rather than a
`workspace_id` column (add that column only for the hosted version). The three-way
merge from B1 is unchanged; it now runs inside a DB transaction, so the nightly CLI
process and the server cannot lose each other's writes either. `_write` writes only
rows that are not the cached objects, so an upsert is one row, not the table.
Legacy `applications.json` is imported on first open (old v1–v4 upgrade steps run in
memory), copied to `backup-pre-sqlite-<stamp>/` and renamed `.migrated`; a corrupt
file is set aside as `.corrupt-<stamp>` and logged rather than crashing every read.
A file reappearing after import is ignored (logged). Deviation from the plan: the
operations registry (`operations.json`, transient) and run directories stay files;
the plan's `application_refs`/`application_events`/`answer_memory` tables are added by
the tasks that first need them (a new entry in `db.MIGRATIONS`, never an edit).

## P3-A: answer memory (2026-09)
- `apply/answer_memory.py` stores in a new `answer_memory` table (db migration 2) in the workspace's `app.db`, next to the applications. It never goes in `applicant_profile.json`: the rows are a log of corrections, not profile facts. Uniqueness is `(label_norm, ats)`, so a second correction to the same question replaces the first.
- Capture happens only in `review.correct`, after the correction is verified in the browser, and only for questions the field catalog doesn't classify as a profile fact (`policy != "known"`). A wrong phone number is fixed in the profile, not memorised. A failure to remember never fails the correction.
- Recall runs after the profile/packet value and before the model, at three spots: `engine.py` (verified engine: `answer_source="memory"`), the legacy `fill.py` leftovers (ahead of `custom_answers`), and `fill.py` long-text questions (ahead of `answer_question`). A remembered long answer over the field's `maxlength` goes to review rather than being truncated.
- Company handling: labels normalise the posting's company to `{company}`, so "Why Acme?" and "Why Beta?" are one question. The answer text is never rewritten. An answer that names a company other than the current posting's comes back `needs_review` and becomes a review item (`saved_answer_other_company` in the engine) instead of being filled.
- Never stored or recalled: equal-opportunity questions (by label regex and by canonical key), passwords (label or `input_type`), codes, SSN, date of birth, signatures.
- Test gap: there is no end-to-end harness for `engine.fill_application` in the suite. Recall is covered at the module level and capture through `review.correct` with a faked browser.

## Auto-submit guard rails (P4-S)

- **The guard runs at the last moment, in `fill.py`, not in the operation worker.** The
  worker's `auto_submit_max_per_run` still decides the submit mode. Only the form knows
  whether it is ready, and the registry can change during a long batch. So
  `submit_guard.check` runs right before the click and re-reads everything live. A held form
  ends `awaiting_review`, `ready_to_submit=True`, with the hold message as its handoff reason
  and status note.
- **The pause switch is global, not `kv('automation')`.** The plan put it in the
  per-workspace DB, but "pause all automation" has to cover every profile. The scheduler
  already iterates over them. It is a small JSON file under `DATA_ROOT`; a missing or
  unreadable file means not paused. The scheduler returns `"paused"` without recording a run,
  so resuming inside the 12-hour catch-up window still runs today's pass.
- **Caps use a rolling 24 hours, not calendar days**, to avoid a burst at midnight. They
  count `submitted` *and* `submit_unconfirmed` changes noted `auto_submit`, because an
  unconfirmed click may have reached the employer. `0` means no automatic submits, never
  "unlimited".
- **Duplicates:** the row's own history comes first (a row submitted by hand and later
  reopened is never auto-submitted). Then the same `group_key` at any age, or the same
  normalised company and role submitted by any means within 30 days.
- **Pacing is per process, with at most one submit in flight.** `pace()` holds a lock
  across the click and sleeps in steps of at most 1 s, so a cancel or pause during the wait
  stops the submit. A slot is only recorded when the submit went ahead. The tests replace
  `_sleep`, `_clock` and `seed()`, and `conftest` makes sleeping a no-op everywhere.
- **Audit evidence:** `before.json` (filled fields and uploads) is written *before* the
  click and is required: if it cannot be written, the submit does not happen and the row
  ends `fill_failed`. Screenshots are best-effort.

## Company watchlists and business titles (P4-D)

- **Board listings live in `apply/boards.py`, not `ats_api.py`.** `ats_api` fetches one
  posting's text by canonical key. A board listing is a different job with different
  failures, and they need to be told apart: `BoardNotFound` (404: a wrong or retired
  name, so fix the settings) versus `BoardUnavailable` (try again tomorrow). A watchlist
  reports each failed board as one run error and keeps the others.
- **Rows use the ATS's own job URL** (`boards.greenhouse.io/{slug}/jobs/{id}` and so on),
  never the company's careers-page redirect. That keeps `identity.canonical_key` equal to
  the key a Simplify row for the same job gets. The Ashby listing also primes
  `ats_api._ASHBY_BOARD_CACHE`, so the JD fetch doesn't download the board a second time.
- **An undated posting is kept as fresh** (`age_days=0`, flag `age_unknown`). The
  README filter drops rows with no age, but a board only lists open postings.
- **Keyword matching:** title words match at a word start ("intern" finds "Internship",
  "consult" finds "Consulting"). Locations match whole words, so "NY" matches
  "Albany, NY" but not "Sunnyvale".
- **Starter watchlists were not verified from the build environment.** Its network
  policy blocks the ATS APIs. So they are suggestions only: each one goes through
  `POST /api/apply/boards/resolve` before it is added, and a renamed board shows as
  struck through, never silently empty. Onboarding's business field adds an *empty*
  watchlist, with business title keywords, for the same reason. Consulting has no
  starter list: the large firms mostly run Workday or their own sites.
- **D3 was narrowed on purpose.** The plan said to treat "Analyst" and "Associate" as
  early career. Existing tests pin a deliberate rule: a bare "Data Analyst" asking for 5+
  years is rejected. Bare titles still pass `check_title`; only explicit program wording
  ("Summer Analyst", "Analyst Program", rotational and development programs, "Early
  Career") counts as early career. The same pass fixed a real gap: `check_title` rejected
  every title containing "manager", so "Product Manager Intern" never passed discovery.

## Fill edge cases (P4-E)

- **New checks** (`apply/form_guards.py`, pure and hermetically tested):
  - E13, closed postings: a 404/410, a closing banner in the first 1,500 characters, or a
    redirect to the same site's careers home. `fetch_jd` sets `FetchResult.closed`, and
    `_process_one` marks the row `skipped` before screening or tailoring, so a closed
    job costs no model calls. The per-row fetch retry does the same. Only the top of the
    page is read, so "applications are closed on holidays" deep in a real JD doesn't
    count.
  - E19, non-English forms: `<html lang>` not starting with `en` is handed over.
    A missing `lang` counts as English, since most US forms don't set it.
  - E21, refused visits: 403/429 or a block-page title ("Access Denied", "unusual
    traffic"). The fill hands over and the host rests for an hour, in-process;
    `fill_application` refuses that host until then. Read from `page.goto`'s response
    and `page.title()`, not an extra `page.evaluate`, because the fill tests queue
    `evaluate` results in order.
  - E14, Workday session timeout: a sign-in screen at the start of a later step is a
    handoff (`SESSION_EXPIRED_MSG`). **Deviation:** no automatic re-sign-in. The auth
    block runs before the step loop and isn't re-entrant, and Continue fill already
    signs in again from the same tab.
  - E18, long saved answers: `fit_to_limit` cuts at the last sentence end within
    `maxlength` (or the last whole word), and the field is always flagged for review.
    Drafted answers were already trimmed by `answer_question`.
- **Already covered before P4-E** (no change): E1 frames (`page.frames` loop), E4
  revealed-field passes (`filler.js`), E5/E6 comboboxes and date widgets
  (`controls.py`, Workday prompts), E10 blank legal answers (never guessed), E11 OTP
  handoff, E12 CAPTCHA handoff, E15 existing-account handoff, E16 phone country codes
  (`engine._national_phone_value`, `controls._phone_match`), E17 middle name (profile
  field), E20 Workday popups.
- **Not done:** E2 shadow DOM (belongs to AD6), E3 overwriting ATS resume-parse
  prefills, E7 multi-location lists, E9 portfolio uploads, and a separate E.164 packet
  field. Each needs live ATS fixtures to build safely.

## P4-A: platform adapters (2026-09-25)

- **Wizard screens, not wizard handlers.** The plan sketched a `WizardAdapter` with
  `handlers: dict[Screen, Callable]` extracted from `workday_flow`. Workday's 1,350-line
  flow is tuned on captured live tenants, and nothing here can re-capture them, so it was not
  moved. `wizards.WorkdayWizard` wraps `workday_flow.classify` / `is_review_step` and a test
  checks every captured Workday screen maps unchanged. The new platforms share one
  text-and-structure classifier; the fill loop's existing field filling does the steps, and
  the adapter only decides which screens are the applicant's (sign-in, account, code,
  closed) and where the loop stops (review).
- **Why hand over before filling.** On a sign-in page the filler would type the email into
  the login box. The handoff check runs after the Workday block and before the filler, so
  nothing is typed. The review check runs after filling, because review pages can carry an
  e-signature field.
- **Review detection is whole-name.** "Review our privacy policy" is not the review step.
  Only a step name or heading that is exactly "Review", "Review and Submit/Apply", "Review
  (your) application", "(Application) summary" (after "Step 5 of 6" / "5 -" numbering is
  stripped), a platform's own `review_words`, or a page with no fields and only a Submit
  button counts.
- **Fixtures are synthetic.** `tests/fixtures/wizards/screens.json` is written from each
  platform's public wording (the proxy blocks these sites here). Replace with captured
  snapshots as real dry-run fills are reviewed; the plan's "10 live dry-run fills per
  adapter" gate is still open.
- **Not done:** the `ats_auth.py` vault generalisation (iCIMS/Taleo accounts are handed
  over, not created), Taleo/SuccessFactors radio-table handling beyond `filler.js`, and
  Lever `cards[...]` parsing (the filler's bare-text labels already read them).
- **Assist-only job boards.** `fill.ASSIST_ONLY_ATS` = Workday + LinkedIn + Indeed +
  Handshake (plan X5, done here with the new kinds). The settings drawer's auto-submit list
  never offered them.
- **New canonical keys do not re-key stored rows.** A row stored as `other:<host>:<digest>`
  keeps its key; discovery drops known rows by `(source, source_job_id)` before recomputing
  a key, and `group_key` plus the P4-S duplicate guard cover the rest. `ats_stats.py`
  re-detects the platform from the URL so old `other` rows count under their platform.
- **Shadow DOM (AD6 / E2).** `deepQueryAll` walks open shadow roots in document order;
  closed roots stay hidden. Playwright CSS locators pierce open roots, so reported
  selectors still resolve. A `<legend>` question with `label[for]` radios was already
  unrecognised in the light DOM (the hybrid resolver handles those groups); unchanged.
- `tests/test_filler_dom.py` now falls back from Edge to Playwright's Chromium
  (`PW_CHROMIUM_PATH`), so these DOM tests run in the container as well as on Windows.

## P4-X: extension pairing and capture, server side (2026-09-25)

- **Pairing** (`web/extension.py`): one pending 6-digit code at a time (120 s, 5 wrong
  guesses voids it), traded at `POST /api/extension/pair/complete` for a random token.
  Only its SHA-256 is stored, in `<DATA_ROOT>/extensions.json` (global, like the
  automation switch), not in `secret_store` as the plan said: a hash needs no keychain,
  and the file can be revoked from without unlocking anything.
- **Extension lane** (`web/security.py`): `/api/extension/*` skips the cross-site and
  session-token checks (the origin is `chrome-extension://…` and there is no cookie) and
  instead needs `X-RT-Extension`; `pair/complete` is the one open path. The Origin must
  be an extension scheme or an allowed host, so a web page cannot use the lane even with
  a stolen token. Pairing management (`/api/extension-pairings*`) stays behind the app's
  own session.
- **Capture** (`POST /api/extension/capture`): keyed on the external apply URL when the
  page gives one, else the page URL; dedupes against both. Text goes through
  `jd_input.from_text` (same 200-char floor and warnings as paste/URL), row is
  `source="extension"`, `jd_fetched`, then the no-LLM prefilter (a failure marks it
  `screened_out`). Prepare reuses the captured text (`daily._captured_jd`, fetch method
  `captured`) because LinkedIn/Handshake pages cannot be refetched without a login.
- **Prepare/Fill from the extension** always send `auto_submit=False`: the student is at
  the tab. Model comes from the Apply settings' autofill model.
- **Not done here:** the MV3 extension UI, the Settings → Browser pairing UI, and the X3
  `cdp_relay` spike (moved to another machine). CDP mode stays the only fill driver.

## P4-X: browser extension (2026-09-25)

- Settings → Browser now creates and replaces short-lived pairing codes, lists paired browsers, and confirms revocation. The normal app session still protects those routes.
- The unpacked MV3 extension discovers the local app on ports 8000–8010, stores its paired token in extension local storage, and sends page text only after a capture action. The popup sends the active URL for lookup. Captured external Apply links are used for deduplication and lookup; LinkedIn redirect links are unwrapped without a network request.
- The extension service worker owns a session-scoped Prepare → Fill follow-up so closing the popup does not cancel it. A dispatch interrupted before its response is not retried blindly. All extension Fill requests continue to set auto_submit=false in the existing server route.
- activeTab cannot read a cross-origin iCIMS iframe. Selection capture or opening the iframe as its own tab is the fallback; broad host permissions were not added.
- The normal CDP browser remains the Fill driver. The separate X3 relay spike is evaluated independently; this extension does not gain debugger permission without all GO tests. Store publishing is not done.

## P4-X: browser extension relay decision (2026-09-25)

- X3 GO on the isolated extension-relay-spike branch. A synthetic Greenhouse-like
  posting in headless Edge completed the real fill_application path through the
  extension relay with status awaiting_review and no submit. The same probe used
  set_input_files, evaluated a cross-origin iframe, and completed wait_for_selector.
  Closing the controlled tab during Fill persisted fill_failed with the exact error
  "Tab was closed or DevTools opened". No live job site was contacted in this probe.
- BROWSER_MODE defaults to cdp. The optional extension mode uses an explicitly
  attached tab, a separate loopback relay process, and an ephemeral secret CDP URL.
  The only Fill integration change is in apply/browser.py. The relay gets the
  debugger permission; there is still no all-URLs host permission. A 20-second
  WebSocket ping keeps the relay connection alive.
- The relay reuses the selected tab for Target.createTarget because it cannot create
  an arbitrary page through the limited debugger attachment. Only one tab and one
  Playwright client are supported at a time. The relay currently needs manual startup
  and attachment from the popup. These are deviations from a seamless Fill button.
- Store publishing and live LinkedIn/Greenhouse manual acceptance were not done.
  CDP remains the default. The existing Advanced CDP setting is unchanged.

## P4-E leftovers: phone shapes, portfolio, location lists, parser overwrites, Lever cards (2026-09-25)

- **E.164 (E16):** `apply/phone.py` is pure string rules, not a phone library: the
  calling code comes from a typed `+`/`00`, else `phone_country_code`; NANP numbers must
  be 10 digits, other codes drop a trunk `0`; 8–15 digits or `None` (the phone is then
  typed as entered). The packet carries `phone_e164` and `phone_national`. filler.js
  uses the national number beside a separate code control, E.164 only when the box asks
  (`^\+` pattern, "international"/"include country code" hint). A "+1" placeholder
  alone does not count: masked inputs show one and reject a typed "+".
- **E9 portfolio:** the transcript upload was generalised (`_store_document` /
  `_forget_document`); `portfolio_path` is server-owned like `transcript_path`. Fields
  labelled portfolio / work sample take the PDF; "Resume or portfolio" takes the resume
  (every packet has one). Transcript and portfolio files are staged as
  "<Name> Transcript.pdf" / "<Name> Portfolio.pdf" — before this the transcript was
  staged under the cover-letter filename (bug fixed in passing).
- **E7 location lists:** only a named checkbox group of 2+ under a location question.
  Order: every option `location_preference` names (place head before a comma or
  parenthesis, whole-word match), else the posting's city (`posting_location`, fill-time
  only), else the first option **only when the list is required**, flagged as
  "<question>: Picked the first location; check it". Deviation from the plan's "else the
  first": an optional list stays blank rather than guessing. The flag is its own
  needs_review string because verification drops review labels whose field it observes.
- **E3 parser overwrites:** runs only after a resume upload in the step, as filler.js
  `correct: true`: plain text inputs whose key is a contact fact (names, email, phone,
  address, city, postcode, links, school, major, GPA) and that disagree with the profile
  (case, phone digits and URL shape normalised) are rewritten; nothing else is touched
  and blanks are not filled. The outcome keeps `previous` and a `reason_text` the review
  row already renders. Selects/comboboxes (state, country, typeahead school) are not
  corrected.
- **Lever cards:** labels and the required flag come from the card's hidden
  `cards[<id>][baseTemplate]` JSON (the markup only shows a styled "✱" and the card
  title), in both filler.js and filler_readiness.js. No live Lever form was used; the
  test fixture is synthetic.
- **Encoding fix:** the extension branch's note block above was appended as UTF-16
  (PowerShell `>>`), which made this file read as binary; it was re-encoded to UTF-8.
  On Windows append notes with `Add-Content -Encoding utf8`, not `>>`.

## Workday: no second Education row after Continue/Reopen (2026-09)

The owner saw Education added twice. On a re-run of My Experience (Continue, Reopen,
error recovery) the row this fill added earlier carried a Field of Study the applicant
picked or a one-result search committed ("Computer and Information Science" for
"Computer Science"), so `_choose_row`'s exact/partial/blank stages all missed and a new
row was added. Now: the major compares both ways through `closest_option` (`_same`);
rows claimed by an earlier entry this pass are excluded; when nothing matches, the single
unclaimed row whose school (employer, for work rows) matches is reused if no later entry
shares that school (`_reuse_or_guard`), keeping its Field of Study as the applicant's
answer; and when the page already has as many rows at that school as entries left to
place, the add is blocked and flagged "possible duplicate row" instead. `_add_row` takes
one late look (1.5 s) so a slow render is not left as a second blank row for the next
pass to call ambiguous.

## Remembered answers never duplicate the profile (2026-09)

The owner saw Profile → Remembered answers repeat facts from other profile sections.
`review.correct` remembered any correction whose `field_catalog.classify` was not
"known", and that catalog is far smaller than `ats_hints.SYNONYMS`; rows were also one
per (question, ATS). Now `answer_memory.profile_key` (the fill's canonical key, else a
short label of at most 8 words through `workday_flow.key_for_label` + a referral regex)
decides whether a profile field answers the question. Such a correction is never
remembered: it fills the profile text field when blank (`save_to_profile`, a fixed list
of plain-string fields; Yes/No and EEO fields are never written). `list_answers` groups
rows by `label_norm` (sites, `differs`), and edit/delete act on every row of the
question. A one-off pass (`schema_migrations` marker `answer_memory_cleanup_v1`, run
lazily from `list_answers`/`recall`) moves existing profile-duplicate rows into blank
profile fields and deletes them, after writing `backups/answer_memory-<stamp>.json` next
to the workspace database.

## 2026-09-26 — Posting-age window: one-off catch-up, watchlists widen only
Find keeps postings no older than `max_age_days` and dedupes against the store; it never
looks at the last run, so days away lost postings for good. Search options now carries a
one-off window (1 day / 7 days / custom, `ApplyOperationRequest.max_age_days`, applied as a
`model_copy` of the captured settings in `operations._worker`); the saved setting uses the
same `AgeWindowPicker`. A source's own `max_age_days` now *widens* the funnel-wide limit
(`max(src, funnel)`) instead of replacing it, so a 30-day catch-up reaches watchlists while
1 day never shrinks a watchlist below its 7. The per-search cap is unchanged; the "Most
postings per search" placeholder read "All" but empty means `max_new_per_day`, so it now
shows that number.

## 2026-09-27 — Workday rows: popup before Add, skill-chip dedupe, rows kept in the record
F5 (Software Engineer I) left every Work Experience and Education row empty: each `_add_row`
press timed out (bare `TimeoutError`, ~5 s apart). The Skills prompt runs just before the
rows and its results popup kept Workday's full-viewport `click_filter` up over the Add
buttons. `fill._fill_workday_experience_and_education` now passes
`workday_flow.close_stray_popups` as `dismiss`: it runs before the rows and once more when an
Add press is blocked; `fill_skills` also ends with it. `_ADD_BUTTON_JS` counts only visible
add buttons and tags the chosen one `data-rt-add` (a hidden template button shifted `.nth`).
A press that still fails raises `AddRowError` naming Playwright's call-log blocker ("…
intercepts pointer events", `_reason`), and later entries in that section reuse the reason
instead of waiting again. The same page showed "You cannot enter duplicate skills": the
exact and model paths never checked the option against existing chips (a Continue run finds
the first run's chips; "HuggingFace" searches to "Hugging Face"); `field_matcher.same_skill_in`
now skips it. Filled rows (no selector) were dropped when `_observe_fields` replaced
`merged["filled"]` and collapsed in the `(frame, selector)` outcomes map; they are kept and
keyed by label.

## 2026-09-27 — Veteran status is a four-way category, matched by option tiers
CACI's required veteran listbox (four options) was left on "Select One". The profile held
free text "No", which cannot say "not a veteran" vs "not a *protected* veteran", and
`eeo_pattern` built one regex per answer and hoped exactly one option matched; each new
wording needed another regex patch, and the failure recorded only a bare label. Now
`EEOAnswers.veteran` is `protected | veteran_not_protected | not_veteran | decline | ""`;
a `mode="before"` validator converts legacy text (`field_matcher.veteran_category`: No →
not_veteran, Yes → protected) and keeps the original in `veteran_legacy`, which the Profile
page shows as "please check" until confirmed. `field_matcher.VETERAN_TIERS` lists option
patterns per category, most specific first (not_veteran: "not a veteran", then "not a
protected veteran", then a bare "No"); a tier naming no option falls through, one naming two
stops. `eeo_tiers`/`eeo_patterns` return lists, and `filler.js`'s `eeoPick` applies the same
rule (unnamed checkbox boxes choose among their container's boxes, so a fallback tier never
ticks a second box). The OFCCP "protected veteran but choose not to self-identify" option is
an answer, not a decline; OFCCP sub-categories ("Disabled Veteran") are never guessed. Failed
self-identification choices now log and review `choice_failure` lines with the form's options
(`workday_flow.last_listbox`). VEVRAA labels quote "entitled to compensation": self-
identification now classifies before salary in `field_catalog.classify` and filler.js never
treats a choice control as a salary box. Corpus: `tests/fixtures/eeo/veteran_options.json`
(add new live wordings there). Gender/disability keep their single-rule matching for now.

## 2026-09-27 — SmartRecruiters entry: "I'm interested", DataDome, assist-only
SmartRecruiters postings open the one-click form with an "I'm interested" link
(`a#st-apply`, `a.js-oneclick`); hidden `js-smartr-oneclick` twins go to smartr.me and are
excluded. `ats_hints.ATS_PRE_FILL_CLICKS["smartrecruiters"]` clicks it; the generic entry
search uses the shared `ats_hints.APPLY_ENTRY_PATTERN` (Apply…, I'm/I am interested, Start
application) and is skipped once the SmartRecruiters hint has entered the form. The verified
engine gets `SmartRecruitersAdapter.enter_application`; `engine` calls any adapter that
overrides `FormAdapter.enter_application` (was Workday-only). The one-click form sits behind
DataDome ("Verification Required", `geo.captcha-delivery.com`) for automated browsers:
`_detect_barriers` reports it as a CAPTCHA for the applicant, never automated. SmartRecruiters
joined `fill.ASSIST_ONLY_ATS` and left the auto-submit picker until live dry-runs exist.

## 2026-09-27 — F5 live re-run: optional education years, slow saves, stale duplicate chips
A live reopen fill on F5 after the fixes above filled all five employment rows and the
education row, and My Experience saved. Three follow-ups: F5's Education asks no years
attended, so `_date_absent` makes a missing years control "not a gap" (like GPA). The save
took longer than `wait_for_step_change`'s 15 s and the fill reported "did not advance";
while `pageFooterNextButton` is disabled (save in flight) the wait extends to 3× the
timeout, with one last look at the end. A draft saved by an earlier run kept duplicate
skill chips; `workday_flow.remove_duplicate_chips` (focus + Delete, verified per chip) runs
before skills are entered. CACI could not be re-checked live (already applied).

## 2026-09-27 — Career-page watchlist discovery and Workday boards

- Workday board slugs store `{host-prefix}/{tenant}/{site}` (for example `acme.wd5/acme/External`), so the public careers URL and CXS jobs endpoint round-trip without relying on a company name. Listing uses bounded 20-job POST pages and converts Workday relative posting dates to ISO dates for the existing watchlist age filter.
- Board resolution reads one bounded company careers page and counts supported ATS links in iframe, script, and anchor URLs. It validates the selected board through the existing live listing check; equal top counts return candidates, and pages with no supported link return 404. The editor accepts and labels Workday while showing the resolver's existing error detail.

## 2026-09-27 — SmartRecruiters one-click form: City, Experience, Education, Resume, Message

The generic pass filled none of these five areas on `/oneclick-ui/` (live Resultant 744000151474767 and Wellmark 744000150732768). The causes: the City typeahead (`div[data-test=personal-info-location] spl-autocomplete`) drops typed text on blur and only commits a *clicked* option, stored as the host's `value` object (`city`, `region`, `stateCode`, `country`). Experience/Education are inline editors behind "Add" (`oc-button[data-test=add-experience|add-education]`) with typeaheads for title/company/institution (a `#spl-custom-option` commits the typed text), flatpickr month pickers that accept typed `MM/YYYY` + Enter, and Save/Cancel. Both dropzones' inputs are `#file-input`, so `filler.js` deduped to the *top* "Easy Apply" one, which parses the resume and prefills the form. The message box is `#hiring-manager-message-input` ("Let the company know about your interest…"), which `filler.js` reports as long text.

Built `apply/smartrecruiters_flow.py` on the `workday_repeaters` model: entries are found by `data-test`, and a listed entry with the same title+company (or the same school with a compatible major/degree) is reused. An editor someone already has open is never touched. Answers already present (city, resume file, message) are kept, and whatever can't be verified goes to `needs_review`. City and office locations pick the single option for the city in the profile's state, then verify the committed object; an ambiguous match is cleared and left for review. `fill.py` (legacy engine, the default) calls it after the `filler.js` pass and before attachments. It drops the generic records for City, `#file-input` and the message box, and keeps the flow's records under key `smartrecruiters_entry`, next to `workday_row`. Wellmark has no City field, which is not a gap.

Deviation: clicks go through `_activate`, a real mouse press at the control's centre made only after `elementFromPoint` (followed through shadow roots and slots) confirms it lands on that control. In the applicant's background tab Edge throttles `requestAnimationFrame` to about 1/s, so Playwright's stability wait cost ~2s per click (158s for the form). Dispatched clicks are ignored because the menus need trusted events. The form now takes ~70s. The verified async engine (`engine.py`) is not hooked, since the Workday repeater flow is legacy-only too. Tests: `tests/test_smartrecruiters_flow.py` runs against sanitized captures under `tests/fixtures/smartrecruiters/` plus `behaviour.js`, a component stand-in that commits options only on trusted presses.

## 2026-09-27 - Parallel nightly fills (T7)

The unattended batch dispatches oldest ready applications to up to 1-4 workers based on max_parallel_fills, copying the current RunContext into each. One daily batch owns the Apply browser operation lock; each synchronous Playwright worker opens its own CDP connection and new tab, while the upload lock serializes file attachment and the submit pacing lock rechecks caps immediately before a click. Pause stops dispatch and is passed into each fill so in-flight forms hand off without submitting. The extension relay continues serially because its selected-tab, single-connection model cannot provide independent tabs. The verified engine currently hands off for review rather than auto-submitting, but its attachment upload uses the same lock.
