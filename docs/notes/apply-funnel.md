# Apply funnel — implementation notes

Covers: discovery sources, screening, packet, ATS hints, browser/filler, Workday/Greenhouse, daily run, Apply page.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-09-21 — Apply Phase 1: packet, ats_hints, answer

- **Decision:** Added `apply/funnel/packet.py`, `apply/ats/ats_hints.py`, and `apply/answers/answer.py` as pure
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

- **Decision:** Added `apply/funnel/store.py` (`applications.json` keyed by `source_job_id`, atomic
  `.json.tmp` writes) and `apply/discovery/sources.py` (SimplifyJobs README parse/filter ported from
  the internship-tracker script). `ApplySettings` nests on `JobSettings` with
  `exclude_citizenship_required` mapped to `filter_rows(..., exclude_citizenship=...)`.
- **Why:** Discovery needs a durable funnel registry and deterministic README ingestion
  before orchestration or the UI can schedule daily runs.
- **Tradeoff:** `set_status` blocks terminal → pre-ready transitions only (not terminal →
  `ready`/`filling`); `FillResult` is a stub until Phase 4. Rows without a Simplify job id
  are dropped at dedupe time.
- **Follow-up:** Wire store upserts into the discover job; expose apply settings in the SPA.

## 2026-09-21 — Apply Phase 4–5: filler, fill, daily pipeline

- **Decision:** Added packaged `filler.js` / `filler_readiness.js`, `apply/forms/fill.py` (CDP
  runner with `decide_submit_action` policy A/B), `apply/funnel/daily.py` (discover → fetch →
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
  comments, docstrings in `apply/driver/browser.py`/`fill.py`/`__init__.py`/`fetch_jd.py`,
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
An unrecognised end screen is now logged. Tests: `tests/apply/ats/test_workday_flow.py`.

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
and 
esolve_step_blockers returned as soon as the page showed no errors, which on Workday is
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

- `apply/funnel/scheduler.py` replaces the exact-minute check in `web/app.py`. That check skipped a day whenever a 60 s wake drifted past the scheduled minute, and never ran when the machine was asleep at the time. A run is now due any time from `schedule_time` until 12 hours after it (`CATCH_UP_WINDOW`), including on the first tick after startup. Later than that the day is recorded as missed rather than starting mid-afternoon unannounced.
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

- Every Apply click goes through `apply/driver/clicks.py`, and `tests/apply/driver/test_click_guard.py` fails on any `.click(` elsewhere under `apply/`. The 49 call sites were rewritten mechanically (AST) with a purpose each: `enter` (Apply / Apply Manually / resume draft), `advance` (Next / Save and Continue), `dismiss` (stray popup), `select` (options, labels, dropdown triggers, repeater Add), `auth` (Sign In, Create Account, email-route chooser, Workday click-filter overlay).
- `enter`/`advance`/`dismiss` refuse text, aria-label, value or title matching `SUBMIT_TEXT`, and refuse when the text cannot be read. `select` refuses a submit input or a button-like control whose text reads as submit, but not options: an option may legitimately say "Complete". `auth` is unchecked because some Workday tenants label the sign-in overlay "Submit"; only the auth code uses it.
- `submit_click(loc, decision=action)` is the only path to a final submit, used once in `fill.py`, and raises unless the decision is `auto_submit`.
- Checked by hand against Chromium: a Workday Review "Submit" (no form), Greenhouse "Submit Application" and an iCIMS `input[type=submit]` are refused for both `advance` and `select`. The same checks live in the test file and run where Playwright's bundled browser exists.

## Application store on SQLite (S1–S3, 2026-09)
`apply/funnel/store.py` keeps its whole public API but persists to the `applications` table of
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
- `apply/answers/answer_memory.py` stores in a new `answer_memory` table (db migration 2) in the workspace's `app.db`, next to the applications. It never goes in `applicant_profile.json`: the rows are a log of corrections, not profile facts. Uniqueness is `(label_norm, ats)`, so a second correction to the same question replaces the first.
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

- **Board listings live in `apply/discovery/boards.py`, not `ats_api.py`.** `ats_api` fetches one
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

- **New checks** (`apply/forms/form_guards.py`, pure and hermetically tested):
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
- `tests/apply/forms/test_filler_dom.py` now falls back from Edge to Playwright's Chromium
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

- **E.164 (E16):** `apply/answers/phone.py` is pure string rules, not a phone library: the
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

Built `apply/ats/smartrecruiters_flow.py` on the `workday_repeaters` model: entries are found by `data-test`, and a listed entry with the same title+company (or the same school with a compatible major/degree) is reused. An editor someone already has open is never touched. Answers already present (city, resume file, message) are kept, and whatever can't be verified goes to `needs_review`. City and office locations pick the single option for the city in the profile's state, then verify the committed object; an ambiguous match is cleared and left for review. `fill.py` (legacy engine, the default) calls it after the `filler.js` pass and before attachments. It drops the generic records for City, `#file-input` and the message box, and keeps the flow's records under key `smartrecruiters_entry`, next to `workday_row`. Wellmark has no City field, which is not a gap.

Deviation: clicks go through `_activate`, a real mouse press at the control's centre made only after `elementFromPoint` (followed through shadow roots and slots) confirms it lands on that control. In the applicant's background tab Edge throttles `requestAnimationFrame` to about 1/s, so Playwright's stability wait cost ~2s per click (158s for the form). Dispatched clicks are ignored because the menus need trusted events. The form now takes ~70s. The verified async engine (`engine.py`) is not hooked, since the Workday repeater flow is legacy-only too. Tests: `tests/apply/ats/test_smartrecruiters_flow.py` runs against sanitized captures under `tests/fixtures/smartrecruiters/` plus `behaviour.js`, a component stand-in that commits options only on trusted presses.

## 2026-09-27 - Parallel nightly fills (T7)

The unattended batch dispatches oldest ready applications to up to 1-4 workers based on max_parallel_fills, copying the current RunContext into each. One daily batch owns the Apply browser operation lock; each synchronous Playwright worker opens its own CDP connection and new tab, while the upload lock serializes file attachment and the submit pacing lock rechecks caps immediately before a click. Pause stops dispatch and is passed into each fill so in-flight forms hand off without submitting. The extension relay continues serially because its selected-tab, single-connection model cannot provide independent tabs. The verified engine currently hands off for review rather than auto-submitting, but its attachment upload uses the same lock.

## 2026-09-27 — Keyword job-search source (Adzuna + USAJobs)

Added `job_search` source kind with providers `"adzuna"` and `"usajobs"` to allow keyword-based searches across any industry.
- `schemas.SourceConfig` supports `kind="job_search"`, `provider` ("adzuna" | "usajobs"), `query`, `location`, `country` (default "us"), and default `max_age_days=14`. Existing schemas still validate unchanged.
- `apply/discovery/job_apis.py` implements bounded paging (up to 5 pages), polite delay (`JOB_SEARCH_DELAY_SECONDS=1.0`), timeouts, and injectable `get` callable. Results map to `sources.SourceRow` with stable `adzuna:<id>` and `usajobs:<MatchedObjectId>` keys, recency derived from timestamps, and formatted salary when present.
- Factored shared `sources.matches_filters` helper to reuse `include`, `exclude`, and `locations` keyword filtering consistently across `ats_board` and `job_search`.
- Missing API credentials (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `USAJOBS_API_KEY`, `USAJOBS_EMAIL`) raise `MissingCredentialsError` and are recorded per-source by `run_daily` in `summary.errors` without crashing the run.
- Configured savable credentials in `config.SAVABLE_CREDENTIALS` and updated frontend UI (`providers.ts`, `ModelsSection.tsx`, `SourceEditors.tsx`, `ApplySettingsDrawer.tsx`) with sensible labels, documentation links, inline missing-credential alerts, and drawer "Add a keyword search" integration.
- Deviation: none.

## 2026-09-27: Apply tables sort by posted date

The Found column became Posted. No stored field held a posting date, but `age_days` is the age on the day a row was found, so posted = discovered_at - age_days reconstructs it for every existing row without a migration. Sources that state a date now carry it (`SourceRow.posted_at`, then `Application.posted_at`), and a re-sighting fills an empty one. Greenhouse lists `updated_at` first; that stays the age-filter input (a repost reads as fresh), while `first_published` is the posted date. Rows with no age (`age_unknown`, extension captures) fall back to the date found, marked `~` in the UI, because a posting is never newer than when we found it. Date-only values render through `localDate`, since `new Date("YYYY-MM-DD")` is UTC midnight and showed the previous day west of UTC.

## 2026-09-27: SmartRecruiters screening step

The one-click form's second page (`/screening`) filled nothing. The generic pass did see its controls, but every label read as "*": the question text is slotted (`[slot=label-content]`) into a `<label>` inside the control's shadow root, and innerText of that label omits slotted nodes. The Yes/No `spl-radio`s have no native input at all, and the `spl-autocomplete` selects list their options only after ArrowDown. `smartrecruiters_flow.fill_screening` reads each `[data-test=question-container]` itself, keys the question with `workday_flow.key_for_label` (salary by its unit; graduation month/year split from one date), then a remembered answer, and picks options with `field_matcher.closest_option`. Declarations and the privacy consent are never ticked; a question with no profile answer is listed for review, never guessed. The page's `definition` attribute carries every question with its options (72 KB); the fixture drops it and keeps the select options in `screening_options.json`. "How did you learn about" now maps to `how_heard`.
2026-09-27 - Apply table actions now dispatch selected fills up to max_parallel_fills and prepares up to max_concurrent_jobs. Extension mode and pause-on-blocker stay serial; same-group prepares run in selection order. Each worker records in_flight progress, while the legacy current fields mirror the most recent activity. Submit slots are reserved before fill and returned unless submitted; pause holds new dispatch only.

## 2026-09-28: One decision layer for questions (`apply/answers/questions.py`)

The fill reports for 7 applications (Quora and Ramp on Ashby, AbbVie and RRS on
SmartRecruiters, GCM on Greenhouse, Atlassian on iCIMS) showed the same four weaknesses in
every fill path.

1. **Controls were scanned instead of questions.** Ashby's name-less radios became one
   "Unrecognized field" per option.
2. **Keying took the first regex hit on the label, with no type check.**
   - "Is your cumulative GPA 3.0 or above?" was keyed to major.
   - "Have you uploaded your transcript?" was keyed to school.
   - "Requesting visa sponsorship?" lost to "work authorization".
3. **No answer was derived.** AbbVie's "currently enrolled?" and "degree by June of next
   year?" follow from the graduation date.
4. **Selectors were not unique.** Ramp's Phone was filled with the school.

Patching each site would have piled up per-site branches. The fix is instead one layer
that every path calls: classify, then answer, then choose. Workday, SmartRecruiters and
the generic filler now call it. The generic filler reads questions in scan mode and fills
from `plan_for`'s plan.

**Why the model did not answer AbbVie's questions.** The SmartRecruiters screening path
called no model, and `hybrid_resolver` only runs on blockers (a required field left
empty, or an invalid one). Letting a model answer eligibility questions would be unstable
across runs, so the split is:

- **The model classifies.** `answer.classify_questions` returns a key from the closed
  `MODEL_KEYS` list, cached by wording, and only for choice questions no rule keys.
- **Code answers.** The value is always computed from the profile.

The derived rules alone answer AbbVie's two questions without any model call.

**Other fixes in the same change:**

- A date picker gets MM/01/YYYY, because a typed "2027-06" landed on May 31st.
- Greenhouse's `start-month--0` combobox is keyed by id and date part.
- "If other…" and "If yes…" follow-ups take no fact.

**iCIMS** never clicked "Apply for this job online". The footer language `<select>` made
the wizard read the posting page as the form, and filling that one select reported
"ready for review". Now:

- A posting page with at most 2 inputs and an Apply control is still the posting.
- `WizardAdapter.enter` clicks that control once.
- A fill that sees only unlabelled chrome hands over with `NO_FORM_MSG`.

The regression corpus is `tests/fixtures/forms/{ashby_quora,ashby_ramp,greenhouse_gcm}.html`
with `tests/apply/answers/test_question_pipeline.py`. The captures were sanitized: example.com emails and
555 phone numbers.

## 2026-09-27: A parallel fill adopts only a tab its own page opened

**Symptom:** in a batch Fill of ~20, some applications failed with "No application form
controls detected" while their real form tab sat open and unfilled. Two applications
recorded the same `browser_target_id` (GM Financial and Goldbelt; ZipRecruiter and CHS).

**Cause:** `max_parallel_fills` (default 2) runs fills against one browser context. After
clicking Apply, `fill._click_and_track_popup` waited on `context.expect_page()`, which
fires for any new tab in the context. A fill whose Apply navigated in place adopted the
tab the other fill had just opened with `context.new_page()`. `workday_flow._new_tab` and
`WorkdayAdapter.enter_application` diffed `context.pages` and had the same race.

**Rule:** a fill follows only a tab whose opener is its own page: `page.expect_popup()`,
or `opener() == page` when diffing `context.pages`. Playwright takes the opener from CDP's
`openerId`, so `rel=noopener` links are still followed (browser test). Real-Edge
regression tests are in `tests/browser/test_apply_controls.py`: a sibling page opens a
tab while the click is in flight. The shared claimed-tabs registry discussed as a guard
was dropped. A foreign tab has no opener or another fill's page as opener, so the opener
check already refuses everything the registry would.

## 2026-09-28: a Workday prompt results list closes with Tab
CACI rows failed: the Skills results list (promptLeafNode rows) covered the Add buttons. A prompt list has no click_filter and ignores Escape (verified live on Cencora), so close_stray_popups now presses Tab when focus is in a prompt search box. The chip list (role=listbox, data-automation-id=selectedItemList) is always visible and no longer counts as a popup. Also seen: a narrow Edge window (~710px) makes Workday render responsiveMonikerPrompt variants; an expired session leaves such a prompt aria-busy forever.
2026-09-28: OpenAI-compatible sync and async calls retry HTTP 429/500/502/503/504 with bounded backoff. Exhausted Autofill errors are recorded on the step ledger and named in the handoff when required answers remain.
## 2026-09-28: School email and year-only Workday text

Classify school-issued email separately from personal email so a missing school address is reported as a blank profile fact. Format availability date parts from the question label and replace stale text in date-part inputs, preventing values such as 142027.

## 2026-09-28: duplicate spellings in a prompt search are one answer
American Century School search returned "University of California, Irvine" and "University of California-Irvine"; normalize() makes them equal, so match_option returned ambiguous and School stayed blank. Now the exact spelling wins, else the first of distinct spellings; identical labels remain a tie. Cencora "How Did You Hear = LinkedIn" (hierarchical list: Job Board, Social Media, ...) is still open: the tab session expired (prompts stay aria-busy), so the category tree could not be captured.

## 2026-09-28 — Workday "applyManually ... element is not stable" under parallel fills

- Started with 43f78df (parallel fill tabs, `max_parallel_fills` = 2). A background tab gets
  its animation frames throttled by Edge, so Playwright's "stable" actionability check never
  passes while the start dialog animates in. A longer timeout would not help.
- `workday_flow._follow_href_or_click`: Apply / Continue and Apply Manually read the link's
  own `href` (no actionability check) and `page.goto()` it, resolved with `urljoin` against
  `page.url`. A missing, empty, `#` or `javascript:` href falls back to `clicks.safe_click`.
  `_new_tab` still returns the same page when no tab opened, so in-place navigation is safe.
- The Edge launch command (`frontend/src/lib/browserCommand.ts`, the `apply/driver/browser.py` CDP
  hint, README) now adds `--disable-background-timer-throttling
  --disable-renderer-backgrounding --disable-backgrounding-occluded-windows`, so the
  remaining click paths in background tabs are not throttled either. Edge must be restarted
  with the new command for these flags to take effect.
- Pre-existing and environmental, not caused by this change: test_config::test_local_ollama_needs_no_key,
  test_estimate::test_local_and_unknown_models and test_setup_status::test_checklist_reports_each_prerequisite
  fail on a clean tree on this machine; the setup-status one hit a live ollama.com request.

## 2026-09-29 — Consistent Workday answers: rules first, one answer per question

Live run (5 Workday tabs, gemini-3.5-flash-lite as the Autofill model). Two American
Century postings asked the same ~20 questions and ended with *different* blanks. Causes,
none of them sampling (temperature is already 0 on every backend, `llm.py`):
- `questions._DERIVED` read "current or former" anywhere as `previous_worker`, so the
  non-compete question ("...with a current or former employer?") took that key instead of
  `noncompete`. Now "former" must be followed by employee/worker/intern/contractor.
- The "worked for any of the listed firms?" checkbox group (Grant Thornton / FORVIS /
  Deloitte / No) was self-identification-only in `fill_choice_checkboxes`; it is now
  answered from the applicant's employers (`_previous_employer_options`: a listed firm
  they worked for, else the one "No").
- Salary range dropdowns were answered by nobody: `_BLANK_EXEMPT` skips salary in the
  rule pass and the resolver reserves salary from the model. `salary.pick_range` picks the
  option with the most overlap with the applicant's range (min .. min(posted top, own top));
  `salary_fields` now also emits `<key>_low_number`. Needs >= 2 range-looking options.
- The resolver's model call returned a list of actions and could silently omit controls;
  every control was then marked asked, and the step was called "cleared" because Workday
  shows no error before Save. Now the prompt demands one decision per control ("unknown"
  allowed and final), an omitted control is sent once more alone (`_MAX_ASKS`), a choice
  that did not stick is retried once, and "skipped but still blank" keeps the loop going.
- Choice answers are remembered in `CACHE_DIR/resolver-choices.json`, keyed by prompt
  version + `config.fingerprint("answer")` + profile digest + control type + normalised
  label + options (not packet fields, so one employer's postings share answers). A tab
  that meets a question another tab is asking right now waits for that answer
  (`_IN_FLIGHT`, per question — unrelated questions never wait). "unknown" is not cached.
- "How Did You Hear About Us?" (Cencora): sources exist only under categories, so no
  search finds "LinkedIn". Source questions (`_ANY_OPTION_KEYS`) now take the option naming
  the profile's value, else "Other...", else the first, walking categories
  (`select_prompt_any`; `any_option` for listbox dropdowns).
- CACI: one experience row's From month/year stayed empty (data was a normal 2025-03).
  `fill_date_sections` typed into whatever held focus and read back only at the end; it now
  focuses the input, reads each section back, and retypes once (a partial "0" is retyped).

Considered and rejected for the resolver: Jev (hosted API: applicant PII to a third
party) and Laya (local, deterministic encoder, but its base checkpoints are near chance
zero-shot on typed decisions per its own model card; would need fine-tuning on our own
question/answer pairs, which `resolver-choices.json` could later supply).

## 2026-09-29 — Workday skills: Enter already committed the lone result

American Century's Enterprise Data Intern fill added every skill and then removed it again. On
a real Workday multiselect, Enter on a search with a single result commits that result as a
chip immediately and keeps the option listed, ticked; the click `fill_skills` then made on
that option *toggled it off*. `_search_prompt` is now followed by `_entered_chip` (the one
chip that appeared during the search): the right skill → recorded, no click; a wrong one
(e.g. "PyTorch Lightning" for "torch") → `_drop_chip` takes it back off and it goes to the
near-miss judge like any other. `_click_option` also accepts only a +1 chip change that
includes the option, so a toggle-off is never counted as a commit.

Same tab: the listed-firms `-CheckboxGroup` fieldset holds only the boxes, and the question is
the enclosing `formField-` legend. `CHECKBOX_GROUPS_JS` read a blank question, skipped the
required group, and the wizard never left page 1, so the page-2 graduation date was never
reached. The legend now falls back to the form field. `salary.pick_range` ties (60k–80k
against "$60,000 - $70,000" / "$70,000 - $80,000") go to the band holding the applicant's
top, which matches the number answered everywhere else.

## 2026-09-29 — User-managed sources and the complete extension

- **Sources are fully user-managed, per profile.** Built-ins became catalog entries; any source
  can be removed, and an explicitly empty list stays empty (the old legacy-field synthesis only
  ever fired for a hand-written `sources: []`, so it was removed rather than flagged).
- **Catalog is remote-refreshable from this repo's `main`**, bundled copy as fallback, never
  auto-applied to a user's settings — the SPA offers an update when the catalog version is newer.
  Repo names roll over each season (`Summer2027-` → `Summer2028-`); `scripts/refresh_source_catalog.py`
  proposes the new URLs after parsing them. jobright-ai lists are daily rolling windows and still
  carry a `2026-` prefix; their links open jobright.ai rather than the ATS.
- **Pre-catalog sources are linked on load** (`_link_catalog_sources`) only when id *and* url match
  a bundled entry. The SPA's `runState` defaults and older app versions saved them without a name
  or `catalog_id`, so they showed raw ids and could never be offered updates.
- **A pasted github.com link is mapped to the raw README** (`sources.raw_readme_url`); fetching the
  GitHub page itself returned HTML whose `<table>` markup the Simplify parser misread as a
  600-row job table with no categories (seen live on zapplyjobs).
- **Keyword `query` is comma-separated phrases** (max 5), each its own search — users read the
  old single-string field as a list because of its placeholder.
- **LinkedIn/Indeed are capture-while-browsing only.** No background fetching with the user's
  session (account-restriction risk and ToS), no auto-clicking through cards. Search cards become
  `capture_stub` items completed when the user opens each job. Email job alerts were considered
  and declined by the user.
- Live-verified in a browser against an isolated data dir: Sources tab, catalog add, per-source
  Test (Simplify 1412 rows; Adzuna two phrases 412 rows), README link inspect. LinkedIn/Indeed
  live capture still needs a pass with the user logged in (checklist: docs/GUIDE.md §2.4).

## 2026-09-29 — Stale desktop page; Sources tab regrouped by type

- **The desktop window kept showing the previous release's UI after an update.** The window signs
  in via `/?t=`, which 303'd to `/`, and index.html had no Cache-Control, so WebView2 reused its
  heuristically cached copy; the old hashed bundles it references are never deleted from
  `server/_internal/frontend/dist/assets`, so the stale page worked perfectly. Fix: the redirect goes
  to `/?v=<version>` (a new cache key once per release; the SPA strips it), index.html / SPA
  fallback are `no-cache`, hashed `assets/*` are `immutable`. Takes effect from the release after
  v0.2.9 with no manual step.
- **Sources tab regrouped** after the user found it unintuitive (search engines invisible until
  adding one, identical rows, no health). Three always-visible groups; Adzuna/USAJobs connected once
  per provider (keys never inside a search); identical rows with a ⋯ menu for every source;
  side-panel edit with autosave; Undo toast instead of confirm; per-source health from
  `source_status.json` (`found`/`kept` counted after filters, before known-id dedupe).
- The row's on/off control is a drawn pill inside a full-size button: the global 36px control floor
  in `index.css` is unlayered, so a Tailwind `h-5` on a `<button>` rendered a circle.

## 2026-09-30 — Job sources moved to their own page; one panel and one filters block for every kind

- **Why**: the Sources tab sat beside the application tables it has nothing to do with, and a walk
  through the running app showed inconsistencies: "+ New Adzuna search" opened a dialog (Add
  button) while an existing search opened a side panel (autosave); search phrases were chips but
  titles/locations were comma boxes; job lists had no filters and no way to add your own list
  except a paste bar at the bottom.
- **Page**: `/applications/sources` (`pages/apply/SourcesPage.tsx`), opened from Apply settings
  ("Job sources →") and the Manage link beside Find jobs. `?tab=sources` redirects there.
  Applications lost its fourth tab.
- **One panel**: `SourcePanel` has `mode="new" | "edit"`. Edit autosaves as before; new holds a local
  draft that only `onAdd` saves (Cancel drops it). The three add dialogs are gone. Same body for
  every kind: name, what to read, `FiltersEditor`, test. A watchlist needs a company and a search
  needs a phrase before Add.
- **Filters for every kind**: `include` / `exclude` / `locations` / `max_age_days` on `SourceConfig`
  already existed for watchlists and searches; `sources._apply_source_filters` now applies the first
  three to README rows in `fetch_source_rows`, so job lists get them for the nightly run and the
  test. `ChipInput` is the one list input (comma, paste and Backspace); `WordsField` is deleted.
- **Adding a list**: "+ Add job list" opens the catalog with a paste-a-link field on top (README
  first, then careers page). The bottom paste bar is gone.
- **Test result says why**: `SourceTestResult.dropped` (too_old, title, citizenship, advanced_degree,
  no_sponsorship) and `max_age_days`. The old "596 found · 3 kept" hid that Apply's 1-day limit
  did it.
- **Stale health**: a "requires credentials"/"needs <KEY>" failure recorded before the keys were
  saved shows as "Keys saved since the last run" once the provider is connected (the block said
  Connected while its row said needs ADZUNA_APP_KEY).
- **Not a bug**: the panel's Close button "timing out" under Playwright MCP was the automation tab
  being in the background (`requestAnimationFrame` never fires, so Playwright's stability check
  hangs); `evaluate`-driven clicks work. No Modal change was made.

## 2026-09-30 — Apply attention and mistaken submitted marks
Needs you sorts by the latest status timestamp, so recently changed rows appear first. Apply operations and nightly runs retain one latest attention outcome per application with the real failure or hand-off reason and a review-tab link. Restoring a submitted/skipped Done row now undoes that mark using its last non-terminal status; undo_terminal is the only bypass of set_status's terminal guard, and an explicit undo route covers already-restored rows.

### 2026-10-01 — Self-healing Workday rows/dates; Ashby preset date selects
- Ashby education month/year `<select>`s arrive set to today (Ramp: both dates stayed 9/2026);
  `filler.js` kept them as the applicant's answer. A select keyed `education_start_month` /
  `graduation_month` whose value differs from the planned option is now overwritten (education
  dates come only from the master resume).
- Workday: an Add press that showed no single new row silently dropped the entry
  (AmerisourceBergen rows 4–5). `_recover_row` uses an unclaimed blank row rendered late, else
  closes popups and presses Add once more. Progress line only — no review line (user: review
  lines push work onto the applicant).
- Workday dates: `_fill_date_retrying` retypes with `page.bring_to_front()` when keys did not
  land (Invesco: concurrent fills in one window), logging `document.hasFocus()` to confirm the
  cause; `_recheck_dates` re-reads every filled employment date after the section and retypes.
- Not fixed: the post-Continue scroll lock (Motorola/Invesco). Esc does not clear it, so the
  2026-09-25 stray-popup theory is incomplete; needs a live-tab CDP probe.
- iCIMS (2026-10-02, from runtime reports): saved JDs were nav chrome only — the description
  lives in `icims_content_iframe` (src = job URL + `?in_iframe=1`, server-rendered, same
  origin), and the app's HTTP fetch got `405 Not Allowed` because iCIMS rejects a Chrome
  User-Agent from a non-browser client (default httpx UA and `Mozilla/5.0` get 200).
  `fetch_jd._fetch_icims_content` fetches the iframe document with default headers and
  `extract_fragment_text`, before the generic path; any miss falls through unchanged.
  The browser fallback still reads only the top-level `innerText` (not changed).
- iCIMS fills stopped at the `/login` email step: the "I agree" privacy box (`#accept_gdpr`,
  inside the iframe) was an "Unrecognized field", so `required_empty` blocked Next
  (H&R Block, Lutron, TRC ×2, Atlassian). `_FillAnswers._accept_consent` now ticks a required
  consent checkbox leftover (`form_routes.is_required_consent`/`tick_consent`; marketing,
  job-alert, talent-community and arbitration boxes excluded) on iCIMS only, via `clicks`.
  The Workday consent path is page-level and never reached the iframe.

## 2026-10-02 — "Ask the AI" panel on the application Answers tab

- `POST /api/jobs/{id}/answer` gained `context`, `full_resume`, `regenerate`; defaults keep the
  MCP call identical. The panel always sends `full_resume=true`: every master-resume bullet plus
  an **allowlisted** set of profile facts (`answer_facts.SAFE_PROFILE_FIELDS`: location, work
  authorization, sponsorship, start date, education). Never contact info, salary, EEO, credentials.
  Allowlist, not denylist, so a profile field added later stays out until named.
- Typed context and profile facts are a **trusted guard source**: `check_claims(extra_sources=…)`
  appends one synthetic bullet, like `_resume_context_bullet`. Anything else the model invents is
  still discarded after one retry. Autofill (`answer_question_async`) is untouched.
- Prompt version 3. The applicant-facts rule is appended to `_SYSTEM` only when context or facts
  are sent, so the legacy prompt is byte-identical; context and facts are in the cache key.
- Copy-only: nothing is written to answer memory (a typed, company-specific answer would
  otherwise pollute autofill). Needs a succeeded run: JD and requirements come from it.
- Employer naming fix (all answer paths): `check_claims` only took names from resume text, so
  "Why do you want to work at Acme?" drafts naming the employer were discarded after the retry
  (autofill, MCP and the panel alike). `AnswerExtras` (company / facts / context) now carries the
  application's employer into the prompt (`<employer>`) and the guard. Only the name: the
  posting's products and technologies are still blocked, so JD tools never become claimed skills.
- The answer route pins `config.ONE_OFF_PROFILE` when a run has no `backends.json` (CLI-made
  runs) instead of falling through to the claude fallback.
- The panel offers the last fill's open written-answer questions as chips
  (`frontend/src/lib/askQuestions.ts`): outcome `unanswered`/`manual_review` on a text control.

## 2026-10-02 — iCIMS email step: typed by hand, Next found in the frame

- Corgan's iCIMS fill stopped after filling the email: `_find_advance_button` searched only
  the top page, and iCIMS's Next sits in `icims_content_iframe`. `_FillWizard._advance_button`
  now falls back to `wizard.form_scope(page)` (renamed from `_target`).
- Pressing Next after the filler's script-set email sent the tab to hCaptcha, then to iCIMS's
  central Auth0 login (`login.icims.com/u/login/identifier`, cookie
  `icims_prompt_login_redirect` with `loginOnly=1`) for an applicant with no iCIMS account.
  The same email typed by hand in the same tab opened `/candidate?from=login&eem=…&code=…`
  (the new-candidate profile). The step's invisible hCaptcha scores how the box was filled.
- `IcimsWizard.type_email` clicks the empty email box (via `clicks`) and types it with
  `press_sequentially` (trusted key events, 80 ms/key) on the portal's `/jobs/.../login`
  step only, before the scan; the filler then keeps it as an existing answer. A half-typed
  box is cleared so the filler fills it instead. No CAPTCHA is solved or bypassed: a
  challenge that still appears is the applicant's.
- `IcimsWizard.classify` names any `login.icims.com` page `sign_in` (the shared rules read its
  one visible box as a form); its handoff tells the applicant to sign in or, with no account,
  type the email on the posting's own step. Fixture `icims/central_login` is captured text.

## 2026-10-02 — iCIMS email step: handed to the applicant (supersedes "typed by hand")

- Live re-test in a fresh context of the fill Edge: the email typed with real key presses
  (`press_sequentially`), consent ticked, Next clicked in the frame, and hCaptcha still
  raised an image challenge. Typing was not the signal; the likely one is the automation
  session attached to the tab (the applicant's own Next, with the fill finished, passed).
  `type_email` was removed. Getting past or hiding from the check is out of scope.
- `WizardAdapter.applicant_step(page)` (None by default) runs in `_wizard_gate` after
  `stop_for`. `IcimsWizard` returns an `awaiting_review` Stop on the `/jobs/.../login` step
  when its form frame holds `.h-captcha` / an hCaptcha iframe (Corgan: 3 matches in the frame,
  none on the page), before anything is typed. A portal email step without hCaptcha is still
  filled and advanced; Continue fill after the applicant's Next lands on `/candidate`.
- Kept: Next found in `wizard.form_scope(page)`, and `login.icims.com` classified as `sign_in`.

## 2026-10-07 — Workday: step identity without step names (narrow window)

- **Every Workday fill stopped on My Experience with no rows.** The Edge fill window was
  ~695 CSS px. Below ~800px the progress bar keeps only `current step N of M` (checked
  live on Magnite, Midland, Expedia, P&G); `active_step()` stripped that, so every step
  read `""`. Save and Continue compared `"" == ""` → "wizard did not advance" → handoff,
  and `_workday_rows` (gated on `"experience" in active_step`) never ran.
- **Fix, replacing the name checks rather than adding a layer:** `step_key()` (the
  `N of M` position) drives advance detection in `wait_for_step_change` and
  `_step_unchanged`, so a mid-step resize is not a step change. `active_step()` falls back
  to the step's own heading (`step_title`, first visible `h3` in `applyFlowPage`), which
  narrow layouts keep. `is_review_step` also accepts `N == M` (Review is always last).
- **The rows gate is gone:** `workday_repeaters.fill` runs on every non-Review step and
  returns silently when no Work Experience / Education / Languages section is present;
  the per-section "skipping" messages remain for partial steps. The verified engine's
  `fill_education_years_async` gate was dropped too (a no-op without `schoolName` rows).
- **Rejected:** forcing a wider window (a guard, not a fix); matching heading text
  variants (Workday's section headings are platform defaults).
- Not verified in a full live fill yet — needs a desktop rebuild.

### 2026-10-07 — Fill watchdog: a stuck browser call no longer holds a worker forever
Magnite (op 5c6c59f2) blocked inside the Workday Skills loop at 23:07:40 (second chip committed, never logged) and held its worker 13 min past its 4-min deadline until the server restarted; Khan stalled 5 min alongside it. No exception, no model calls, heartbeat alive: a Playwright call that never returned. The fill deadline is cooperative (checked between steps) and `page.evaluate` / locator reads take no timeout, so nothing could interrupt it and nothing recorded where it was. `driver/watchdog.stall_guard` (wrapped around `_FillRun.run`'s connected body) watches from a side thread: `GRACE_S` (120s) past the deadline it logs the fill thread's stack to app.log, then kills that fill's Playwright driver process (`driver_pid` reads it from the sync Browser's transport — a private attribute, None-safe). The blocked call raises "Connection closed while reading from the driver"; the fill ends `fill_failed` with handoff_reason "fill stopped responding" and an error naming the innermost resume_tailor frame. Dropping a CDP client never closes Edge or the tab, so the applicant's progress stays. Verified against a separate headless Edge: a never-resolving evaluate was released 3.1s after the guard fired, the browser kept running. The verified (async) engine is not guarded.

## 2026-10-07 — Completed education picker and autofill sources

**What:** `highest_education_obtained` now offers standard levels plus Other while retaining its string storage. Completed/highest education questions use the live profile; questions explicitly permitting a current degree and education history rows retain resume sources. Blank and unmatched completed facts are reserved from cached/custom/model fallbacks.
**Why:** A future resume degree is not evidence that it has been completed. Shared education-group helper text must only qualify degree/level labels, not School or Graduation Date (Quora); current-or-most-recently-completed wording must remain valid (Resultant and Fidelity).
**Impact:** Old packets receive the current value at Fill time, including clearing stale values. Exact/alias/grouped-option matching preserves distinctions such as GED versus diploma and broad Bachelor's versus a named BS/BA. Legacy profile text remains unchanged and appears under Other when unfamiliar. The desktop backend and frontend must be rebuilt together for installed fills.

## 2026-10-08 - Catalog levels, finance/consulting boards, search presets
**Decision:** Catalog entries gain optional `levels` and `tracks` (plain strings, unknown values dropped on load) instead of new `SourceField` values, so an older build still validates the remote `main` catalog and saved `settings.json` fields stay valid. `intern`/`new_grad` were previously only implied by entry ids. The catalog dialog filters by field, level and focus (OR within a group, AND across groups); onboarding preselection skips `job_search` entries because they return nothing until an API key is connected.
**Watchlists:** every board was read live with `boards.list_board` before it was listed (`banking.json` and `consulting.json` are new). Most large consultancies (McKinsey, BCG, Bain, Deloitte, PwC, EY) and several banks answer 404/422/401 or an empty board, so they are not listed; Wells Fargo, JPMorgan, Goldman and KPMG Workday sites returned 422.
**Search presets:** Adzuna and USAJobs accept no level parameter, so a preset fills only query phrases plus title `include`/`exclude`. New-grad searches set no `include` because entry titles ("Investment Banking Analyst") carry no level word. Word-start matching made `intern` keep "Internal Audit Analyst"; `source_watchlists._WORD_START_EXCEPTIONS` fixes that with a negative lookahead.
**Impact:** Seven new catalog entries (four Adzuna finance/consulting searches, two USAJobs Pathways searches) need API keys. No new community README lists were added: the only finance list found that parses (drewdavis0302) was already there.

## 2026-10-08 - Filters for every source
**Decision:** Global keep/skip/location words (`ApplySettings.source_filters`) are *added* to each source's own words (add-on, not override), merged once in `source_filters.with_global_filters` right before `fetch_source_rows`, so `source_keyword_filters` and every fetch path stay unchanged. A source can only narrow with skip words and locations; `ignore_global_include` is the one opt-out (keep words only). The Job sources page shows a "Filters for every source" tile above Job lists, in the Tailor Options-tile pattern (DataList summary, Change/Done in place); source panels show global words as locked chips (`ChipInput` `locked`) via `EverySourceContext`, and open at the Apply-settings width (`Modal size="lg"`).
**Posting age:** kept the existing rule (a source's own `max_age_days` only widens the funnel-wide one) rather than the mockup's "source replaces global", because replace would shrink watchlists under Find's catch-up window. The global age control moved out of the Apply settings drawer into the tile.
**Eligibility:** `exclude_no_sponsorship`/`exclude_citizenship_required`/`exclude_advanced_degree` and `eligibility.hard_reject_years`/`flag_years`/`extra_text_block` got UI for the first time, in the tile; a source shows them read-only. `extra_title_block` stays without UI (global "Skip titles" covers it). Block entries are regexes, but the UI saves plain words, so `eligibility._block_hit` falls back to a literal match when an entry is not a valid regex ("C++").
**Migration:** a `mode="before"` validator on `ApplySettings` hoists words every source shares (case-insensitive intersection, ≥2 sources) into `source_filters` when the key is absent; union semantics keep each source's effective filters identical.

## One-click browser: the app starts it (2026-10-08)

- The copy-paste launch command (per-OS tabs in the Apply drawer, `frontend/src/lib/browserCommand.ts`)
  is gone. `apply/driver/browser_launch.py` starts the browser chosen in
  `ApplySettings.browser` (Edge/Chrome/Comet; `None` = first installed, Edge first) whenever
  `cdp_browser`/`async_cdp_browser` or the nightly batch submit find the port closed.
- Subprocess launch + CDP connect, not Playwright `chromium.launch()`: a launched browser
  carries automation markers (`navigator.webdriver`, infobar) and closes when the connection
  drops. Started detached (Windows `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, breakaway
  from a job when allowed; POSIX new session), so it outlives the app.
- Firefox excluded: Gecko no longer exposes CDP. Comet is Chromium.
- "Browser in use" is not a blocker: the dedicated `--user-data-dir` runs a separate instance.
  The real blockers, reported as `state: unavailable` + `reason`: not installed, port held
  by another program, the ResumeTailor profile already open without the port (a launch
  that times out, remembered per browser). Never kills a process.
- Host-side default `CHROME_CDP_URL` is now `http://127.0.0.1:9222`; the Docker image sets
  `RESUME_TAILOR_IN_DOCKER=1` and keeps `host.docker.internal`, and the UI shows a one-line
  manual flag note only there. Tests set `RESUME_TAILOR_BROWSER_LAUNCH=off`.
- Fill buttons are enabled when the browser is `ready` or `idle` (it will launch), not only
  when connected (`browserUsable` in the SPA).

### 2026-10-09 - Greenhouse autofill gaps

- Added a blank/Auto high-school graduation year, derived from the earliest dated undergraduate start, with a saved override. High-school year questions precede School and match explicit offered year bounds.
- Programming-language checkbox groups use the complete master Skills list, distinguish C/C++/C#, and preserve existing selections. Grade level uses class standing; relatives use the declared Yes/No without inventing names.
- Routine privacy/data/read notices require the acknowledgement preference. Certifications, signatures and other commitments remain manual. Saved answers and model fallback cannot bypass these decisions.
- Phone Country resolves the declared region beyond the first visible options and verifies its committed option. Known dates retry resume facts; resolver cache identity includes packet facts, full Skills, option punctuation, help text and resolver version.
- Transcript inputs use their enclosing upload question rather than Attach, select the transcript artifact, and verify/preserve its filename. Successful final scans replace stale missing-field lists; scan failures block readiness.
- Continue repairs prior automated dates only when the current value still matches that automation; manual edits are preserved. Both fill engines share these facts and scoped checks.
- Regression fixtures reconstruct the observed DOM without applicant data; local browser tests cover both engines. Live Chrome rechecking remains pending because CDP was unavailable. Work is isolated in fix/greenhouse-autofill.
- Validation: 1,501 Apply/API tests and 440 frontend tests passed; the frontend built and the frozen sidecar passed its startup/health/UI/shutdown smoke check. Ruff reported no new diagnostics in changed lines; repository-wide lint and a targeted type check retain existing baseline failures.

### 2026-10-09 - Find never tailors; nightly run never submits

- Find jobs (`run_daily(fetch_only=True)`) now fetches each JD and runs the no-LLM prefilter, leaving rows `jd_fetched`/`screened_out`/`needs_browser`; the user chooses what to Prepare. It previously stopped at `discovered`, except that `_join_group` let a same-role sibling of an untailored primary fall through to extraction and tailoring (fixed; a dry-run sibling no longer writes either).
- The nightly run discovers, fetches, screens and tailors only the postings it found itself; rows waiting from an earlier Find are left alone (`_process_one(include_known=False)`; `_rows_to_process` no longer sweeps pending `discovered` rows). Prepare still carries a known row on (default `include_known=True`).
- The nightly run never fills or submits: `_run_batch_submit`, `operations.batch_browser_owner`, `run_daily(auto_submit_max_per_run=)`, `apply_daily.py --max-submissions` and the summary's submit counters are gone. Auto-submit lives only in Fill, which still honours `auto_submit_*` (the per-run cap now reads "per Fill" in the UI).
- Since it never submits, the scheduler dropped the 12 h catch-up window / "missed" day (`missed_today`) and the automation-pause gate: a due run starts on the next tick however late.

## Double majors on application forms (2026-10-11)

A double major stays one education entry on the resume (one school, one date line, the
combined degree line). Forms are different: a repeatable education row usually takes one
field of study. `packet_fields.education_rows()` expands an entry with 2+ majors into one
row per major (same school/dates/degree, `entry_key` suffixed `:i`). It is used only where
rows repeat: the Greenhouse adapter's numbered rows, Workday's education repeater (rows are
matched on school + major, so each major claims its own row), and SmartRecruiters'
`fill_education`. Single-answer questions keep `packet.education` (first major in `major`;
every major in `majors`). Considered and rejected: storing majors as separate resume
entries — it prints the school and dates twice.

## Screen coverage matches the tailor report (2026-10-11)

Apply's "Coverage" and the run report's "Required skills covered" count the same thing
(must-haves among the master resume's known skills) but disagreed (7/10 vs 6/9 on one
posting): screening extracted the JD with `known_tags` lacking inferred skills, the tailor
job with them (`tag_infer.prepare_run` first). `known_tags` is in the extraction cache
key, so the job missed the screen's cache and re-read the posting; the second vote dropped
a must-have. Screen threads also read the process-wide `bullet_tags` annotation of
whatever tailor job ran last. Now `daily._resume_skills` (once per Find/Prepare) joins any
`skill_refresh`, runs `tag_infer.ensure` under Light routing, and passes the inferred map
to `bullet_tags.known_terms(resume, inferred)` without installing it (`prepare_run` would
clear a running job's context). `screen()` takes that list as `known_tags` and counts
with the report's rule. Rows with a run show the report's figure
(`daily_rows.adopt_run_coverage`: on tailor success and reuse; `daily.sync_run_coverage`
at startup for older rows). "Force fresh results" still extracts twice (rejected:
passing the screen's requirements into the job — more plumbing for a rare setting).

## Prepare Pause/Cancel stop tailoring at once (2026-10-11)

Pause and Cancel used to wait for every in-flight Prepare item (multi-minute tailor
jobs) to finish, and the banner lost "Pausing…" under the next progress event, so both
read as dead buttons. Now, during Prepare, both set `operations._HOLD`. Each item polls
it between stages (`_RowRun._stop_point`) and every 0.5 s while waiting on its tailor
job (`_wait_for_job(should_stop=…)` cancels the job). It raises `PrepareInterrupted`,
and `prepare_application` puts the row back exactly as it was (`store.restore`). A
paused item goes back on the front of the dispatcher's deque and runs again from the
start on Resume (LLM caches make that cheap). A cancelled item isn't counted as failed.
`control()` sets `state="paused"` itself, so the reply flips the banner immediately. A
model call already running still finishes before its thread unwinds. Fill keeps its old
behavior: Pause waits for the form in progress. The SPA reads pending Pause/Cancel from
the whole event list (`pendingControl`), not the newest event. Also,
`resume_review.state` skips rows that are mid-Prepare
(discovered/jd_fetched/screened_in/tailoring): their `job_id` names a run that has no
quality report yet, which used to flash "Resume needs review". The selection bar now
splits rows in two: Tailor files gets rows without files, failed tailors included;
Tailor again gets rows with files (`canTailorFiles` / `hasTailoredFiles`).

## Faster Apply batch prep on Ollama Free (2026-10-11)

Ollama Free serves one request at a time (3 parallel extraction calls: 13.2s wall vs
12.5s sequential), so batch time is the sum of every model call. Telemetry showed ~18
calls per Apply item, a third redundant. Changes:
- **One shared JD extraction.** Screening extracted without the profile guidance, which
  is in `jd._slug`'s fingerprint, so the tailor job hit the extract cache in 2 of 48 runs.
  Screening now extracts under `web.job_routing.tailoring_guidance` + `tailoring_context`,
  the same snapshot `JobQueue.submit` captures. Default extraction is one read
  (`EXTRACT_CONSENSUS_RUNS = 1`; see pipeline-and-guards.md).
- **Cover letters at fill time.** Prepare wrote a letter for every item (2 calls each;
  266 of 268 gemma letters failed the old 300–380 band even after the retry). Whether a
  posting asks is only known in its form (Workday shows it pages in), so Fill writes one
  via `cover_on_demand.ensure` only for a required cover-letter upload with Apply's switch
  on; an optional field is left empty (`not_requested`, not a readiness blocker).
  `preparation.check` lost `require_cover` and `missing_configured_cover_letter`.
- **Near-empty postings** (47 of 292 runs) are still tailored, with the run warning
  `jd.THIN_POSTING_WARNING` (text < 1,200 chars or no keywords). Not a resume-review
  warning, so it never blocks Fill.
- Model bake-off on 3 postings (full runs, medians): gemma4 70s / 0 fallbacks;
  gpt-oss:120b (low) 94s / 6 fallbacks; nemotron-3-super (no thinking) 139s / 13 invented
  skills dropped; nemotron-3-nano 157s; gpt-oss:20b (low) 183s. Qwen cloud models are
  retired (410/404); deepseek/glm/kimi/mistral/minimax need a paid plan (402). gemma4
  stays the default.

## Cover-letter choice in Apply settings (2026-10-11)

The on/off `ApplySettings.cover_letter` became `cover_letter_mode`: Off / Required only
(default) / Required and optional / Every application. One four-way setting rather than a
switch plus a choice, which could contradict each other; old settings migrate (true →
`required`, false → `off`). Only `every` writes in Prepare — the user's trade: about 15–30s
per batch item for a faster Fill and a letter readable before it is sent. `optional` writes
during Fill and fires on most Greenhouse/Lever forms (their optional upload). Text boxes
follow the upload rule (owner's call), so a "Cover letter" textarea gets the letter, not an
Ask-AI draft. A letter written during Fill does not hold auto-submit (owner's call;
Workday never auto-submits anyway). Under `off`, a letter already on hand (an older
packet, a Tailor-tab run) is still used for a required field.

2026-10-12 - Table Prepare no longer serializes rows that share a posting group (same company + role, other locations). Each selected row is already in the store, so `prepare_application` takes the `_merge_known` path and never reuses a sibling's run; the wait only cost a slot (4 selected, "Preparing 3 at once"). The nightly `daily_batch` keeps its group order: `_join_group` reuses the first row's tailor run there.

## 2026-10-12 — Workday fills under parallel batches: one per site, vault lock, overload budget

From three live Fill runs (ops 390ef872, 11b1a1ae, d348b8dc; 10 Workday tabs handed back or crashed). Most causes trace to `max_parallel_fills` (2026-09-27) meeting code that was only safe serially.
- **One fill per Workday site** (`funnel/fill_hosts.py`, used by `operations._dispatch_items`): two Aptiv postings filled at once both pressed Create Account. The dispatcher now takes the next pending row whose Workday host is free; other sites still run side by side. A site whose new account ends `awaiting_otp` hands the rest of that site's batch back at once (needs_input, not filled) instead of spending a Sign In that can only fail until the email link is clicked.
- **Vault**: `_save_vault` wrote a fixed `workday_vault.tmp` and crashed a parallel fill with `[Errno 13] Permission denied`. Writes go through `infra/atomic.write_text` (unique temp + retried rename; `packet.py` and `operations._save` share it), and `_vault_entry` holds a lock across read→generate-password→save so two fills can never mint two passwords for one site.
- **Model overload vs the 240s budget**: Gemini returned 503 on 5 of 9 calls; GlobalFoundries spent 69s in Skills retries and hit the limit silently. Root bug: `llm_telemetry.Client` had no `__setattr__`, so `client.timeout = <remaining budget>` stopped at the wrapper and the real client kept `LLM_TIMEOUT` (900s). Fixed; sync `_post` now treats `timeout` as the whole call's budget (attempt time + backoff). Skills model window capped at 45s; an HTTP 429/5xx there sets `model_unavailable` and the progress line names it. The deadline break now logs a progress line. No automatic Heavy→Light fallback (user declined hybrid routing earlier).
- **Events**: the global `events[-100:]` let one chatty fill erase a parallel fill's whole history (NVIDIA had none). Now the last 60 per application plus every operation-level event, 400 max.
- **Slow auth step** (Itron, ~23s to paint Create Account): after Apply Manually, a still-loading shell gets up to 25s more, bringing the tab forward halfway, before the "did not open" handoff.
- **Answers**: long direct "Who is your current or most recent employer?" labels map to `current_company` (the >60-char short-field guard stays for labels that merely mention an employer); talent-pool consent ("data … for other job opportunities", "talent community") is a new `talent_pool_consent` key answered **No** (user decision); Phone Device Type picks the single personal mobile option ("Personal Cell", "Mobile - Personal"); language levels know Poor/Fair/Good/Very Good/Excellent and Low/Medium/High and break a same-rank tie by the option naming the answer. BD's real language options and NVIDIA's phone options were not captured live (desktop app still running); confirm on the next live fill.
- **Citizenship stop** (user decision): CMU SEI said "requires a U.S. Department of War Security Clearance, which requires citizenship" only in an Application Question, never in the JD. A visa-holder fill that sees a form statement that the job *requires* citizenship/clearance stops and marks the row `screened_out`; a plain "Are you a U.S. citizen?" does not. JD block patterns now also match across a line break or non-breaking space.
- Not changed: `cmu:2025200` vs `cmu:2025200-1` stay separate (a `-N` suffix can be a real separate requisition).

## 2026-10-12 — Round 2, phase 1: deterministic answers from the v1.8.2 rerun (op c9f64ef1)
- **Required notices are agreed by default** (user decision): `auto_accept_routine_acknowledgements` now defaults True, labelled "Agree to required notices and consents". `form_facts.acknowledgement()` returns `routine` (privacy, background check, restricted-party screening, accuracy certification, terms, arbitration, signature: agree), `fact` (a declaration stating something about the applicant, e.g. "I confirm I am authorized to work": falls through to the fact keys, never agreed blindly) or `optional` (marketing/SMS/alerts/talent pool: No). `form_routes.consent_candidates` ticks every required non-fact notice; only optional opt-ins are excluded.
- **Typed consents**: `form_facts.typed_consent` fills a text box with the quoted word ("Type 'I AGREE'", "select \"Yes\""), the full name for an e-signature, today's date beside it. Only when the box is a routine notice and the setting is on; "If none, type 'N/A'" is never a token.
- **New fact keys**: `us_person_status` (citizen/permanent resident -> Yes), `us_citizen`, `citizenship` (profile country of citizenship), `government_employee`, `conflict_of_interest` (new profile bools, default No), `export_control_country` (No unless the citizenship is a listed country). Government/military service never reads as `previous_worker`; "receiving compensation" in a conflict-of-interest question is no longer salary.
- **How did you hear** (user decision: never blank, never a person): named source -> generic online (job board/online/website/social/LinkedIn) -> Other -> career fair/campus -> first impersonal option. Workday tries only the profile value, then `any_option`.
- **Languages**: a language the form's list lacks (Magnite: Vietnamese) deletes the row this fill added (`workday_rows._delete_row`, the row's Delete button inside its `role=group` panel) instead of leaving an empty required row; a level pick is retried once after 600ms (Itron English).
- **Authorization by country**: `ApplicantProfile.authorization_countries` (list; old `authorization_country` mirrors the first). A posting clearly in another country is answered authorized **No**, sponsorship **Yes** (was: left for the applicant). `job_country` reads Canadian provinces, "Remote in USA", multi-place " | " lists, and Tbilisi, Georgia as the country.
- **School-only postings**: "<X> University (Students) Only" / "open only to students of X" screens out as "Other school only" unless X is the resume's school.

## 2026-10-12 — Round 2, phase 2: fill robustness
- **Progress-extended deadline**: a fill starts with 240s (`fill_outcomes.BASE_BUDGET_S`); every forward-progress line (`fill_outcomes.is_forward_progress`: a scanned step, a filled row, an added skill, an upload) pushes the deadline to at least now + 75s, never past 600s from the start. Both engines; the verified engine's outer `asyncio.timeout` is the 600s cap. `fill_application(on_deadline=...)` reports each extension and `operations` moves the item's `deadline_at`, so the UI countdown follows. Workday skills get max(120s, 6s a skill) within the cap (Workday ML had 24 skills).
- **Continue reopens a closed tab** (user decision): instead of "Review tab was closed. Use Reopen and fill", Continue logs "Review tab was closed; reopening the posting (Workday restores the saved draft)" and takes the reopen path. The SPA offers Continue whether or not the tab is open; "Reopen and fill" is renamed **Start over** and its toolbar button is secondary.
- **Parallel fills** moved out of the auto-submit fieldset into its own "Filling" section: it was disabled whenever auto-submit was off, though it applies to every Fill.

## 2026-10-12 — Round 2, phase 3: model limits, Heavy->Light fallback, AI tile
- **429s are logged and acted on** (`infra/model_queue.rate_limited`, every response passes): a 429 logs its body (300 chars) with Gemini's quota id and `retryDelay`, halves the endpoint's effective limit (min 1; +1 after 20 successes in a row), and cools it down. A per-day quota id, or 3 cooldowns within 2 minutes, marks the endpoint used up (`exhausted_for`; retryDelay else 10 min): `llm` then fails fast with `LLMError(status=429)` instead of three backoff retries, and stops retrying a 429 once the pool is used up. `_retry_delay` honours a body `retryDelay` up to 60s when it fits the call's budget.
- `LLMError.status` carries the HTTP status; `llm.unavailable(exc)` (429/5xx, also an Anthropic SDK `status_code`) replaces the `HTTP (429|5xx)` regexes.
- **Heavy -> Light during Fill** (`apply/answers/model_fallback.py`): `ApplySettings.fallback_selection` mirrors the Light task model (`JobSettings._shared_heavy_model`). `_FillState.answer_pin()` replaces the `config.pinned(model_spec)` sites; it pins Light when Heavy's endpoint is used up, and `model_fallback.call` retries a failed Heavy call once under Light, after which the fill stays on Light. One progress line: "Heavy model is at its limit (HTTP 429); answering with Light (<model>)". Verified engine: same via `acall`.
- **One operation notice**: a fill handed back as "autofill model unavailable" adds one `model_limit` event per operation; at the end of a Fill those applications get one Continue fill if the Heavy endpoint is no longer used up (counters adjusted so they count once).
- **Plan per model** (`ModelSelection.plan`: free / paid / subscription / local; None = Gemini free, Anthropic/OpenAI paid, else the queue's local/cloud default) sets the endpoint's default concurrency (1/4/2/1); a saved per-server limit still wins. Read from `ai_settings.json` by mtime.
- **AI tile**: Advanced is a switch in the AI models tile header (Settings only) revealing effort, posting reads, request speed and resumes at once inside the tile (`AiAdvancedCard` removed). Each row has a Plan select, a custom server's format and URL inline (its key stays in API keys), and a chip "At limit, resumes HH:MM" / "Quota used up" from `/api/model-queue` (`roles` maps each task model to its endpoint).

## 2026-10-12 — Location policy for Find (work types + countries)

Postings outside the applicant's countries were only filtered by free-text `locations`
words, so Belfast/Toronto rows reached Prepare. `apply/discovery/posting_location.py`
(pure) splits a row's location on `|`/`;`, reads each place's countries through
`packet_profile_fields.location_countries` and its work type (hybrid > remote > on-site >
unknown, unknown counted as on-site). A posting passes when any place passes. New
settings: `SourceFilters.work_types` (all on), `countries` (empty = the profile's
`authorization_countries`), `other_countries` (default **True** — the user can get
sponsored anywhere; those applications already answer "not authorized / needs
sponsorship" via `authorization_mismatch`), and per source `keep_unknown_remote` (True).
Applied once per source in `daily_batch.by_location` right after the fetch (not inside
each fetcher), and in the Test-source route so its preview and `dropped["location"]`
match Find. A place naming no country is never dropped on country grounds.

## 2026-10-12 — Answer book (one store, learns from the page)

Four answer stores (answer_memory corrections, `resolver-choices.json`, profile
`custom_answers`, the classifier's file cache) were invisible to each other and the user
barely used them; answers typed on the page after a handoff were never kept. Migration 3
rebuilds `answer_memory` with `kind`, `options_digest`, `action`, `canonical_key`,
`options`, `profile_digest`, unique on (kind, label_norm, ats, options_digest).
`answer_book.import_legacy` (marker `answer_book_import_v1`) imports the resolver file
(options_digest = the old choice key, so picks keep matching exactly) and moves custom
answers (profile-field ones fill the blank field; backup in `backups/custom_answers-*.json`;
the profile field is then cleared). The resolver still shows the model custom answers
(`hybrid_resolver._model_profile` reads them from the book), so the profile digest — and
every cached pick — survives the move. Deviation from plan: AI picks stay keyed on the
whole-profile digest; the model does not say which profile keys it used, so per-key
invalidation would be a guess. Plain `recall` reads only kind 'answer' rows with no
options_digest; with `options` it returns the offered option's wording or nothing.
Learned types: `LEARNABLE_TYPES` excludes authorized_to_work, sponsorship*, noncompete,
previous_worker and EEO keys; forgetting a type also deletes its classifier cache file.
Harvest (`funnel/answer_harvest.py`) saves only questions the fill left (field_outcomes in
unanswered/ambiguous/invalid/manual_review/failed, leftovers, required_empty), never fields
it answered (those are corrections), never passwords/files/checkboxes/`review._PROTECTED`
labels, and never logs values. The background pass only reads tabs `/json/list` shows open
(never launches a browser), skips tabs in `answer_harvest.FILLING`, is off in extension
mode, and exits when nothing is watched. Tests stub `collect`/`watch` in conftest.

## 2026-10-12 — Workday questionnaire dates and Continue on Review

Workday's required Expected Graduation Date uses hidden month/day/year spinbuttons, which the generic text scan skips. `workday_dates.fill_question_dates` classifies the whole label through `questions`, fills it after other answers finish rendering, and verifies every section; a failed background attempt gets one retry with the tab in front. The existing month-precision convention supplies day 01. Missing month, conflicting partial manual dates, and unrelated dates are never guessed; complete manual dates are preserved. Reconciliation checks every section rather than treating a filled month as a complete date.

A Continue fill already on Workday's read-only final Review page is allowed through the no-controls guard only when the final step was independently recognised. Attachment checks and submission policy still run. Live reproduction fixtures contain an empty date field and a review snapshot with no personal values. Validation: 683 nearest forms/ATS tests, focused date/review regressions, and the live six-tab check with auto-submit off. The Settings browser test was also updated for the existing inline custom connection controls and Advanced switch; desktop and mobile cases pass.

## 2026-10-13 � Application answer policies, experience, dropdowns, and manual submissions

Apply settings now owns Answering questions preferences: required notices/consents, an explicit broad minimum-qualification declaration, and consideration for other positions. Storage remains in the applicant profile for compatibility. Advertising-partner sharing is declined; ordinary factual questions containing marketing/SMS words are not treated as opt-ins. Information-source answers try only saved-source equivalents, then Other. Student/recent-graduate answers use all dated education intervals, including six calendar months for recent graduation.

Profile > Application has an experience-basis selector: Experience, Experience+projects, Experience+projects+education, or custom years. Calculation unions overlapping calendar intervals, clips ongoing periods at today, excludes undated evidence with visible reasons, and uses the raw subtotal for range matching. Both general hands-on and professional experience questions use the selected basis; technology-specific questions remain separate.

The DoorDash posting used an optional cover-letter field and Required only correctly skipped it. Upload evidence and progress now retain the operation's cover-letter mode and the skip reason; fallback file scans retain required metadata. The failed custom location dropdown previously bypassed direct profile facts and reached an SDK Timeout coercion crash. Known location facts now bypass the model; selected location and telephone-country options are verified, including countries sharing +1. HTTP timeout bounds preserve SDK phase limits and disable provider retries within the resolver deadline.

Retained application tabs are observed after restart, including extension mode. Explicit confirmation must match the posting/requisition; Workday candidate-home evidence requires a dated matching row and rejects explicit unsubmitted states. Recording uses an atomic re-read, preserves later terminal decisions, and checks the originating workspace under the workspace-switch lock. A shared relay lease makes background observations skip foreground connections, while foreground fills wait for a bounded observation to release it. Submission observation never clicks a submit control.

Validation: 3,532 backend tests passed (two skipped), 641 frontend tests passed, plus focused headless regressions for the final split-day/range/dropdown/relay fixes. The desktop sidecar was rebuilt, smoke-tested (READY/health/UI/exit), installed with a preserved 1.9.0 shell and a rollback server folder, and checked through its authenticated API. Explicit answer preferences were saved through the existing profile API with other fields preserved. Installed screen checks covered widths 320-1280. The observer requires the recorded browser tab to remain connected; it does not launch a browser or infer submission from a disconnected tab.

## 2026-10-14 — Apply list speed; expansion only where a fill pastes it

**What:** `GET /api/applications` reads `store.rows_view()` (the cached rows, uncopied, read-only) instead of `load_all()`, and list rows carry only the fill fields the table reads (`browser_target_id`, `handoff_reason`, `missing_profile`, `error`); the detail endpoint keeps the full fill. `upsert` refuses a cached row. Prepare writes the experience expansion only for `preparation.EXPANSION_ATS` (Workday, SmartRecruiters) via `_job_settings(..., ats=)`; `preparation.check` asks for it only there. Workday fills a missing description from the resume bullets, as SmartRecruiters already did. The application Files tab gains Generate/Regenerate for the expansion and cover letter (`ArtifactsCard`); `POST /api/jobs/{id}/expansion?force=true` skips the expansion cache, and the cover-letter route rebuilds `packet.json` so Fill pastes the new letter (`cover_on_demand` already rebuilt its own).
**Why:** Profiled against a snapshot of the live registry (861 rows, 6 MB): SQL fetch was 15 ms but `load_all()` deep-copied every row on every poll — 928 ms cold, 360 ms warm, 1.4–2.4 s for the review group, whose 564 KB body was 452 KB `fill`. After: 143 ms cold, 40 ms warm, 229 ms review group, 145 KB. Stored rows are copy-on-write (`_merge_into`/`_write` build new rows and swap the dict), so uncopied reads are safe while nothing mutates them; the deep copy stays the default for every other caller. Only Workday (476 rows) and SmartRecruiters (18) fills read the expansion, so ~43% of expand calls produced unused text.
**Impact:** Rows on other ATSs no longer wait on, or pay for, an expand call. A row misdetected as non-Workday still fills Workday's description (bullets). Regenerating an expansion for an older run uses that run's saved backend snapshot, including its recorded effort.

## 2026-10-14 — Rows stay in their table while a task runs; row-click selection

- `store_models.list_group` decides Needs you vs In progress for both group filters
  (`store_views.list_applications`, `GET /api/applications`). A row in `RUNNING_STATUSES`
  (filling, tailoring) takes the group of the last non-running status in `status_history`, so
  Retry/Fill on a Needs you row no longer moves it to In progress and back. No history → working.
  Tab counts cover the rows listed (running ones included). The extension's "needs you" list and
  `review_summary` stay on real `REVIEW_STATUSES`: a running row needs nothing from the user.
- Leaving a table drops the row from the selection (already done by `useApplicationTable`'s
  "gone from this exact view" prune).
- Frontend: click anywhere on a row / tap a card selects it (`lib/rowSelection.ts`), Shift-click
  ticks a range taking the anchor's state, Esc clears. Controls, links, `noRowSelect` columns,
  portals (row menus) and text highlights never toggle. The selection bar is always shown
  ("0 selected", actions disabled) so ticking the first row never shifts the table. Drag-select
  was rejected: it fights text selection and touch scrolling; Shift-click covers 10–20 rows.

## 2026-10-16 — Manual-submission detection, careers-page entry, tab clean-up

Verified on live reruns (12 apps, 4 parallel, twice) and by replaying `confirmation()` on real URLs.
Only 7 of the 14 submissions that day were auto-detected.

- `submission_monitor.confirmation`: `boards.greenhouse.io` and `job-boards.greenhouse.io` are one
  site (Point72/Anduril were saved on the first, applied to on the second). A Workday
  location-variant key (`R5054820-2`, from the URL tail) also matches the bare id the page shows
  (`R5054820`); the base must contain a digit, so `R-01418` is never read as `R` + variant.
  `identity.canonical_key` is unchanged: dedupe keeps location variants separate on purpose.
- `answer_harvest`: the loop ticks every 2 s on one `/json/list` call (`browser.open_targets`), reads
  a tab at once when its URL changed, keeps the 20 s full pass, and closes a submitted/skipped
  application's tab after a 30 s grace. Loop exit and `_THREAD = None` share one lock (a `watch`
  racing the exit could otherwise be dropped).
- Tabs: a fresh (initial/reopen) fill closes the application's previously recorded tab. 27 retained
  tabs had the fill browser at 8.4 GB (2.1 GB after closing). `browser.close_target` never closes in
  extension mode (that tab is the applicant's own). `tests/conftest.py` stubs it suite-wide: the
  developer's live fill browser listens on the default port.
- `fill_buttons._enter`: when the Apply click is intercepted (Qualtrics' Phenom chat widget) or does
  not leave the page (Capgemini/Royal Caribbean SuccessFactors dropdown toggle), follow the
  control's own same-site `href`. A `SubmitRefused` is never bypassed by the link.
- No-form guard: nothing filled and every control "Unrecognized field" (a careers page's search box,
  "Save job"), no required-empty fields, not Workday → `NO_FORM_MSG`, not "missing answers".
- Not fixed, diagnostics only: Workday "stuck on unknown" on location variants of an already-applied
  requisition (signed-in state; not reproducible signed out). `fill_entry` now logs the screen's
  automation ids + URL (never text). Dropped as not reproduced: 60 s navigation timeouts, unread
  dropdown options, concurrency as the cause of stops.
- Amended same day after the live check: following the toggle's `href` on SuccessFactors sites
  redirects to the site home. `_enter` now first clicks a newly visible "Apply" `menuitem` (the
  dropdown's "Apply Now" → SuccessFactors sign-in/create-account), follows the `href` only
  without one, and returns to the posting if the link bounced to `/`. Live: Capgemini →
  create-account form, Royal Caribbean → sign-in, Qualtrics → application form.

## 2026-10-17 — Autofill correctness fixes (Phase A of the autofill review)

From two outside reviews of the Apply pipeline, checked against the code and 255 live fills. Each
is a bug against an existing rule, not new policy.

- Written answers (`fill_answers._answer_one_long_text`): the model call goes through
  `model_fallback.call` (Heavy → Light on a limit), and any other error costs that one question:
  a progress line, plus `"<label>: could not draft an answer"` when it is required. Cancellation
  and the fill deadline still stop the fill. With Heavy and Light both on one model, the per-field
  catch is what matters.
- Review flags carry their reason (`"<label>: shortened to fit the form's limit"`, the policy of
  "Fill edge cases (P4-E)" E18), so `_reconcile_observed`, which drops bare labels the form now
  shows filled, never clears them.
- Profile switch vs Apply: `activate_workspace` refuses while `apply_operations.active()`, inside
  `template_ops.LOCK`; `operations.start` and `start_review_action` hold the same lock from their
  first workspace read through registration and thread start. Apply workers read the
  process-default workspace (threads do not copy the `RunContext`), so a switch mid-fill mixed
  profiles.
- Progress redaction: `answer_memory.shown(label, value, key=)` hides values of self-ID/credential
  questions (`_EEO_KEYS`, `is_sensitive`) at the Workday/SmartRecruiters progress call sites, and
  `operations._event` runs `answer_memory.redact` before the message reaches any persisted field.
  `fill.json` keeps filled values; the review panel needs them.
- Readiness (`filler_readiness.js`) now returns `{required_empty, invalid}`: a visible control
  with a value that fails native `validity` (not `valueMissing`) or carries `aria-invalid="true"`.
  Before handoff those are focused, changed and blurred once (a stale marker from before the value
  was typed clears), then re-read; any still rejected becomes `"<label>: the form rejects this
  value"`, so `ready_to_submit` is false. Not the planned `resolve_step_blockers(only_invalid)`
  pass: the resolver only sees empty dropdowns/radios, never a filled text field.
- Continue tab identity (`identity.retained_tab`): the kept tab's URL against the posting, final
  and last recorded tab URLs. `different` (another requisition on the same ATS, or no requisition
  and off every known site) → the tab stays open untouched and the posting opens in a new tab;
  `unknown` (no requisition id, same site: Workday sign-in/step pages) → continue. Workday's
  `/apply/<step>` tail hid the id (`canonical_key` fell back to `_R123`, dropping `-2`); the check
  keys the posting part. Checked on 281 recorded end-of-fill URLs vs the posting URLs alone: 3
  cross-site redirects read `different`, 0 with the last tab URL included (as Continue does).
- Stale uploads (`upload_replace`, legacy engine only): upload records carry `uploaded_by_app` and
  `artifact_sha256`. On a later fill, the app's own file under the same name with a changed
  document is replaced (native input: `set_input_files`; listing widget: its own delete control,
  `clicks` purpose `remove`, found inside the upload component only, stopping at any other kind of
  form control so a work-experience row's Delete is never pressed). Removal failing → reported, not
  uploaded twice. Seen only off its step (Workday Review) → reported, not verified. Anything else
  attached is `kept_existing`, including records from before these fields existed. UI:
  "uploaded and verified" / "uploaded by an earlier fill" / "kept the file already attached"
  (`lib/attachmentState.ts`). The plan named `ApplicationReview.tsx`'s "Verified / preserved"
  group; that label is for fields, attachments render in `AttachmentResults`.
- Per-run auto-submit cap counts `submit_unconfirmed` too, and a fill that raised after storing
  its pre-dispatch `submit_unconfirmed` record; `operation.submitted` stays confirmed only.

## 2026-10-17 — Notice detector, model tie-breaker, resolver basis (Phase B of the autofill review)

- `form_facts.acknowledgement(text, help_text)` reads every statement: "optional" (any opt-in,
  including ones worded as acknowledgements and opt-outs), "fact" (a claim or question about the
  applicant), "routine" (every statement in the applicant's voice is process language; a caption
  with none must name a document or process), else "unclear". Callers agree only on "routine".
  Help text is read apart from the caption, and its questions are not put to the applicant.
- Unclear notices go to one batched, cached model call (`answer.classify_notices`, prompt v3) only
  when routine acknowledgements are set to auto-accept; "process" -> routine, anything else or a
  failed/misaligned reply -> never agreed. A field's caption ("Confirm your password", "Applicant
  Signature") is never sent (`needs_reading`): v2 of the tie-breaker read such captions as notices
  and agreed to them (dev 0 -> 8 unsupported agreements, held-out 2 -> 7).
- Claim statements on a checkbox or choice are answered as worded (`questions._as_stated`): one
  negation flips the profile's answer, a qualifier or double negation leaves it for the applicant.
- Resolver actions cite `basis_kind`/`basis_key`; `resolver_basis.supported` checks the field has a
  value, the question is about it (the decision layer does not key it elsewhere; label patterns),
  and the option says it (GPA ranges, fluent languages, Hispanic origin named in a race option).
  Picks are saved only once on the page; the question stays in flight for other tabs until then.
- Gate (`scripts/evals/notice_eval.py`, wording only / with the tie-breaker): dev 288 cases 0
  unsupported agreements, 1 handoff / 0, 1; held-out 80 cases 2 unsupported (1 opt-in, 1
  not-a-notice), 6 handoffs / 2, 4; the old detector 30 unsupported, 4 handoffs. The held-out set
  was consulted three times as per-category aggregates while widening the detector (its texts and
  ids never read), so its numbers are optimistic. Bar was 0 unsupported, handoffs <= old + 2.
- Resolver replay (`scripts/evals/resolver_replay.py`, 54 distinct stored AI choice questions):
  11 applied, 36 rejected by the check, 7 "unknown"; all shown applied answers matched the profile.
  Most rejections were unsupported guesses (a previous application answered from "relatives at the
  company", on-site work from relocation, a basis of "unknown"); they become review lines.

## 2026-10-17 — Follow-up repairs from an outside review of Phases A and B

- Notices: a later clause with no subject of its own continues the applicant's statement and is
  read as "I ..." ("I agree to the terms and possess a passport" is a claim). The clause split also
  breaks before claim verbs (hold, possess, meet, reside, speak, require, plan...). Dev 295 cases 0
  unsupported / 1 handoff; held-out unchanged at 2 / 6, 2 / 4 with the tie-breaker (a fourth
  aggregate-only consult).
- Resolver basis: a resume skill answers only a plain ask about that one skill (`_SKILL_ASK`:
  "Do you have experience with X?"), never negated, joined with another skill or qualified by a
  setting. A profile/packet fact answers a Yes/No question only when it is not negated and joins no
  second question or "and a/an ..." requirement (`_as_worded`); "if not", "with or without" and
  "or not" are not negations. Multi-option questions are exempt: negation there sits in context
  ("this is not a guarantee of placement"), and both stored labels it hit were of that kind. 0 of
  the 54 stored choice questions are refused by the new rules. A general and/or rule was rejected:
  16 of 35 stored Yes/No labels contain and/or, almost all alternatives or context.
- `model_fallback.call/acall`: once Heavy is down, later calls in the same pinned block go to Light
  straight away (Fill pins once around all of a step's written answers).
- A fill that raises after the submit click keeps `submit_unconfirmed` (noted `auto_submit`, so the
  caps count it); before the click it is still `fill_failed` (`_FillState.submit_dispatched`).
- Retained-tab identity compares the employer's tenant/board too (Workday ids repeat across
  tenants); embedded Greenhouse (`gh_jid` off greenhouse.io) has no reliable board and matches on
  id. No verdict changes on the 281 recorded end-of-fill URLs.
- A failed upload replacement keeps the old file's ownership and digest (`upload_replace.still_ours`),
  so the next Continue retries instead of keeping it as the applicant's.
- Readiness reads a checked checkbox/radio and a filled Workday dropdown marked aria-invalid as
  rejected. Only the checked box is read or revalidated: a change event on an unchecked radio can
  select it (Vue's v-model listens to change). A dropdown's review line uses its label, never the
  aria-label, which carries the chosen value.

### 2026-10-17 — Multiple-choice fact answers read what the question says to pick

A second outside review pointed out that what decides is what a negation modifies, not how
many options there are. The earlier repair skipped multiple-choice questions, so a profile
answer to "Choose the office locations where you cannot work" took the preferred office.
`resolver_basis._to_pick` now keeps only the sentences that say what to pick (a "?", a
select/choose/pick/indicate/exclude verb, or one that starts with which/what/where/check/list).
If none does, it keeps the whole label. It also drops negated "If ... not ...," fallbacks and
the options' own words. `_as_worded` checks negation and `_SECOND_ASK` against that text. Yes/No
questions still read the whole label, since the answer affirms or denies all of it. The help
text is not read, the same as for Yes/No: Self-ID help often says "you may choose not to
answer". `_NEGATED` gains cannot (it never matched `\bnot\b`), unable, unwilling and exclud….
Over the stored labels (read only), it refuses 1 of 16 multiple-choice questions, an AI-review
opt-out that no profile fact answers, and 0 of 36 Yes/No. The harmless shapes are kept as
regression tests.

### 2026-10-18 — Autofill on more sites, Batch 1 (deterministic)

Measured with `scripts/evals/fill_probe.py` (eval-only). A made-up applicant fills 25 of the
owner's unsubmitted postings in a throwaway data dir behind a request guard: requests that
carry the applicant's details, uploads and unreadable bodies are aborted; service workers and
WebSockets are blocked; every request is audited. The runs are read-only (no typing) and live
(`awaiting_review`, never submitted; Workday/iCIMS/Oracle are read-only only). The baseline is a
frozen worktree of the pre-change commit, run twice for noise.
- Social-apply routes ("Apply with LinkedIn", "Continue with Google") are refused by the click
  guard for every purpose (`clicks.SocialApplyRefused`). The entry finders skip them and try
  the next match (`fill_buttons._entry_control`, `wizards._ENTER_JS`).
- `_find_submit_button` matches `clicks.FINAL_SUBMIT_NAME` (Jobvite's "Send Application"); each
  such name also reads as a submit to the guard.
- `wizards.GenericScreens` gives sites with no adapter the applicant's own screens on clear
  evidence only: sign-in (a password box, ≤4 other fields), create account, a code control
  (≤3 other fields; page text alone never counts: Eightfold's privacy text), closed (0
  fields), already applied. It never reports posting, review or confirmation.
- `ats_fingerprint` re-checks the platform after entry: its own host or path alone, or two
  agreeing page signals. The stored `Application.ats` only moves from other/unknown to an
  existing `AtsKind`; eightfold/avature/jibe live in `fill.json` diagnostics only, since a new
  `AtsKind` would make older apps fail to read the row.
- `identity.lost_posting`: a posting URL naming a job that lands on its careers root stops the
  fill as closed.
- `fill.json` gains `diagnostics` (additive: app version, posting/landed platform, end
  category, elapsed, model calls via `model_queue.count_requests`) and `corrections`.
  `corrections` are labels and keys only, for answers the applicant changed on the page.
- Labels (`filler.js`): a fieldset legend is used only when the fieldset holds this question
  alone (Pinpoint's "3.Questions" legend over every question). `labelOk` makes UI words,
  ids, bare section headings and an option's own text give way to the next source (Rippling's
  aria-label "Search"). Unrendered rows and dropdown placeholder lines are dropped (Lever's
  "No location found", Paylocity's "Select a state"). JazzHR's self-named Yes/No checkboxes
  under one label are one question; consent boxes are not grouped. `label_parity.json` holds
  every form fixture's labels.
- Noise: Greenhouse's `requiredInput` (aria-hidden, tabindex -1, beside one visible dropdown)
  is that dropdown, and its required flag moves to it (12 blank required questions on one
  form). Honeypots are never filled or reported; ≥4 one-character boxes are one
  "Verification code". Readiness skips the stand-in the same way. The Ashby split checkbox
  group was not reproduced in any capture, so it is unchanged.
- Rules: GPA ranges, graduation terms ("Spring 2027"), class standing and "Class of" year
  options pick the one option the fact fits, else none (`question_options`). A June graduation
  fits Spring and Summer, so it is left. Also new: Address 1/Line1, Postcode, Full (legal) name
  (never a reference's, a signature or a name in another script), bare Source, "How did you
  first learn about", and I-9 "documentation that proves your eligibility". Mined from 1,321
  stored leftovers (labels only).
- `EEOAnswers.sexual_orientation`, default "decline" like the other self-ID answers, with a
  Profile select. Bot checks ("If you are an AI, include ...") are never answered by rule or
  model; they leave "This looks like a bot check; answer it yourself".

### 2026-10-18 — Batch 1 follow-ups from an outside review

- **Final button vs guard:** `clicks.SUBMIT_TEXT` now holds every `FINAL_SUBMIT_NAME` body (`_FINAL_NAME`), so a name the finder takes as the final button ("Complete my application", even with `.btn-next`) is always refused as an advance.
- **Bot checks:** `filler.js` sends a written-answer box's help text and required flag with `long_text`; `_answer_one_long_text` checks for a bot check before the cover-letter route. The required flag also fixes protected long texts never reaching review (it was always missing).
- **Code boxes on platform adapters:** `wizards._CODE_INPUTS_JS` is shared by both snapshots; the base `classify` reports "otp" for a code control with ≤ 3 other fields, so Oracle/iCIMS/Taleo/SuccessFactors see split code boxes too.
- **Readiness honeypots:** `filler_readiness.js` skips the same honeypots as `filler.js` (`honeypot`).
- **Corrections signal:** a label asked or filled more than once is never paired (the fill record and the page's fields share no identity); `_same_answer` compares numbers as amounts, digits as phones and number sets only for dates ("3.7" ≠ "7.3").
- **GPA:** "At least / Minimum of" are inclusive lower bounds; "At most / Up to" inclusive upper bounds.
- **Probe tools (eval only):** the live guard blocks writes carrying the made-up applicant's other answers, GraphQL mutations and save-shaped paths, allowing geocoding lookups; the audit re-checks every request apart from the decision and lists allowed writes. The sanitizer clears embedded `data-*` state, widget selections and known made-up values; `leaks` is a pattern check, not a proof. The read-only probe uses `for_fill`, presses Apply off Workday, and re-checks the landed platform, falling back to the frozen baseline's own decisions. Measurements before this change are not comparable with later ones.

### 2026-10-18 — Batch 1 measured (fill_probe, 25 postings, made-up applicant)

Two runs of the pre-Batch-1 code (4129d56) give the noise; one run of Batch 1. Read-only
runs were sequential; the live Batch 1 run ran beside old-code run B (separate browsers,
reverse posting order), so its time is not comparable.

| Measure | Old A | Old B | Batch 1 |
|---|---|---|---|
| Read-only: questions keyed by rules or model | 116 | 117 | 133 |
| Read-only: required questions keyed | 71 | 72 | 80 |
| Live: answers committed (17 live postings) | 101 | 100 | 109 |
| Live: required questions left | 35 | 36 | 27 |
| Live: steps reached | 17 | 17 | 17 |
| Live: model calls | 13 | 13 | 13 |
| Allowed requests carrying applicant data | 0 | 0 | 0 |

- Live gains: pinpoint1 5→9 (section legend no longer the label), jazz1 0→1, rippling1 5→6,
  ashby1 32→33; lever2 10 vs 9/8 is inside the noise. gh1, sr1, sr2, ashby2, tiktok1 equal;
  gh1 required left 4→2 (dropdown stand-ins).
- Read-only screen fixes: breezy1 sign-in→form (7 keyed, was 1), sr1/sr2 unknown→form,
  avature1 create_account→sign_in (one password box), jibe1 now handled as iCIMS.
- Rippling/Workable: labels are now the real questions, but those are custom dropdowns the
  fill cannot commit yet ("Custom dropdown needs an observed selection"), so read-only
  gains there wait on Batch 2's `widget_actions` work. paylocity1 (15 keyed, 0 committed)
  and jobvite1/2 (0 committed) are open.
- No Workday target in the set: Workday is covered by the test suite only. Steps are flat:
  no live target had a later step to reach. eightfold1 timed out on every run.
- Allowed writes reviewed by host/path: analytics, RUM, bot-challenge and Ashby's
  read-only GraphQL queries only; no form save.

## 2026-10-18 — Batch 2, part 1: custom dropdowns commit, zero-fill postings

- **eightfold1 was the probe, not the fill.** Every run's audit ended on the chat widget's
  WebSocket: the guard's `route_web_socket` handler called `ws.close()`, which deadlocks
  the sync Playwright API, so nothing ran after it. The handler now only records the
  socket and never calls `connect_to_server()`, which keeps it off the network.
  `fill_probe_live.py` writes `<tag>.progress.log` as it goes, so a cut run shows where.
- **Commit check** (`widget_actions._committed_text`): React Select's value, else a
  `role=combobox` input's own value or a div trigger's own text, read only with the menu
  closed (`aria-expanded` not true, no option row showing). Rippling and Workable both
  write the option text into the input and close the menu (probe capture, 2026-10-18);
  the old check returned "" for every `role=combobox`, so a working pick read as failed.
  `_selected_combobox_text` is unchanged (the "before" read and `fill_repairs` use it).
- **Menu ownership**: `aria-controls`/`aria-owns`, then the listbox holding
  `aria-activedescendant`, then the one menu the click opened (handles taken before the
  click); unclear means nothing is chosen. `[class*='-menu']` narrowed to React Select's
  `select__menu` / emotion `css-…-menu`. Rows: ARIA options, `.select__option`, Workday
  `promptOption`, `.oj-listbox-result`, `oj-option`, else a listbox's plain `li`.
  "Loading…"/"Searching…" rows are waited out (≤3 s on open); "No options" rows are never
  options. The search box is the owned menu's, else the trigger (not when read-only), else
  the page's only visible one.
- A failed pick clears search text it typed into an empty input dropdown, and
  `filler.js` reads a closed non-React-Select input dropdown's value as its choice (else
  `_reconcile_observed` dropped committed Rippling/Workable answers). `filler.js` also
  scans `div[role=combobox]` with no input inside (Rippling's Yes/No and EEO questions).
- Phone codes: Rippling lists "+1 US - United States" and shows "+1 US" once chosen;
  `_phone_option` accepts the region's short codes and a "code - name" pair.
- `_load_options` waits for the menu, never caches an empty list, and reads a control's
  options again once another control on the step has been answered since (a State list
  follows Country). Seeded options with no recorded basis count as current.
- **Workable**: a cookie banner lay over the form and every dropdown click timed out.
  `fill_buttons.decline_cookie_banner` presses a refusing button ("Decline all", "Reject
  all", "Necessary only") inside a cookie/consent container, before each step's scan.
  "Accept" is never pressed: Paylocity's OneTrust bar (Accept / Settings / ×) stays.
- **paylocity1**: "Fill out application with my resume" is ticked by default and the
  upload redraws the Information fields blank. The post-upload correction rewrites only
  boxes that still hold a value, so the step ended empty and the read-back found nothing.
  `_refill_emptied` runs the fill once more after a resume upload (filler keeps every box
  that has a value; classifications come from the cache). `_observe_fields` now logs a
  failed frame read instead of suppressing it.
- **jobvite2**: `div.jv-form-field-control` wraps every field, and the "-control" class
  check took each for a React Select box, so the scan saw 0 questions. `reactSelectBox`
  now requires React Select's own class shape or its value/indicator containers.
  **jobvite1**: a "Location of Residence and Language" gate select; the rule picks the
  profile country's English option, else the single all-locations English one.
- Follow-up: the probe blocks uploads, so Paylocity's resume upload was never verified and
  `_upload_one` returned False, skipping the after-upload passes. The form redraws on the
  chosen file whether or not the upload verifies, so `_upload_one` now reports any resume
  file it set. Live spot-check (one run each, same probe): jobvite2 0→10, workable1 →12,
  rippling1 6→8, eightfold1 timeout→13, paylocity1 0→11, jobvite1 0→1; 0 leaks.

## 2026-10-18 — Batch 2, part 2: recovery sees what the filler sees, rescans, evidence waits

- **`forms/dom_common.js`** holds the helpers the three page readers had each copied
  (`rootOf`, `deepQueryAll`, `reactSelectBox`, `TRIGGERS`, `twinOwner`, `hiddenFromPeople`,
  `honeypot`). It is spliced in at a `/*DOM_COMMON*/` marker inside each script's own
  function (`fill_page.with_dom_common`), so it uses that script's `isVisible` and
  `labelFor`. Tests and the frontend test load the scripts through the same loaders.
  `page_blockers` keeps its script inline (one marker) rather than moving it to a `.js`.
- **`page_blockers`** reads open shadow roots, skips honeypots, and reports a filled box
  the form refuses (aria-invalid, or native validity other than empty) in a separate
  `rejected` list: selector, label, help, kind, placeholder and the form's message, never
  the value. `rejected_repair` types the same value again in another shape (phone,
  postal, date; the placeholder's date shape first) and puts the original back when none
  is accepted; a select, textarea or anything else becomes a review note "Label:
  message". The model is never asked about a rejected box.
- The resolver runs on every frame for both the advance and the invalid-blocker passes
  (`_resolve_blockers(frames, only_invalid=...)`), with the ledger's notes going to
  `needs_review`.
- **Rescans** follow a signature of the step's questions (frame, id, label, required,
  options) taken before the scan, not Greenhouse or an "Other" answer: up to 2 extra
  passes when a question appeared or changed. Classifications come from the cache, so an
  unchanged question is never asked again.
- **Waits on evidence**: entry waits for a visible form control or Apply control (then at
  most 2 s of network settle) within the old 10 s; Apply clicks wait for a URL change or
  more controls, with the old 1–1.5 s as the cap; a non-Workday advance waits for the
  step signature to change and hold across two reads, or a shown refusal on the unchanged
  step, capped at 6 s first / 3 s on a retry. An unreadable page falls back to the old
  fixed wait.
- `_observe_fields` keeps a verified pick in an input dropdown whose box shows the chosen
  option while `filler.js` (which ignores typed text in an open box) reads no choice.
- eightfold1's "hang" was the probe's WebSocket close deadlock (`0cbaaa3`), not the fill;
  no `_ms_left` change was needed.

### 2026-10-18 — Batch 2 measured (fill_probe, 25 postings, made-up applicant)

Batch 1 (3b2cb83) twice for the noise, Batch 2 (abf62cd) once. The two read-only runs
of Batch 1 A and Batch 2 ran alone (9.5 / 9.1 min); the rest ran up to three at once on
separate ports and posting orders, so their times are not compared. Totals use the
current probe's counting, not the Batch 1 table's.

| Measure | Batch 1 A | Batch 1 B | Batch 2 |
|---|---|---|---|
| Read-only: questions keyed | 159 | 160 | 190 |
| Read-only: required questions keyed | 103 | 104 | 115 |
| Live: answers committed (18 postings) | 121 | 121 | 159 |
| Live: required questions left | 46 | 46 | 41 |
| Live: model calls | 15 | 15 | 16 → 14 after the fix below |
| Allowed requests carrying applicant data | 0 | 0 | 0 |

- Committed gains: jobvite2 0→10 (and fill_failed→awaiting_review), paylocity1 0→12,
  jazz1 1→9 (the referral follow-up), workable1 9→14, rippling1 6→9, jobvite1 0→1. Ashby,
  SmartRecruiters, Lever, Pinpoint, TikTok and Eightfold equal; gh1 16 vs 17 was noise
  (17 on a rerun). No new wrong screens. Allowed writes are the same hosts in all runs.
- The probe counted every `classify_questions` call, cache hits included, so the
  after-upload refill and the rescans showed as 7 extra calls; the cached question keys
  per posting were identical. The probe now counts only calls that reach the model, and
  records each control's label and type that the resolver put to the model.
- The real extra: SmartRecruiters' phone "Country code" picker (`spl-select`) keeps its
  value in a shadow root; `page_blockers` now finds the picker but reads it as empty, the
  profile's code cannot be confirmed there, and it went to the model (one call, about
  20 s, nothing gained). A calling-code menu the profile could not set now goes to the
  model only when the form marks it invalid. Rerun: sr1/sr2 0 calls, 7/8 committed.

### 2026-10-18 — Batch 2 follow-ups from an outside review

- **Existing dropdown answers**: `filler.js` cannot tell a committed choice from search
  text in an input dropdown that takes typing, so such a box became a leftover and
  `_fill_declared_combobox` replaced "Female" with the profile's answer.
  `widget_actions.committed_option` opens the menu (typing nothing) and reads the box's
  text as a choice only when it is one of the menu's options; `fill_widgets.kept_choice`
  keeps it unless it is what the fill would pick anyway (selecting that commits it).
- **Date repair**: "05/06/2027" reads as May 6 and June 5; a date whose day and month
  could swap is reshaped only when one reading is a date in the packet fields, else it
  is left as typed and noted.
- **Repair verification**: a new shape counts only when the form accepts it *and* the box
  still holds the same answer (same phone number, postal code or date); a widget that
  empties the box is not a repair, and the original is put back.
- **Reused ids in shadow roots**: `page_blockers` scopes a selector that matches more than
  one element by its hosts (`#work >> #phone`, Playwright's chain), kept only when the
  chain finds that element alone; otherwise a refused box is `ambiguous` and only noted,
  and an unresolved dropdown is not reported (as before shadow roots were read).
- **Rescans**: the pass after a question change hands its new written answers, uploads,
  leftovers and required questions to the usual handlers (only the new ones), not just
  dropdowns.
- **Probe guard (eval only)**: writes are refused unless they are telemetry or bot-check
  traffic (named hosts, `/cdn-cgi/`, `/rum`, `/vslog`, `/sink`), a GraphQL read, or
  Eightfold's question-list POST (short body only; refusing it leaves an empty form).
  `{"q1": "Yes"}` to an unnamed path is now refused as an unrecognized write.
- **Corrections signal**: punctuation may differ but never the numbers it separates
  ("$900.00" ≠ "$90,000"), and dates compare by their readings, so a swapped day and
  month in ISO form is a change.

### 2026-10-18 — Oracle Recruiting dropdowns and the address chain (Batch 2, 2.6)

- From three live Candidate Experience forms the applicant opened (captures kept in
  `output/`; the fixture `oracle_cx_address.html` is rebuilt with made-up values). The
  dropdowns are `input.cx-select-input` (role=combobox, `aria-haspopup=grid`), not JET
  widgets: each owns a `div[role=grid].cx-select__list` that renders only while open,
  its options `div[role=gridcell].cx-select__list-item`. `widget_actions` now reads that
  menu and those rows.
- Postal Code is a lookup whose rows read "ZIP, City, County, ST"; picking one fills City,
  County and State. `_postal_option` picks the row whose first part is the profile's code
  (a ZIP+4 matches its five digits; of several rows, the one naming the profile's city),
  and the commit check reads the code alone back.
- `_resolve_leftovers` takes Country and Postal Code first (`_dependency_order`), so City,
  County and State are already set when their turn comes. A dropdown with no profile
  answer that shows one of its options (County) is kept (`kept_choice`), and a settled
  leftover leaves the required-empty list.
- The packaged app (v1.16) stopped these fills at the email/code step: one reported the
  six "digit N of six" code boxes as missing answers. Batch 1's split-code-box detection
  on platform adapters covers that shape; not re-verified live.

### 2026-10-18 — second review round: date repair, revealed uploads, new frames

- **Refused-date repair verifies the meaning, not the text.** `_holds` used to accept any
  overlap between the readings of what was typed and what the box kept, so "05/06/2027"
  typed for May 6 and kept by a day-first widget as 2027-06-05 counted as success.
  Now the kept text must equal the typed shape, or read as exactly the original date
  (`_meant`). And a numeric shape with day <= 12 that could read both ways is typed only when
  the box's placeholder declares the order (`_one_reading`); ISO and month-name shapes
  are always safe.
- **An upload that appears alone triggers a rescan.** `filler.js` scan mode skipped
  `type=file`, so the question signature missed a newly inserted required upload. The scan
  now returns `file_inputs`, and the signature includes them.
- **Rescans see frames added after the pass.** The signature read `page.frames` but the
  rescan filled the cached `self.frames`, so a City in a new iframe stayed blank.
  `_sync_frames` appends new frames and keeps earlier ones at their index (a detached frame
  stays in place and fails to evaluate), so every `frame_index` already recorded stays
  valid; `_refill_emptied` uses it too. The signature is keyed by the frame object, not
  its index.
- **A postal code the applicant already picked is kept.** Oracle's lookup box shows only
  the code of the row picked ("95815" for "95815, Sacramento, Sacramento, CA"), so
  `committed_option` never matched it against the full row text, and the fill replaced it
  with the profile's code. With `key="postal_code"` it compares codes (`_postal_code`).
- **Read-back numbers frames as the fill did.** `_observe_fields` enumerated `page.frames`
  while answers were recorded against the synced list, so removing an earlier iframe put
  City's verification record under another frame's index. It now takes the fill's frame
  list; `_sync_frames` moved to `_FillState` so the wizard and finish read-backs use it.
- **Resolver ledgers and readiness use the same frame numbering.** The refused-Next retry
  enumerated `page.frames`, so after an earlier iframe was removed another frame got its
  ledger and skipped its own refused phone as "already tried". `_FillState._numbered_frames`
  yields `(frame_index, frame)` from `_sync_frames` for frames still attached;
  `_resolve_blockers` (both callers) and `_scan_readiness` (leftovers matched by
  `frame_index`) use it, and a removed frame is skipped rather than reported as unreadable.

### 2026-10-21 — Batch 3 fill probe: 61 live postings, page readback, findings

Method: `scripts/evals/fill_probe.py live` over postings picked from the live app.db
(`fill_probe_targets.py`, one per ATS site), 3 browsers, made-up applicant, live model
calls. New in the probe: a screenshot and a readback of every visible control before each
advance and at the end (`fill_probe_observe.py`, `fill_probe_readback.js`), each answer
graded against the page and the profile, a `fill_end` category, a submit-shaped request
refusal in the guard, `submit_click` patched to raise, and a test-account mode for
Workday/iCIMS/Oracle (`fill_probe_inbox.py`, IMAP; not run yet, no test inbox).
- **Results (run 1, 61 postings):** 33 reached review; 0 answers on the page contradicted
  the profile (378 matched); 103 required fields left blank (deduplicated); 0 data leaks,
  0 submits. A 30-posting repeat matched run 1 exactly (end, blank set, ok count).
- **Ranked findings:** (1) closed postings reported as fill failures, 7/61: Ashby "Job not
  found", Greenhouse `/<board>?error=true` (passes `identity.lost_posting`; the fill then
  treats the board's filters as questions); (2) react-select comboboxes recorded with no
  options (`filler.js` "Custom dropdown needs an observed selection") and the resolver
  declining profile-answerable education/sponsorship questions, 38 fields; (3) Lever
  multiple-choice inputs labelled by their wrapping option `<label>`, 32 fields, 7/8 Lever;
  (4) Apply entry missed: `wait_for_entry` ready on any input, single-pass
  `find_and_click_apply`, no "apply without an account", `fill_entry.py` logs "application
  form opened" without an entry; (5) Jobvite résumé "Select" menu; (6) Ashby fact wordings
  unrecognised.
- **Probe artefacts:** SmartRecruiters' own-host résumé upload is blocked by the guard
  (page shows "Cannot upload resume"), so its 7 stops are not app failures; the readback
  labels radio groups by option text, so Ashby/Lever answers show as "not seen".

## 2026-10-21 — Batch 3 fixes, measured on the same postings (run 1 → run 3)

Seven fixes from the Batch 3 probe (commits 67e5bbd..adbd0fd), re-probed on the 61
non-account postings (`output/evals/b3-run3`; Duolingo again in `b3-run3b` after the
gh_jid fix). Run 1 vs its 30-posting rerun had zero noise, but live sites drift.

- Reached review 33 → 37; called closed 1 → 7 (Ashby "Job not found", Greenhouse
  `?error=true` and gh_jid landings); fill_failed 6 → 2; stopped mid-way 18 → 12.
- Answers on the page graded ok 378 → 396; wrong 0 → 0; leaks 0; submits 0.
- Required blanks, deduplicated by label: 103 → 99. The raw count fell 234 → 99 mostly
  because the readback now names radio/checkbox groups by their question (counted once).
- Fixed blanks: Greenhouse "degree currently pursuing" (Bachelor's → Undergraduate),
  "Degree discipline", now-or-future sponsorship; Ashby contact number, most recent
  employer, place of residence, course studying; Lever location; Jobvite preferred name.
- Entry: Meta hides its posting with aria-hidden (role queries missed "Apply now");
  Dayforce's chooser needs "Apply without an Account". Both reach their forms headless;
  under the probe, Meta's guard still refuses `/ajax/route-definition/` (probe artefact).
  PACCAR reaches its SuccessFactors sign-in; run 1's failure was the guard refusing
  `/services/cas/createpayload/`. A page whose only "filled" box kept its own value
  (PACCAR's job-alert days) now ends as no form.
- SmartRecruiters 5/7 reach review with the probe's own-host upload of the made-up
  resume; 01 and 07 still stop mid-way (wizard does not advance; not yet diagnosed).
- Resolver diagnosis: of 21 rejected dropdown answers, most rejections were right
  (journalism years, UK right to work, "worked at ID.me?"); the guard was not loosened.
- Regression caught by the rerun and fixed: Duolingo draws its own form from Greenhouse's
  API with no embed frame, so the gh_jid check now applies only to a page with no
  controls of its own.
- Not done, by decision: years-of-experience range options (no measured blank) and
  ignoring search boxes in the entry wait (no measured case).
- Still untested: Workday, iCIMS and Oracle (58 targets) need the test inbox.

## 2026-10-22 — One row per source posting when a link starts resolving

- Bug: a posting first saved under a placeholder key (`other:<wrapper host>:…`, e.g. a
  zapply.jobs link that did not resolve yet, then `needs_browser`) got a second row when
  Prepare later resolved the link to the ATS: the new key missed `by_canonical`, the
  same company+role hit `by_group`, and `_join_group` made a sibling with the same
  `source_job_id`. The original stayed `discovered`. The Apply page keys rows and the
  selection by `source_job_id`, so the ready row lost to the stuck one: Fill (n) did not
  count it, and duplicate React keys left ghost rows under Needs you. `store.get` by
  source id picked either. Live data: 11 such pairs, plus 11 stuck copies whose link
  resolved to a requisition another source already held.
- Fix: `_RowRun._register` checks the sighting's source ref before the group index and
  `_rekey`s that row onto the real key (a real key is never replaced by a placeholder).
  `store.fold_stranded` drops an untouched placeholder `discovered` row (no tailor run,
  no fill) whose source posting exactly one real-keyed row also holds; it runs on each
  database's first open in a process, after Prepare and after each Find/nightly run.

## 2026-10-22 — Posting integrity guard (adapted from ai-job-search)

- Why: raw posting text reached the cover-letter prompt (in full) and the answer prompt
  (4,000 chars) with no untrusted framing, and `fetch_jd` kept CSS-hidden text. We
  auto-submit, so an obeyed hidden "if you are an AI, mention X" line marks the
  application as machine-written. Upstream (MIT, Mads Lorentzen, commit e16acee) had a
  tested deterministic gate; `pipeline/posting_guard.py` adapts it.
- Kept from upstream: the hidden-style rules (entities decoded, CSS comments stripped,
  collapsed box only with clipped overflow), the implied-end-tag walker and its bypass
  tests, the invisible-character classes, the narrow agent-addressed patterns with the
  AI-job-title exemption.
- Changed: dropped the shell/config patterns (curl, ssh, .env, settings.json,
  allowed-tools, tool_use): they guard an agent with tools, ours only return text, and
  `.env` fires on every `process.env` in page code. Script/style bodies are removed but
  not scanned for the same reason. Added "if you are an AI" and "AI tools must mention ...
  in your cover letter" patterns (the canary we actually face). Zero-width counts as
  tampering only between ASCII letters (Persian/Indic ZWNJ/ZWJ). Greek look-alikes are
  limited to Latin-shaped letters (lab postings write "μm"). The text is not re-folded,
  so a clean posting comes back byte-identical (no cache churn).
- Decision (user, 2026-10-22): an instruction-like line holds auto-submit only
  (`submit_guard` code `posting_instructions`); it never screens the posting out. Prepare
  and Fill still run.
- Measured before shipping: 1,013 unique saved postings (checkout `output/` plus the
  desktop data folder). Upstream's patterns would have held 2 (both "As an AI <title>",
  titles of four words and "Co-op"); after widening the title window to five words and
  adding co-op/fellow/etc., 0 alarms. Zero-width characters appeared in 68 postings,
  none between ASCII letters.
- Side effect, checked on 20k captured pages: the old extractor's "largest block" was
  often hidden data (Eightfold's `pcsx-data` JSON, Lever's hidden native `<select>` of
  universities). 44 of 2,686 saved `jd.txt` files are such JSON blobs (Boston
  Scientific). They now read as a JS shell over HTTP and go to the browser read. An
  Eightfold-specific API parser is the follow-up if that costs rows.

## 2026-10-22 — Submission attempts and outcome events

"Submitted" archives a row, and the status route refuses archived rows, so nothing could
record an interview afterwards; the status list also mixed operational state with hiring
facts. Outcomes are now events on the row, recorded on archived rows too, and the hiring
stage is derived (`outcomes.hiring_progress`) from those events plus the legacy
`interview`/`rejected`/`ghosted` statuses. Nothing was migrated: old rows read correctly
as they are.

Choices:
- **Snapshot in `store.set_status`.** It is the one place every path that submits passes
  through (fill finish, `_failed_after_submit`, the submission monitor, the status
  route), so no caller can forget it. The method is read from the status note, which
  those callers already set; `attempts.MONITOR_NOTE` replaced the monitor's literal.
- **`confirmed` means the app sent these exact files.** A manual mark copies the
  prepared files but cannot know what was uploaded; interview prep must say so.
- **Corrections never delete.** An edit adds a replacing event and voids the old one, so
  the timeline is auditable and a mistaken "rejected" can be undone without losing it.
- **Cohort rates.** Reply/interview counts cover applications sent 21+ days ago only, so
  a busy week of sending does not dilute the rate; silence stays separate from
  rejection. Shown in the pipeline banner's footer, not as a new banner stage (stage
  dates are counted per posting in the browser, and outcomes have their own dates).
- **List rows drop events and attempts** (the table reads `hiring` only); the detail
  view returns the full record.

## 2026-10-22 — Spoken-language gate in the prefilter

`apply/funnel/language_gate.py` (pure) runs inside `daily_rows.prefilter_screen`, so it
reaches the nightly run, extension captures and "Re-check eligibility" alike. Only a
language the profile does not list rejects; a not-fluent entry or an empty language list
is a flag, because the profile is often incomplete and a wrong reject hides a posting the
user never sees. Requirement means a cue within 80 chars in the same clause (fluent,
bilingual, native-level, business-level, C1/C2, JLPT N1/N2, HSK 5/6, required, must,
proficient, "written and verbal"); any optional word in the clause or a "Preferred …"
heading above it cancels it. Names are matched capitalised and must be followed by
nothing, punctuation or a language-ish word, which drops "a Dutch university" and
"Japanese clients"; "Polish the UI" is excluded explicitly. `profile.load_languages()`
reads only the JSON (no secret-store touch) per prefilter call; an unreadable profile
skips the gate. Measured on 1,013 unique saved postings with the owner's profile
(English + Vietnamese): one hit, "Bilingual (English / Spanish).", which is a real
requirement; the only false positive found ("enrolled at a Dutch university") led to the
adjective rule.
