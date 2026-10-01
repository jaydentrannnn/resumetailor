# Tooling & tests — implementation notes

Covers: repo hygiene, README, hermetic test suite.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-07-26 ? Workspace cleanup

**What:** Cleared `output/` (~30 MB of tailored docs, calibration temps, score caches),
Python `__pycache__` / `.pytest_cache`, and `frontend/dist`. Added the missing `output/`
rule under the existing `.gitignore` heading so regenerated resumes are not stageable.

**Why:** `output/` held full resumes (PII) and was only commented as ignored, not actually
ignored. Kept `data/`, `templates/`, `.venv`, `frontend/node_modules`, and
`docker/soffice.Dockerfile` (still used by `scripts/compare_pdf_backends.py`).

**Impact:** Next `docker compose up --build` or `npm run build` recreates the SPA; next
tailor run recreates job artifacts under `output/jobs/`.

## 2026-08-01 ? Root README

- **Decision:** Added project-root `README.md` covering local venv install, CLI/web usage, Docker Compose, and Ollama / LM Studio profiles.
- **Why:** No root readme existed; `frontend/README.md` is only the Vite template stub. Setup and alternate-backend usage lived in `CLAUDE.md` / `.env.example`.
- **Tradeoff:** Kept it short and command-focused ? deferred architecture / fabrication-guard detail to `CLAUDE.md` and `docs/PLAN.md`.
- **Spec delta:** User asked for install, Docker, and Ollama/LM Studio guides only.

## 2026-08-05 - Test suite decoupled from the developer's own data/master_resume.json

- **Verified the coupling was real, not hypothetical, before touching anything:**
  temporarily moved `data/master_resume.json` and every real template file
  (`templates/{main_template.docx,original_export.docx,template_profile.json}`) out of
  the tree and ran the full suite. Before this session's changes it would have been 21+
  failures in `test_web.py` alone (`FileNotFoundError`, or assertions like
  `test_get_config_returns_defaults`'s `len(tag_vocabulary) >= 1` silently depending on
  whichever real resume happened to be checked out) plus dozens more across
  `test_render.py`/`test_report.py`/`test_report_data.py`/`test_rewrite.py`/
  `test_tailor_cli.py`/`test_facets.py`/`test_fit.py`/`test_include.py` — none of it
  visible from a green CI run on a machine that happens to have the file.
- **`tests/fixtures.py` (new)**: the DOCX-builder helpers previously defined in
  `test_template_analyze.py` and cross-imported by `test_template_build.py`
  (`_add_bullet_numbering`, `_make_bullet`, `_docx_bytes`, `_add_hyperlink`,
  `_standard_resume`, `_multi_section_resume`, `_spacer_multi_section_resume`,
  `_rule_separated_resume` — two more of these than the originally-scoped plan named,
  found by grepping every `def _` in that file rather than trusting the enumerated
  list) moved here, since a second file already treated the first as a shared-fixtures
  module in every way but name. Added `_full_featured_resume` (a synthetic docx: linked
  project, education with GPA + coursework, an ampersand in a skills group and a
  bullet, three location strings chosen to never be substrings of one another so a
  contact-field-override test can assert one is absent without a false negative from an
  unrelated section) and `synthetic_resume()`, the matching `MasterResume` — kept in
  section-kind-and-order lockstep, though under the fixed-mode template this fixture
  builds, only the docx's own heading text and paragraph shapes affect what renders;
  `synthetic_resume()`'s section titles are inert prototypes.
- **`conftest.py` gained three more autouse fixtures**, same reasoning as the
  pre-existing `_isolated_libraries`: `_pinned_calibration` (pins `CHARS_PER_LINE`/
  `LINES_PER_PAGE`/`CALIBRATION_SOURCE`/`CALIBRATION_REJECTION` to the fallback pair —
  otherwise a test asserting on line counts would pass or fail depending on this
  machine's own `data/calibration/<backend>.json`, the exact failure mode the
  `chars_per_line: 20` incident produced) and `_isolated_template_paths`
  (`TEMPLATE_PROFILE_PATH`/`DEFAULT_TEMPLATE_PATH`/`BASELINE_TEMPLATE_PATH` redirected
  to nonexistent temp paths by default). The second one was found the hard way, not
  planned in advance: building the first hermetic render test, `resume.projects`
  rendered as silently empty even with `config.MASTER_RESUME_PATH` correctly isolated,
  because `render.build_context`'s default `active_layout()` lookup was still reading
  *this developer's own* `templates/template_profile.json` — a stale, pre-workspace
  file with `enabled.projects: False` sitting on disk, unrelated to anything this
  session changed, that nothing had ever surfaced before because every prior test
  happened to either override the path or not care whether projects rendered.
- **A second, subtler instance of the same bug class**: `tests/test_render.py`'s
  `rendered_docx` fixture was `scope="module"` (render once, reuse across every test in
  the file, since none of them touch Word/LibreOffice). Pytest sets up module-scoped
  fixtures *before* function-scoped ones for a given test, so a module-scoped fixture
  that reads `config.TEMPLATE_PROFILE_PATH` indirectly can construct *before* the
  function-scoped `_isolated_template_paths` autouse fixture has ever run — seeing the
  real, unpatched path regardless of the isolation fixture existing at all. Fixed by
  dropping the module scope (rendering is cheap here; the whole file still runs in
  ~1 second) rather than trying to make the isolation fixture wider-scoped, which would
  have needed a hand-rolled `MonkeyPatch()` instance (the built-in `monkeypatch` fixture
  is function-scoped only) and risked leaking patches across unrelated test files.
- **One real bug found in a test's own logic, not a fixture gap**: `test_render.py`'s
  `test_experience_header_location_is_not_bold` picked "the first run in the paragraph
  containing no pipe" as the location run. Against the real resume this happened to
  work; against a tagged/rebuilt header (which legitimately splits `"Company | "` into
  a `{{ job.company }}` tag run plus its own literal `" | "` run, both bold, since the
  separator is never part of the company field's span) the bare company-name run itself
  satisfies "no pipe" and was matched first. Fixed by searching for the location run
  only *after* the last pipe-bearing run before the tab, not from the top of the
  paragraph — a latent bug this test's logic always had, only surfaced by testing
  against a resume shaped differently than the one it happened to be written against.
- **`test_web.py`'s `client` fixture now seeds `config.MASTER_RESUME_PATH` with
  `synthetic_resume()`** rather than leaving it pointing at whatever the developer's
  own file holds. Five existing tests already followed a "copy the current
  `MASTER_RESUME_PATH`'s content, then redirect" pattern (`path.write_text(config.
  MASTER_RESUME_PATH.read_text(...))`) to get a realistic resume before making their
  own further edits — seeding it here made all five copy synthetic content instead,
  with no change to their own bodies.
- **`test_tailor_cli.py` gained the equivalent autouse fixture** (`tailor.main` calls
  `data.load()` internally regardless of what any given test stubs), and its 14
  `resume = load()` call sites — used only to build a stubbed `fit.fit` return value,
  since `fit.fit` is monkeypatched in every one of these tests — became `synthetic_resume()`.
- **Files needing more than the shared fixture**, each solved locally rather than by
  stretching `synthetic_resume()`'s shape for one caller: `test_report.py` already had
  its own parametrised `_synthetic_resume(bullet_tags=..., project_tech=..., ...)` for
  gap-diagnosis tests; its ten other `load()`-calling tests switched to it directly
  (default `bullet_tags=("python",)` already matched what they needed), except the one
  needing two experience entries (`test_report_lists_entries_dropped_entirely`), which
  builds its own inline. `test_rewrite.py` and `test_fit.py` needed resumes generous
  enough to exercise entry-ranking/budget-growth/page-fitting meaningfully — both files
  already had tests that assert their own sizing assumptions explicitly (e.g. "test
  needs room to grow the selection"), so undersizing the replacement fixture surfaced
  as a clear, named assertion failure rather than a silent false pass; sized each
  fixture up until every such self-check held (`test_fit.py`'s went from 3 to 5 bullets
  per experience entry, 2 to 4 per project, before `test_fit_restores_bullets_on_underflow`
  stopped reporting `initial_limit(13) == available(13)`, i.e. no room to grow).
  `synthetic_resume()`'s one experience bullet is tagged `"python"` specifically (not
  e.g. `"backend"`) so a consumer can write a plain `Keyword(canonical="python")`
  requirement and get a real match — the convention the rest of the suite's fixtures
  already used, discovered when `test_tailor_cli.py`'s coverage assertion needed it.
- **`pyproject.toml` gained an `owner` marker** (`addopts = "-m \"not owner\""`),
  applied to exactly one test in the end:
  `test_data.py::test_all_bullets_order_matches_pre_migration_order_for_the_real_master_resume`,
  which validates a property of the real file specifically (that migrating it preserved
  bullet order, load-bearing for the relevance-score cache key) and cannot be
  meaningfully replaced by a synthetic fixture. Every other `data.load()`/
  `config.MASTER_RESUME_PATH` dependency found across the suite turned out to be
  convenience, not genuine specificity to the owner's content.
- **Verification**: full suite green (595 passed, 1 deselected) with
  `data/master_resume.json` *and* every real template file physically absent from the
  tree, and again via `RESUME_TAILOR_DATA_DIR`/`RESUME_TAILOR_TEMPLATES_DIR` pointed at
  genuinely empty directories (the env-var path a container or CI would actually use).
  Frontend (`tsc -b`, `oxlint`, `vitest`) unaffected — no frontend files touched this
  pass.

## 2026-09-24 — Decision log split by topic; stale ARCHITECTURE.md removed

**What:** Split the 252 KB `implementation-notes.md` into nine topic files under `docs/notes/` (all 110 entries kept verbatim); the root file is now a 2 KB index. Deleted `docs/ARCHITECTURE.md` (stale, marked do-not-trust, unreferenced).
**Why:** Agents appended via Read+Edit, which pulled up to ~40k tokens of notes into every session that logged a decision.
**Impact:** Look things up by grepping `docs/notes/`; append with `>>`. The user-level `implementation-notes` skill (Claude Code `~/.claude/skills`, Codex/Cursor `~/.agents/skills`) now requires this. ARCHITECTURE.md is recoverable from git (`c7d7c60`).

## E6 app logging (2026-09)

- `logs.py` writes one rotating JSON-lines `app.log` (2 MB x 5) under `RESUME_TAILOR_LOG_DIR` (default `<OUTPUT_ROOT>/logs`, `off` disables). Every record passes `RedactingFilter` before any handler writes it: emails, phones, API keys and `password=`/`token=` style values are replaced, so the file is safe to attach to a bug report.
- `run_id` comes from a ContextVar set around job (`web/jobs.py`) and operation (`apply/funnel/operations.py`) worker threads, so one failed run can be picked out of a shared log.
- `GET /api/diagnostics.zip` bundles the log (re-redacted), versions, platform, backend routing and redacted settings. It deliberately omits the master resume, applicant profile, registry and generated documents.
- Tests: `tests/conftest.py` points `RESUME_TAILOR_OUTPUT_DIR` at a temp dir before importing the package, because job threads that outlive a test wrote `packet.json` into the real `output/` after the monkeypatch was undone.

## Housekeeping (S5, 2026-09)
`housekeeping.run()` runs in a daemon thread at server start and in the job worker after
each run: the LLM cache is held under 500 MB by least-recently-used (max of atime and
mtime, since many filesystems mount noatime), and `OUTPUT_DIR/jobs/` keeps the newest
200 run folders plus any folder an application references (`job_id`,
`reused_from_job_id`) or touched in the last hour. `DELETE /api/cache` 409s while a run
is queued or running, because stages read cache files mid-run.

## Extraction votes per backend, and the cost preview (PF3/PF4, 2026-09)
`JobSettings.extract_runs` defaults to 0 = automatic: `config.extract_runs` gives 1 vote
on Anthropic/Gemini (a 3-way vote there triples a paid call for little stability gain)
and `EXTRACT_CONSENSUS_RUNS` (3) elsewhere; `LLM_EXTRACT_CONSENSUS_RUNS` in the
environment pins it everywhere. Resolve it inside the run's routing. The vote count is
already in the extraction cache file name (`-consensusN`), so no fingerprint change.
Saved settings from before carry an explicit 3 and keep it.
`estimate.py` + `POST /api/jobs/estimate` price a run arithmetically (chars/4 plus
per-stage prompt overhead, rewrite counted as two fit rounds). Unknown models get token
counts and `usd: null`, never a guessed price; the SPA hides the line for local models.
PF2 (unoserver) is deferred: optional in the plan, and PF1's persistent profile already
removed the per-call profile creation.

## Frontend loading and polling cost (PF5, 2026-09)
Every page but Tailor is `React.lazy` (initial JS 551 kB → 385 kB). `GET
/api/applications` sends a weak ETag over the response body (not a store counter:
rows carry fields computed from job files and settings) and answers 304 to a matching
`If-None-Match`; `api.conditionalGet` then hands back the previous object, so an idle
poll does no JSON parse and gives React the same reference.

## UI primitives and setup health (UI1–UI7, 2026-09)
New primitives live in `frontend/src/components/ui/` (Button with `loading`, Card,
EmptyState, Skeleton, Kbd, Stepper, InlineHelp, ToastProvider). Field/Modal/Tabs stay in
their files and are re-exported from `ui/index.ts` rather than moved (dozens of imports,
no behaviour change). Pure helpers (`buttonClass`, `stepState`, `describeEstimate`,
`setupPillLabel`) sit in `lib/` so component files export only components (oxlint's
fast-refresh rule). `lib/errors.ts` `describe()` maps both server `error` codes
(`ApiError.code`, set by `request()` from the body) and known message text (job errors
arrive as SSE strings) to title/detail/next step; add a rule there when a new failure
mode gets a message. `GET /api/setup-status` never makes a model call: key presence via
`credential_gaps` plus an Anthropic check (that key is enforced later, by
`anthropic_api_key`), and a cached 2 s `GET <base>/models` probe for local servers.
The header needs `relative z-30`: its `backdrop-blur` creates a stacking context that
otherwise lets page cards paint over header popovers.
