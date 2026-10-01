# DOCX import & sections — implementation notes

Covers: arbitrary sections model, flexible template import, heading analyzer, wizard, content importer/merge, table layout.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-08-01 ? Flexible single-column template import

- **Decision:** Added analyze ? confirm ? install for single-column paragraph DOCX
  resumes. Mapping lives in `templates/template_profile.json`. Build logic moved to
  `src/resume_tailor/document/template_build.py`; `scripts/build_template.py` is a thin CLI.
  Experience required; Education / Projects / Skills optional (omitted, never invented).
- **Why:** Hard-coded `EDUCATION` / `WORK EXPERIENCES` / ? headings and baked-in ` | `
  separators rejected otherwise-valid single-column exports.
- **Tradeoff:** Tables, text boxes, multi-column layouts, and manual bullet glyphs are
  still blocking. Header tagging reconstructs from field spans + literal interstitial
  text (safer than sequential in-place run edits when replacement length changes).
  Spacing/bullet-font normalization remain profile flags (default on, matching legacy).
  Calibration stays manual (`calibrate.py` + restart).
- **Runtime:** Analyze/install use no LLM. Staged profile installs smoke-render (DOCX
  only, no PDF) before committing baseline + profile + tagged template. Legacy upload
  without a profile keeps the previous zero-arg `_run_build` seam for tests.
- **Spec delta:** Template tab is now a wizard; `GET /api/template` includes profile
  summary; `POST /api/template/analyze` is new; `POST /api/template` accepts optional
  multipart `profile` JSON.
- **Follow-up:** Owner should install once through the wizard on the current export to
  write `template_profile.json`, then calibrate. Vitest covers section-toggle helpers only.

## 2026-08-04 - Arbitrary, renameable, reorderable resume sections

- **Motivating bug, found before writing any code:** the live install already had
  `templates/original_export.docx` with `EXPERIENCE`, `INTERNSHIP & PROGRAMS`, and
  `OTHER ACTIVITIES` headings, but `templates/main_template.docx` only had `EXPERIENCE` —
  the other two headings and every entry under them had been silently absorbed into
  `EXPERIENCE`'s body and deleted, because `template_analyze._classify_heading` was
  first-match-wins per canonical key. Separately, `template_profile.json` had
  `education.header.header_paragraph_id` pointing at the `______________` horizontal
  rule, not the school line — `_split_entries` read the rule as an entry header because
  nothing filtered non-content chrome. Both are fixed by this change, not just the
  feature request that motivated it.
- **Data model: `MasterResume.sections: list[Section]`**, a Pydantic discriminated union
  on `kind` (`experience` / `project` / `list` / `education` / `skills`), replaces the
  four fixed top-level lists. `Section.kind == "project"` (singular) while the render
  context / `EnabledSections` key stays `"projects"` (plural) — a deliberate naming split
  documented at each site that bridges it (`config.SECTION_KIND_ENABLED_KEY`), not a typo.
  A `model_validator(mode="before")` folds a legacy file's `education`/`experience`/
  `projects`/`skills` keys into four sections in that fixed order with ids equal to the
  key names, which is what keeps `all_bullets()`'s order — and therefore
  `rewrite._score_cache_path`'s cache key — byte-identical for every existing file; a
  test pins this against the real `data/master_resume.json`. Read-only `@property`
  `experience`/`projects`/`education`/`skills` flatten across same-kind sections and
  return the *same* objects, so `facets.apply`'s in-place mutation through
  `model_copy(deep=True)` and ~50 other read sites needed no change. Never
  `@computed_field` — that would put the legacy keys back into `model_dump` and a saved
  file would carry two sources of truth. One real footgun found by a failing test:
  `resume.model_copy(update={"education": [...]})` silently no-ops now (the property
  ignores whatever lands in `__dict__`) — production code never did this, but two tests
  did and had to switch to mutating through `sections` directly.
- **New `list` section kind** (`ListSection` / `ListItem`) — a heading plus plain bullet
  lines with no entry header (certifications, awards, languages). Never rewritten by the
  LLM, never resized by the fit loop — renders in full like a skills group. Chosen as a
  named kind rather than folding it into `experience` because it has no header fields at
  all, the simplest of the five kinds to both detect and tag.
- **Selection/fitting generalized from two hardcoded sections to N.**
  `rewrite._section_budgets` (exactly one function whose *algorithm*, not just its
  plumbing, assumed two pools) became `_allocate_budgets(pools, weights, ...)`: floors
  per pool, proportional shares, then an iterative spill loop that keeps going until
  every pool is either satisfied or at its cap — verified by hand against all four
  existing `experience_share`/`max_per_entry` test scenarios before trusting it.
  `select_within_entries` gained `pools`/`weights` params for the N-pool path; the old
  `experience_share` float stays as two-pool sugar (`isinstance(e, Project)`-derived),
  kept specifically so tests that build raw `Experience`/`Project` lists with no section
  wrapper keep working. `fit.choose_entries` now loops `resume.entry_sections`, ranking
  each one independently against a per-kind default cap
  (`MAX_EXPERIENCE_ENTRIES`/`MAX_PROJECT_ENTRIES`) — the point being that a "Leadership"
  section's entries never compete with a job's for a slot. `fit.estimate_lines` reads a
  new `layout["section_mode"]` (`"fixed"` vs `"generic"`, see below) because under fixed
  mode N same-kind sections still flatten under *one* physical heading (one header line),
  while generic mode gives each its own — getting this wrong doesn't produce a wrong
  page, just an extra grow/shorten round, per the project's existing "estimate is cheap,
  real render is authoritative" invariant.
- **Template build: `section_mode: "fixed" | "generic"`.** Fixed mode is byte-for-byte
  today's contract (one hard-coded loop per kind) and is what a resume with one heading
  per kind still gets — zero behavior change, proven by every pre-existing
  `test_template_build.py`/`test_template_analyze.py` test passing unmodified. Generic
  mode tags **one shared `{%p for section in sections %}` block** with independent
  `{%p if section.kind == '<kind>' %}` branches (not an `elif` ladder — verified
  `docxtpl 0.20.2`'s `patch_xml` regex doesn't care which keyword follows `{%p`, but
  independent blocks let a kind with no prototype be omitted with no ladder-ordering
  bookkeeping), each with its own `{%p for <var> in section.entries %}` loop reusing the
  *exact* tag strings and loop-variable names (`job`/`proj`/`edu`/`group`/`bullet`/
  `detail`, plus new `item` for list) fixed mode already used. The four existing
  `build_*_profile` functions were split into pure `_tag_*_prototype` helpers (tagging
  only, no loop/delete) reused by both modes — a mechanical extraction verified
  byte-identical by the existing test suite before `build_generic` was written on top.
  **One real bug found only by testing against a synthetic doc shaped like the actual
  motivating resume** (education with a single, non-bulleted degree line — no separate
  detail bullet): `_tag_education_prototype`'s existing degree/detail-share-one-paragraph
  fallback does `degree._p.addnext(detail_p)`, inserting a new paragraph mid-build. Under
  fixed mode this is harmless because `build_from_profile` already processes kinds
  bottom-up specifically to avoid this; `build_generic`'s per-kind loop did not, so
  processing EDUCATION (physically above SKILLS in the doc) shifted every later
  paragraph's index and corrupted the skills prototype's span. Fixed by sorting
  `build_generic`'s processing order by descending `heading_paragraph_id` too — same
  reasoning as the fixed-mode comment it was copied from, just not previously needed
  since generic mode didn't exist. Caught by hand-testing against the user's real
  resume end-to-end (`RuntimeError: skills_label: span [0:9] exceeds paragraph length 0`),
  not by a unit test written in advance; a regression test now pins it.
- **Analyzer: structural heading detection, not just alias lookup.** The old
  first-match-wins-per-key loop is now an ordered, undeduped list of every detected
  heading. Two additions: (1) `_is_chrome` — blank or a decorative rule line — is
  filtered out of `_split_entries` everywhere, which is the actual fix for the
  rule-mistagged-as-degree-line bug found up front; (2) `_looks_like_heading` — short,
  no tab, no colon, no date, mostly-uppercase, guarded to `paragraph_id >= 2` so an
  all-caps *name* line is never misread as a heading (found by testing, not anticipated)
  — catches a heading with no alias match (`"OTHER ACTIVITIES"`), defaulting its kind to
  `experience` unless immediately followed by bullets with no entry header (`list`).
  Same-kind headings' bodies are pooled (`combined_body[key]`) before prototype
  selection, so the best-formatted entry can come from any of them, not only the first —
  this is also what makes `_section_body_paragraphs`'s existing "next *other-kind*
  heading" boundary logic correctly treat an embedded same-kind sub-heading as chrome
  to walk past, with no separate heading-filter needed inside `_split_entries`.
  `section_mode` becomes `"generic"` automatically the moment fixed mode could not
  represent what was found (two headings of one kind, or any `list`-kind heading) —
  never user-chosen at analyze time. A non-bulleted degree/detail line downgrades from a
  blocking `no_education_bullets` to a non-blocking warning (`retarget_bullet` creates a
  paragraph's numbering properties rather than requiring them, so it still builds fine)
  — `validate_profile_against_doc`'s `_check_bullet` gained a `strict` flag so this
  relaxation applies only to education's degree/detail role, not the experience/project
  bullet loops where real Word numbering still matters.
- **Verified against the user's actual upload**, not just synthetic fixtures:
  `NGOC_DAO_RESUME_Intern.docx` (EDUCATION / WORK EXPERIENCE / LEADERSHIP EXPERIENCE /
  OTHER ACTIVITIES / SKILLS, non-bulleted degree line) now analyzes `ready: True`,
  `section_mode: "generic"`, all five sections detected correctly. A full build-and-render
  pass renamed `OTHER ACTIVITIES` → `VOLUNTEERING` and moved `SKILLS` to the top of the
  section list on the `MasterResume` side only (no template rebuild) — both changes
  appeared correctly in the rendered `.docx`.
- **Wire format flip.** `GET /api/master-resume` now returns `sections`-shaped JSON
  (previously flattened via a temporary `data.to_legacy_dict`, kept — and still tested —
  as the shape `PUT` transparently still accepts, since the model's before-validator
  folds either shape in identically). `ResumeOutlineResponse` gained a `sections` field
  (one entry per resume section, any kind/count) alongside the pre-existing flattened
  `experience`/`projects`, so `IncludePanel` can show which section an entry belongs to
  instead of merging every same-kind section into one flat list.
- **Frontend: `EditorPage.tsx` rewritten around `resume.sections.map(...)`.** A generic
  `SectionShell` (editable title input, kind badge, move/remove via the pre-existing
  `EntryControls`) wraps a per-kind body component; the four existing body components
  (education/experience/projects/skills) were adapted with minimal changes (they already
  took `entries`/`onChange` — just re-scoped to one section instead of the whole
  resume), plus a new `ListEntries` body. An "Add section" control at the bottom picks a
  kind and appends a blank one. `resumeEdit.ts`'s helpers (`collectBulletIds`,
  `nextEntryId`, `blankSection`, `completenessErrors`, …) all iterate `resume.sections`
  now instead of two hardcoded arrays. `SectionMapStep.tsx` (the upload wizard) shows one
  toggle per detected *kind* still (unchanged mechanism — kind-level enable/disable is
  still what controls which prototypes get built), plus an informational banner when
  `section_mode` came back `"generic"` explaining that per-section title/order edits now
  live entirely on the Master Resume tab and need no re-upload — deliberately not
  pretending to let the wizard reassign an individual detected heading's kind, since
  `TemplateProfile.sections` (the analyzer's per-heading detection list) has no
  functional effect on the build; only the five kind-level prototype mappings do.
- **Verification, given no `chromium-cli`/Playwright available in this environment:**
  full backend suite (523 passed, the same 16 pre-existing failures as `main`, diffed
  before/after), `npx tsc -b` clean, `oxlint` clean (same pre-existing warnings only),
  `npm run test` (11/11), `npm run build` clean. Started the real `uvicorn` server against
  live data and `curl`-verified `GET /` (SPA shell), `GET /api/master-resume` (returns
  `sections`, no flattened keys), `GET /api/resume-outline`, and `GET /api/config`, then
  fetched the real resume, applied the exact mutation `EditorPage.tsx` would produce
  (renamed a section, appended a brand-new `list`-kind section with a fresh id) and
  posted it to `POST /api/master-resume/validate` (non-destructive) — `ok: true`, zero
  errors, confirming the full payload shape end to end without writing to the user's
  real file.
- **Deliberately deferred, not attempted: blank-line/rule visual fidelity and fit-constant
  recalibration** (the plan's own Phase 6). Restoring inter-section spacing changes what
  `LINES_PER_PAGE`/`UNDERFLOW_THRESHOLD` mean and needs a real Word/LibreOffice
  render-and-measure pass to calibrate correctly — "measure, don't guess" is this
  project's own standing rule for exactly this class of constant, and neither Word COM
  nor a verified LibreOffice container was exercised this session. Every other phase of
  the design is complete and tested; this one is the documented, isolated exception,
  not a silently dropped scope corner.

## 2026-08-05 - Analyzer correctness: heading detection stops trusting text alone

**What:** `template_analyze.py`'s heading/entry detection (Phase 4 of the remediation
plan) now corroborates every text-based match against the document's own structure —
formatting, position, and content — instead of trusting a keyword substring on its own.
Four independent mechanisms, landed together because each one's test fixtures depend on
the others being in place first:

- **`_fingerprint(paragraph)` + `_heading_classes(paras)`**: a formatting signature
  (style, bold, size, alignment, indent, spacing, has-tab, caps bucket) clustered across
  the document. A class needs >=2 short, non-bulleted, content-introducing members to
  count — real section headings are almost always styled identically to each other and
  to nothing else, so they cluster; a single stray ALL-CAPS line does not. An unaliased
  text match (`_looks_like_heading`'s structural-fallback path) is now *hard*-gated on
  class membership when a class exists at all; an aliased-but-weak match (the
  <=0.6-confidence tiers, which have no case requirement whatsoever) is downgraded and
  flagged (`heading_formatting_mismatch`, non-blocking) rather than excluded outright,
  since a real template occasionally styles one heading slightly differently.
- **`_introduces_content(p, paras, heading_fp_classes=frozenset())`**: implements the
  guard `_looks_like_heading`'s own docstring has long claimed the caller enforces — a
  candidate must actually precede a bullet or a tab-aligned entry header before the next
  *recognizable* heading, or it introduces nothing and is not a section. This is what
  rejects `"PROFESSIONAL SUMMARY"` followed only by a paragraph of prose. "Recognizable"
  matters: an earlier version stopped the scan at the first short/plain/no-tab line,
  full stop — which made a real heading followed by a two-line entry (company name on
  its own line, title+date on the next, e.g. `"WORK EXPERIENCE"` → `"AMAZON WEB
  SERVICES"` → `"Software Engineer Intern\tJune 2022 - Present"`) register as
  introducing *nothing*, since the scan gave up at the company line one paragraph too
  early. Fixed by only stopping at a line that is unambiguously a heading by the same
  signals the rest of the module already trusts: an alias/keyword match, or (once a
  class is known) fingerprint-class membership — never "short and plain" alone.
- **`_split_entries`, two passes**: `_bootstrap_split_entries` (today's bullet-anchored
  rule, unchanged, kept as its own function) still runs first; a second pass clusters
  each bootstrap entry's own header by fingerprint and, when a majority share one,
  re-splits using the **union** of the bootstrap rule and that class's membership — not
  a replacement. Union matters for the same reason as above: an entry that legitimately
  lacks the dominant format (an otherwise-ordinary job with no tab-aligned date) is
  *already* a correct bootstrap boundary, and a fingerprint-only re-split would
  incorrectly re-merge it into its predecessor for no reason but the format mismatch —
  caught by the `experience_dates_partial` test fixture (three entries, one dateless),
  which the first replacement-based design silently merged down to two.
- **Two position-based exclusions**, neither expressible as fingerprint corroboration
  alone, both hard gates on any match below 1.0 confidence: `p.has_tab` (a real section
  heading never itself carries a trailing tab-aligned date — `_heading_classes`'s own
  candidate filter already assumed this; a later entry's own header, e.g. `"Advocate of
  Sexual Education in School\t2022"` inside an unaliased `"OTHER ACTIVITIES"` section,
  matches the `"education"` keyword at 0.6 confidence and has a tab), and
  `_immediately_follows_entry_header(p, paras)` (the nearest preceding non-chrome
  paragraph has a tab and is not a bullet — the shape of "this line is an entry's title,
  sitting right under its own company/dates header", e.g. `"Experience Designer"` under
  `"Acme Corp | Remote\tJan 2023 - Present"`).
- **`_reconcile_header_fields`** (4d) runs `_header_fields_from_text` on *every* entry in
  a section, not just the one prototype `_exp_score`/`_proj_score` would pick, and keeps
  a field only when a majority of entries carry it — `FieldCandidate.confidence` is
  finally a real presence rate instead of a single entry's yes/no. A field absent from
  the majority is a **blocking** `experience_dates_not_detected` /
  `project_dates_not_detected`; present on some entries but not all is a non-blocking
  `experience_dates_partial` / `project_dates_partial`. The prototype entry itself is
  now chosen from the entries matching the *modal* field-presence signature, so an
  outlier entry that scores well on `_exp_score` (more runs, has a title line) but
  happens to be missing a field most other entries have can no longer become the
  prototype and silently drop that field for the whole section.
- **`_prototype_consistency_issue`** (4e): blocking issue if a prototype's header/title/
  bullet paragraphs don't all fall within one entry's own span — catches the original
  review's exact finding (header from one entry, title from another) directly, as a
  named assertion, rather than relying on the detection fixes above to prevent it from
  ever arising.
- **`validate_profile_against_doc`** (4f) gained semantic checks it never had: a mapped
  date span must actually look like a date (`date_span_not_date_shaped`, non-blocking);
  an experience/project/education header paragraph must be a genuine entry start, not a
  bullet or blank (`header_not_entry_start`, blocking); every `heading_prototype`/
  `DetectedSection.heading_paragraph_id` must be in document range
  (`bad_heading_prototype` / `bad_detected_section`, blocking) — previously unchecked
  entirely.
- **`_contact_field_order`** (4g): `_PHONE_RE` matches a bare year range
  (`"2021 - 2025"` is digit-space-punctuation-digit, same shape as a phone number) —
  excluded anything that also matches `_DATE_RE` before trusting it as a phone.

**Why:** All four mechanisms trace back to one root cause — the analyzer decided
"this is a heading" (or "this is a new entry") from text content alone, with no
cross-check against how the document actually looks or is laid out. That is precisely
how a `PROFESSIONAL SUMMARY` heading silently became an experience section's header
prototype, dragging a real job's title in from a different entry and dropping its dates
with `ready: true` and zero warnings — the finding that opened this whole remediation
effort. Landed after the hermetic suite (Phase 2) and the build verifier (Phase 3)
specifically so the safety net existed before touching the highest-risk file in the
codebase.

**Impact:** Found and fixed one real design flaw during validation, beyond what static
review anticipated: a `conf <= 0.6 and uncorroborated -> exclude` gate (an earlier,
coarser attempt at the has-tab/immediately-follows-header exclusions above) correctly
rejected `"Experience Designer"` but also collateral-damaged the `nina` workspace's
genuine `"SKILLS & Interests"` heading, since both are "uncorroborated" by fingerprint
for the same structural reason (mixed case / a lone stylistic outlier) and confidence
alone cannot tell them apart — replaced with the two targeted, position-based checks
described above, which correctly keep one and reject the other. A second, subtler
issue turned up only once a fixture exercised it: the original `_introduces_content`
and the original (replacement-based) `_split_entries` each had their own version of
"stops one line too early" / "merges a boundary that didn't need fixing" — both fixed
before this entry was written, not after. `tests/document/test_template_analyze.py` gained 11
regression tests (summary-section exclusion, summary-only blocking, an all-caps
uncorroborated entry line, the "Experience Designer" and "Advocate of ... Education ..."
false positives, no-dates/partial-dates blocking for both experience and projects, and
the phone/date regex fix) — file total 33 passed, template suite (analyze + build +
verify) 79 passed, full project suite 617 passed, 1 deselected. Both real workspace
templates (`default`, fixed mode; `nina`, generic mode) re-verified end to end
(analyze -> build -> `template_verify.verify_tagged`) after every change in this phase,
not just at the end: `default` stays `ready: true` with zero issues throughout; `nina`
now correctly reports all five real sections (education, three experience-kind, skills)
with exactly two honest, non-blocking issues (the skills heading's own formatting
mismatch, and no projects section present) — no spurious sections, no dropped ones.

## 2026-08-05 - Wizard confirm + preview: the analyzer's own findings reach the UI

**What:** The template wizard (Phase 5) can now show what the analyzer actually found,
let the user correct a specific heading's classification with a real server round
trip, and preview the installable result before committing to it.

- **`field_candidates` reaches the wire.** `template_analyze.analyze_docx` always
  computed per-field spans (company/dates/title/…), but `template_ops.analyze_upload`
  dropped them building `TemplateAnalyzeResponse`. New `TemplateFieldCandidateOut`
  schema + `field_candidates` field, populated from `AnalyzeResult.field_candidates`.
  `AnalyzeReport.tsx` renders one row per field under each detected section — a red
  "not detected" row for `company`/`dates` (experience), `name`/`date` (projects),
  `school`/`dates` (education) when nothing was found, which is exactly the class of
  problem (a silently unmapped field) that started this whole remediation effort.
- **`template_analyze._analyze_document` takes an `overrides: dict[int, str | None]`
  parameter** (paragraph id -> forced kind, or `None` for "not a section"). Threaded
  through `analyze_docx`. An override bypasses *every* heuristic gate for that specific
  paragraph — fingerprint corroboration, has-tab exclusion, `_introduces_content` — by
  design: those gates exist to make a good guess when the only evidence is the
  document itself, but a user override is not a guess, it is the user correcting the
  guess, so re-running it through the same uncertainty would be backwards. Wired in
  right where `_classify_heading` is called in the main detection loop, so an override
  produces exactly the same downstream shape (entry splitting, field reconciliation,
  date-detection issues) as a naturally-detected heading of that kind — the wizard's
  remap result is never a special case the rest of the pipeline treats differently.
- **`POST /api/template/analyze/remap`** takes an upload's sha256 (not the file again)
  plus the accumulated override map, re-runs analysis, returns the same
  `TemplateAnalyzeResponse` shape as `/analyze`. Needs the upload's bytes without a
  second upload, which is what the new upload cache (`template_ops._cache_upload` /
  `_load_cached_upload`, keyed by sha under `output/.../template/uploads/`) exists for
  — written once by `analyze_upload`, read by every subsequent remap/preview call in
  that wizard session, cleared by `clear_upload_cache()` on a successful install (the
  upload has become the live template; nothing further needs the cache entry) and
  opportunistically pruned past 24h so an abandoned wizard session (tab closed after
  analyze, before install or reset) does not leak forever.
- **`POST /api/template/preview/source` and `POST /api/template/preview/draft`** give
  the wizard a real side-by-side: the uploaded document as-is, and what installing the
  current draft profile would actually produce. `preview/source` converts the cached
  upload straight to PDF. `preview/draft` runs the same staged build
  `_install_with_profile` does — `template_build.build_from_profile` into a temp
  directory, `render.render` with `template_profile.active_layout(profile)` passed
  explicitly (the same fix Phase 3 needed for `verify_roundtrip`, for the same reason:
  a staged/never-installed profile has no business reading whatever profile happens to
  be live on disk) — minus the atomic commit: nothing under `templates/` is ever
  written or replaced. Confirmed by a test that snapshots the templates directory
  before and after calling the endpoint and asserts it is byte-for-byte unchanged.
- **Frontend**: `SectionMapStep.tsx` gained a `<select>` per detected heading (its
  value defaults to the analyzer's own classification, options are the five kinds plus
  "Not a section"), positioned as the primary confirmation control above the existing
  kind-level include/exclude checkboxes — kept both, deliberately: the new select
  answers "what *is* this heading", the old checkboxes answer "do I want this *kind*
  in the template at all", which stays a meaningful, independent question (e.g. omit a
  correctly-detected Projects section). New `PreviewCompare.tsx`: the source preview
  loads automatically (one conversion, cheap relative to a rebuild); the draft preview
  is a manual "Generate draft preview" button rather than auto-refreshing on every
  profile edit, since `templateState.tsx`'s own docstring already documents install as
  "Word ~9s" and the profile can change on nearly every keystroke while mapping — an
  auto-refresh there would mean a near-permanent spinner, not a preview.
- **State**: `templateState.tsx` gained `headingOverrides` (accumulated across remap
  calls — a second correction must never lose the first), `remapBusy`, and
  `remapHeading()`, which POSTs the full accumulated override map every time and
  replaces both `analysis` and `profileDraft` with the server's fresh response —
  intentionally never a client-side patch, for the same "let the analyzer's own
  downstream logic decide" reason the endpoint itself exists.
- **Verified against a live server, not just the test suite**: started `uvicorn`
  locally and drove `/analyze` -> `/analyze/remap` -> `/preview/source` ->
  `/preview/draft` with real HTTP requests against a hand-built synthetic .docx (no
  test doubles) — confirmed `field_candidates` populate with real spans, a remap
  (`EDUCATION` forced to kind `list`) correctly changes `sections` in the response, an
  unknown sha 400s, and — since Word turned out to be available in this environment —
  both preview endpoints returned real, valid PDFs (`%PDF-1.7` headers, hundreds of KB,
  openable), not just the stubbed-render assertions the test suite necessarily uses.
- **Tests**: 6 new backend tests in `tests/web/test_web.py` (field candidates present,
  remap changes section kind, unknown-sha 400, both preview endpoints via the
  established `render`/`to_pdf` monkeypatch seam, install clears the upload cache).
  Frontend: `tsc -b`, `oxlint`, `vitest run`, and `vite build` all clean — no new
  warnings beyond the pre-existing "only-export-components" fast-refresh warning every
  other state-context file in the codebase already carries. Full backend suite: 623
  passed, 1 deselected.

## 2026-08-05 - DOCX importer: an upload becomes content, not just layout

**What:** A Template-tab upload was, until now, a layout donor whose content was
discarded — a new user uploaded their resume and then retyped every bullet by hand into
the editor. New `src/resume_tailor/importing/resume_import.py` (Phase 6) turns
`template_analyze.analyze_docx`'s own structural findings into a `MasterResume` draft;
`POST /api/master-resume/import` exposes it without writing anything.

- **No LLM required for a usable draft.** `import_from_analysis(result, doc)` reuses
  `template_analyze`'s private per-paragraph helpers (`_load_paras`, `_split_entries`,
  `_header_fields_from_text`, `_skills_spans`) — the exact machinery Phase 4 made
  reconcile *every* entry, not just a prototype, which is precisely what "parse the
  whole resume" needs instead of "parse one representative entry." Tags are seeded
  deterministically: `_seed_tags` whole-word-matches each bullet's text against a
  known-tag vocabulary (the built-in `TAG_ALIASES` keys/values, unioned with an
  existing workspace's own `tag_vocabulary` when re-importing into one that already has
  a resume). A bullet nothing matched gets the sentinel tag `"untagged"` (`Bullet.tags`
  requires at least one entry) and is counted in `ImportedResume.
  untagged_bullet_count`, surfaced to the user rather than silently guessed at.
  Deliberately conservative in the false-negative direction: a missed tag is safe (the
  user or the opt-in LLM pass adds it), a *wrong* tag would corrupt the fabrication
  guard's own whitelist for that bullet.
- **New `render.parse_month`/`render.parse_range`**, the literal inverse of
  `format_month`/`format_range`, living right next to them rather than in the importer
  — one module owns both directions of the date format now. Only converts a
  recognizable "Mon YYYY" shape; anything else (a bare year, "Present", free text)
  passes through unchanged, mirroring `format_month`'s own tolerance for whatever a
  human actually wrote.
- **New `docx_text.hyperlink_target(paragraph, hyperlink_element)`** resolves a
  `w:hyperlink`'s `r:id` to its actual target URL via the paragraph part's
  relationships — genuinely new capability. Every existing caller in this codebase
  only ever needed a hyperlink's visible *label* text (`template_analyze`'s link-span
  detection, `template_build`'s stripping); this importer is the first thing that
  needs where a link actually points, to reconstruct `Project.url`.
- **Three real bugs found and fixed by testing against `nina`'s actual uploaded
  resume, not just synthetic fixtures** — the same "verify against both real
  workspace templates" discipline Phase 4 used, applied here to content instead of
  layout:
  - `_PHONE_RE` requires its match to start on a digit, so `"(555) 123-4567"` silently
    lost its opening parenthesis. Fixed by restoring it when the character immediately
    before the match is `"("`.
  - The location-detection loop originally split the contact line on a bare `/`
    character (among other separators) — correct for a real field separator, wrong for
    a plain-text profile URL typed inline instead of a real hyperlink (`"www.linkedin.
    com/in/ngocdao2006"`, common when an export loses its hyperlinks): splitting on its
    own internal slash shredded it into unrelated fragments, one of which (`"in"`)
    then passed every exclusion check and became a bogus `location`. Fixed by
    switching to `template_analyze._contact_separator`'s own detection (the actual,
    space-padded separator this specific line uses) instead of a bare character class.
  - A two-line entry header whose *second* line (the title) also carries its own
    trailing tab-aligned date (`"Organizer and Marketing Member\tJan. 2023 – Feb.
    2023"`, a real shape in `nina`'s "OTHER ACTIVITIES" section) was stored verbatim
    into `title`, tab and date included. Fixed by stripping the title at its own tab
    and using its date only as a fallback when the entry's primary header had none —
    the primary header's own date still wins when present.
- **Optional, explicitly opt-in LLM pass**: `propose.propose_bullet_tags(bullets,
  known_tags)`, modeled on `propose_vocabulary`'s existing "model selects, code
  enforces" contract — a proposed tag outside `known_tags` is dropped, never trusted,
  since a model is not a validator. Addressed by list position (no stable bullet ids
  exist yet at this point in the flow) rather than by id. Deliberately *not* cached
  (unlike `propose_vocabulary`): this is a one-off import action, not a repeated
  pipeline stage, so there is no hot path a cache would be protecting. Never part of
  `resume_import`'s own call graph — the web route runs it only when the caller passes
  `suggest_tags=true`, and a failure there becomes a warning in the response, not a
  failed import; the deterministic draft already produced is still useful on its own.
- **`POST /api/master-resume/import`** (multipart, optional `suggest_tags` field)
  returns `{resume, warnings, untagged_bullet_count}` and writes nothing — the same
  "draft, not a write" contract the template preview endpoints established in Phase 5.
  The editor loads the result as unsaved state via a new `editorState.loadDraft(resume,
  message)`, which intentionally does not touch the saved-snapshot comparison `dirty`
  is computed from, so the imported draft immediately reads as unsaved and the user is
  prompted to review before it can be lost.
- **Frontend**: `TemplateImportWizard.tsx` gained "Also import content from this file"
  (and, nested under it, "Suggest tags for untagged bullets") checkboxes. `confirmInstall`
  now returns a success boolean rather than `Promise<void>`, specifically so the
  wizard's chained "install, then import" action never has to read back a state
  variable a stale closure or React's batching could make wrong — the exact class of
  bug `PreviewCompare`'s manual-refresh design (Phase 5) was already worried about
  avoiding, here on the write side instead of the read side.
- **Tests**: `tests/importing/test_resume_import.py` (new, 13 tests) — full-fixture round trip
  through real JSON serialization (not just in-memory construction), entry-id collision
  safety across different section kinds sharing one flat namespace (matching `data.
  MasterResume._fill_entry_ids`'s own suffixing), the multi-experience-section fixture
  importing every section rather than just the first, and a dedicated regression test
  for each of the three bugs found above. `tests/document/test_render.py` gained 4 tests for
  `parse_month`/`parse_range`. `tests/pipeline/test_propose.py` gained 6 tests for
  `propose_bullet_tags` (prompt contents, dropping an out-of-vocabulary tag, an
  explicit empty-list answer counting as "no tags" rather than being ignored, an
  out-of-range bullet index not crashing, LLM failure propagating normally). 4 new
  `tests/web/test_web.py` tests for the API route (draft returned with nothing written to
  disk — content and mtime both asserted unchanged, non-docx rejected, the suggest-tags
  pass filling in untagged bullets via a stubbed `propose.propose_bullet_tags`, and a
  stubbed failure there degrading to a warning instead of a 500).
- **Verified against a live server**: analyzed and imported a hand-built synthetic
  .docx via real HTTP against a running `uvicorn` instance (no test doubles),
  confirming `warnings`/`untagged_bullet_count`/`resume.contact`/`resume.sections`
  all arrive in the shape the frontend expects. Full backend suite: 649 passed, 1
  deselected. Frontend: `tsc -b`, `oxlint`, `vitest run`, `vite build` all clean.

## 2026-08-07 - Table-layout resumes: `layout="table"`, a whole new physical shape the pipeline never had

**Trigger:** `Nina Dao - aug.docx` (a newer export of the same person the `nina`
workspace above is named after — same content shape, entirely different physical
layout) couldn't be parsed at all. `template_analyze` blocked on a blanket
`code="tables"` issue the moment it saw a `w:tbl` in the body; nothing downstream ever
ran. Root cause: the whole document's content lives inside one 20-row×4-col table used
purely as an invisible layout grid (no borders, no fill) to right-align
location/dates without tab stops — a legitimate, common Word/Google Docs export shape
this codebase had never supported. Full design writeup lives in the approved plan; this
entry is what actually shipped and what surprised me building it.

- **One flattened id space, shared by construction.** `docx_text.iter_document_paragraphs(doc)`
  is now THE only place a paragraph id is minted — depth-first: body children in order,
  descending into a `w:tbl` as rows → *physical* cells (`tc` children, not
  `Row.cells`, which python-docx expands over `gridSpan` and would silently double-count
  a merged cell) → paragraphs. `template_analyze._load_paras` and
  `template_build._para_by_id` both call it, which is what keeps `CharSpan.paragraph_id`
  meaning the same thing on both sides of the analyze/build boundary — the single
  invariant the whole template system rests on. `_para_by_id` stays a *recomputed* walk,
  never cached, for the same reason the existing "descending heading id" build order
  exists: a mid-build paragraph insertion (education's degree/detail-share-one-paragraph
  fallback) shifts every later id, and a cached list would silently resolve to the wrong
  paragraph the moment that happens.
- **`_has_tab_like` generalizes `has_tab` for one specific, load-bearing reason:** in a
  table layout a section heading always sits alone in its row (one populated cell); an
  entry header (company | location, degree | dates) always shares its row with a second
  populated cell. That's exactly the structural role a literal tab plays in a
  paragraph-layout resume ("Company | Location\tDates"), so every heading-detection gate
  that used to check `p.has_tab` now checks `_has_tab_like(p)` instead (row-based when
  `p.location` is set, literal-tab-based otherwise — a no-op for every existing
  paragraph-layout document, confirmed by the full suite passing byte-identically before
  any table-specific code was added).
- **Two surprises the real document produced that a synthetic fixture wouldn't have:**
  (1) the flattened id space doesn't start at the table — this document's body is
  `p, tbl, p, sectPr` (two empty body paragraphs bracket the table), so the name lands
  at paragraph id 1, not 0. `resume_import._import_contact`'s old `paras[0]`/`paras[1]`
  convention would have silently imported an empty name. (2) `_classify_heading`'s
  lowercase-substring heuristic tier matches `"skills"` against `"technologies"` —
  meaning the row-19 label `"Skills:"` (a value cell in a label/value skills grid) reads
  as a heading candidate on text alone. Neither bug is table-specific in origin; both
  were just never reachable before because the paragraph-layout gates that would catch
  them (`p.has_tab`, `_immediately_follows_entry_header`) happened to also catch these
  cases by coincidence. Fixed by generalizing the position-based gates (`_has_tab_like`)
  rather than special-casing the heuristic keyword collision.
- **Linear-vs-sidebar classification is not width- or majority-based.** Tried "row is
  majority full-width" first — fails on this exact document (12 of 20 rows are
  entry-header rows, i.e. two-cell, against 8 full-width ones). Tried "cell 0 is the
  widest cell" next — fails on the skills row, where the label cell (1509 twips) is
  narrower than the value cell (8859 twips). What actually holds for "used only as an
  invisible layout grid": no row has 3+ populated cells, no bullet or heading ever sits
  outside cell 0, nothing is vertically merged. `classify_table_layout` blocks on the
  first violation of those, in a fixed order, each with a message naming the offending
  row.
- **Contact block gets a new optional `ContactMapping.slots: list[ContactSlot]`**
  (`paragraph_id`/`fields`/`separator` per slot) rather than trying to force a
  multi-paragraph, multi-cell contact block through the existing single-paragraph
  joined-line `ContactMapping`. Empty `slots` (every profile before this field existed,
  and any ordinary single-paragraph contact block, table layout or not) is byte-identical
  to today. A street-address line with no recognizable field
  (`_contact_fields_present` returns nothing for it) is left as a template literal with a
  non-blocking `contact_unmapped_paragraph` warning — deliberately not guessed at, since
  `data.Contact` has no address field and inventing one to swallow a single document's
  shape isn't worth the ripple through the editor/API schema/import path.
- **Row-level repetition needs its own marker rows — paragraph-level `{%p for %}`
  doesn't survive inside a table row.** Verified by reading `docxtpl` 0.20.2's
  `DocxTemplate.patch_xml` source rather than assuming: the `tr`-tag pass (processed
  *before* the `p`-tag pass) replaces the **entire** `<w:tr>` containing a `{%tr %}` tag
  with the bare Jinja text — the row is consumed, not repeated. So every row-level
  `for`/`if`/`endfor`/`endif` gets its own disposable one-cell marker row
  (`template_build._marker_row`), and the rows meant to actually repeat sit between an
  open marker and a close marker. This is exactly a well-formed-XML-but-wrong trap (the
  intermediate tagged template opens fine in Word, looks structurally plausible, and
  silently produces nothing at render time), so it's now also in CLAUDE.md's
  "Non-obvious gotchas".
- **The one real bug found only by rendering to PDF and looking at it, not by any of the
  structural checks:** `template_build.build_contact_profile` correctly tagged
  `contact_slot_0`/`_1`/`_2` into the built template, `verify_tagged` and
  `verify_roundtrip` both came back clean — but the actual rendered PDF showed the name
  and street address only, with email/phone/city-state blank. `render.build_context`
  had never been taught to *supply* `contact_slot_<i>` context keys at all; Jinja's
  default-undefined behavior for a missing RichText key renders empty rather than
  erroring, so nothing caught it structurally. `verify_roundtrip` didn't catch it either
  because its own field checks only ever asserted against `profile.experience`/
  `profile.education`/`profile.projects`, never against contact fields. Fixed in
  `render.build_context` (loop over `layout["contact_slots"]`, build one
  `_contact_richtext` per slot, intersected with any `--contact-fields` override). Left
  as a documented gap rather than adding a new automated check for it in this session:
  a real visual/PDF diff of contact-block rendering would need calibration-style
  tooling `template_verify.py` doesn't have yet.
- **A cell holding several repeatable items (three stacked bullets, three skill-group
  labels) needs everything but the FIRST stripped after wrapping it in a loop** — the
  chosen prototype is always the first of its kind (`bullet_paragraph_id`/
  `detail_paragraph_id`/a skills `label_span.paragraph_id` all name the first occurrence,
  an existing convention, not something new here), but the row gets cloned once as the
  loop's per-iteration template, so an untouched second/third sibling would render
  verbatim on *every* entry instead of being replaced by however many the loop actually
  produces. `_wrap_cell_loop` now removes every paragraph *after* the wrapped one within
  its own cell (never before — that's fixed content, e.g. a school/degree line the
  education fallback's synthetic single-paragraph detail clone sits after). Caught by
  rendering the actual built template and finding "Led outreach..."/"Represented the
  company..." duplicated verbatim beside the `{%p for bullet %}` loop in a bullet cell
  that should have held only the loop.
- **Verified against the actual driving document end to end, including a visual PDF
  diff against the original**, not just the structural checks: analyze → import →
  build → `verify_tagged` (0 issues) → `verify_roundtrip` (0 issues) → render →
  Word-COM PDF conversion, side by side against the original document's own PDF. Same
  table grid, same right-aligned dates, same header rule, same bullet formatting;
  the tailored render is one page where the original slightly overflows to a second
  (the redistributed bullets are marginally shorter). `fit.estimate_lines` runs
  unmodified against a table-layout profile and returns a plausible count — confirms
  the plan's prediction that `fit.py` needs no logic change, only a correct `layout`
  dict, which it already gets from `template_profile.active_layout`.
- **Deferred, not shipped this session:** the frontend wizard's `SectionMapStep`
  doesn't yet show a `layout="table"` badge or list contact slots read-only (currently
  falls through to the generic-mode UI, which is not wrong, just silent about the
  extra structure). `POST /api/template/preview/draft` and `POST /api/template` were
  not smoke-tested through the actual FastAPI routes in this session — only the
  underlying `analyze_docx`/`build_from_profile`/`import_from_analysis`/`render.render`
  functions were exercised directly. Full backend suite: 666 passed, 1 deselected
  (started at 649; net +17 covering the flattened walk, table classification, and the
  build/import/verify round trip on a synthetic fixture reproducing the driving
  document's exact row shapes).

## 2026-08-07 - Wizard field-detection rows were kind-wide, not section-wide: false "not detected" on every second same-kind section

- **What:** Uploading `Nina Dao - aug.docx` (the `layout="table"` driving document
  above) through the Template wizard showed LEADERSHIP's company/dates as red
  "not detected" rows, even though the section installs and renders correctly. Root
  cause was general, not table-specific: `_analyze_document` only ever emitted
  `FieldCandidate`s for one *pooled* prototype entry per **kind** (`combined_body[kind]`,
  spanning every same-kind section), while `AnalyzeReport.tsx` attributed candidates to
  a section by checking whether `paragraph_id` fell inside that section's own
  `[body_start, body_end)` range. A candidate from a different same-kind section's
  prototype never falls in that range, so the second (and any later) same-kind section
  always read as undetected — confirmed on the legacy paragraph-layout `nina` export
  too (`INTERNSHIPS & PROGRAMS`/`OTHER ACTIVITIES` both showed the same false red rows),
  so this predates table-layout support entirely and was just never visible until a
  document with more than one same-kind section got run through the wizard.
- **Why:** The *installed* mapping is correctly kind-wide by design — one prototype
  entry per kind is what `template_build` actually clones. But the wizard's display is
  per-section, so display and install need different scopes; conflating them was the
  bug. Fix: `_section_field_candidates(paras, sections, ..., pick=...)` (new,
  `template_analyze.py`) loops every same-kind `SectionCandidate`, splits its own body
  into entries, reconciles *that section's own* field presence rate via the existing
  `_reconcile_header_fields`, and picks its own prototype with the same tie-break the
  kind-wide code already used (`_exp_score`/`_edu_score`/`_proj_score`, hoisted from
  inline closures/lambdas to module level so both the install site and the display
  helper share one definition each). Every `FieldCandidate` now carries
  `section_heading_paragraph_id`, and the frontend filter prefers that explicit
  attribution over the old range-based inference (kept as a fallback for a candidate
  that somehow carries no section id, which none now do).
- **Impact:** `FieldCandidate`/`TemplateFieldCandidateOut` gained the new field —
  additive, so nothing that constructed one before breaks. Bonus fix caught while
  hoisting the projects tie-break: the *installed* Projects prototype's header was
  still being resolved via the plain-text-only `_header_fields_from_text`, bypassing
  the cross-cell dispatcher (`_entry_header_fields`) that experience/education already
  routed through — a table-layout resume with a Projects section would have
  reconciled dates fine and then silently lost them on the actual installed mapping.
  Swapped to `_entry_header_fields(proto, ..., exclude_after=exclude_after)`; falls
  through to the old text path when the row has no second populated cell, so
  paragraph-layout behavior is unchanged. Verified end to end through the actual
  `POST /api/template/analyze` route (FastAPI `TestClient`, not just the underlying
  function) against both `Nina Dao - aug.docx` and the legacy `nina` export — no
  section shows a false "not detected" row on either anymore, and the build/render
  smoke path (analyze → `build_from_profile` → `verify_tagged` → `render.render`) still
  produces a clean, fully-populated document. Backend suite: 671 passed (was 666), 1
  deselected; frontend `tsc -b` and `vitest run` clean (oxlint itself couldn't run in
  this session — a local Windows Application Control policy blocks its native binding,
  unrelated to this change).

## 2026-08-08 - "Also import content" now merges into the master resume instead of silently discarding it

- **What:** Checking "Also import content from this file" in the Template wizard
  parsed the upload correctly (contact, entry locations, everything) but only called
  `loadDraft(...)` — pure React state, never persisted, discarded by navigating away or
  a page refresh. Fixing it as a straight `PUT` (full replace) would have been wrong:
  `master_resume.json` is deliberately a *superset* (CLAUDE.md: "bigger than any one
  resume, so an ops/support-flavoured posting can surface roles a tech-flavoured one
  wouldn't"), and a single upload — especially an already-tailored export like
  `Nina Dao - aug.docx` — is a subset. A full replace would have silently deleted every
  entry not present in that one file.
- **Why:** The fix is a merge: match incoming entries against existing ones by
  company/school/project/skills-label/list-text identity; a match refreshes that entry
  in place (its bullets are the whole point of re-importing); no match adds it; anything
  in the existing resume with no counterpart in the upload is left completely
  untouched. Validated by construction against the real `nina` workspace data before
  writing any code — see the design's own "Validated against the real data" table —
  which caught two real bugs in the first draft before they shipped:
  1. **Section-scoped matching would have duplicated entries.** Nina's export titles a
     section `LEADERSHIP`; the existing workspace's section is titled
     `LEADERSHIP EXPERIENCE`. Those titles don't match, so if matching had been scoped
     to a title-matched section first, *In the Green at UCI* and *Yellow Daisy
     Organization* — both already present under `LEADERSHIP EXPERIENCE` — would have
     been duplicated into a brand-new `LEADERSHIP` section instead of updated in place.
     Fixed: `resume_import.merge_into` matches entries **globally across every
     same-kind section**, never scoped to a title match; only *unmatched leftovers*
     ever need a target section resolved (`_target_section_index`), and a section is
     created only when it actually receives leftovers — so `LEADERSHIP` (all of whose
     entries matched elsewhere) adds nothing and no duplicate section appears.
  2. **`config.slugify` is unsafe as an equality key.** It caps output at 40 characters
     (right for minting a short id, wrong for identity) — two distinct 50+ character
     company names sharing a 40-char prefix slugify to the same string, and one would
     silently overwrite the other. Confirmed with a concrete pair before writing the
     fix. `resume_import._match_key` is a separate, uncapped normalizer used only for
     merge-matching; `config.slugify` still mints ids as before.
- **Impact:** New `resume_import.merge_into(existing, incoming) -> (MasterResume,
  MergeStats)` — pure, no I/O, reuses `_fresh_id`/`_import_bullets`'s id scheme. A
  matched entry keeps its *existing* id (nothing referencing it elsewhere breaks) with
  bullets re-minted under that id; contact merges field-by-field and only overwrites
  where the incoming value is non-empty (a blank LinkedIn field from a hyperlink-less
  export must not erase a curated URL); `summary_variants`/`_comment` carry over from
  `existing` untouched; `tag_vocabulary` is unioned. New `POST /api/master-resume/merge`
  (takes an already-parsed `MasterResume` body, e.g. straight from `/import`'s
  response — no re-upload) does the actual save: `_backup_master_resume` now returns
  the backup `Path` instead of `None`, and a new `_write_master_resume` helper
  (mkdir + backup + write) is shared with `put_master_resume` so the write path is
  defined once. `POST /api/master-resume/import` itself is completely unchanged — still
  parses and writes nothing; the existing
  `test_import_master_resume_returns_a_draft_without_writing` pins that. Frontend:
  `editorState` gained `syncFromDisk` (sets both `resume` and `savedSnapshot` together,
  since the merge endpoint already wrote to disk — must never read as an unsaved
  draft); the wizard checkbox is relabeled "Also merge…", confirms via `window.confirm`
  before writing, and its success panel lists the actual updated/added entry names (not
  just counts) from the response — a near-miss duplicate, like the education entry
  below, is visible immediately rather than buried in a total.
- **One accepted false split, by design, not a bug:** the existing `nina` workspace
  stores education as `"University of California, Irvine"`; Nina's export says
  `"University of California, Irvine --- Paul Merage School of Business"` — a different
  string, so it's correctly treated as a *new* entry (reported in `added`), not merged.
  Pinned directly in `tests/importing/test_resume_import.py`. The user reconciles the duplicate by
  hand on the Master Resume tab; silently fuzzy-matching schools was rejected as more
  dangerous than an occasional visible duplicate.
- Verified end to end through the real HTTP endpoint (FastAPI `TestClient`, not just
  the pure function) against the actual `nina` workspace data + `Nina Dao - aug.docx`:
  3 updated, 5 added, 0 new sections, all 7 untouched entries' ids preserved exactly,
  a `.bak.json` holding the byte-identical pre-merge file, and a second merge of the
  same file reporting 0 added (idempotent). Backend suite: 705 passed (was 689), 1
  deselected — 19 new tests (`merge_into` matching/section-targeting/contact rules in
  `test_resume_import.py`, endpoint write/backup/missing-file/invalid-body behavior in
  `test_web.py`). Frontend `tsc -b` and `vitest run` clean.

## 2026-08-08 - Merge wasn't updating coursework because the education entry never matched, not because parsing failed

**What:** Reported as "merge doesn't update relevant coursework." Coursework parsing was
never broken (`_COURSEWORK_RE` reads `Relevant Coursework: …` correctly) — the bug was in
`_merge_education`'s matching. `data/workspaces/nina/master_resume.json` had
`school="University of California, Irvine"`; Nina's export said
`"University of California, Irvine --- Paul Merage School of Business"`. Exact
`_match_key` equality treated these as unrelated, so the merge *added* a second education
entry (carrying the coursework) instead of updating the first — the coursework existed on
disk, just on the wrong entry. This exact behavior — "an incoming school string that
differs, even by an added suffix, does NOT match" — was the previous entry's own accepted
design decision; the user has now rejected that trade-off in favor of matching it.

**Second bug found while tracing the first:** `_merge_education` replaced a matched entry
*wholesale* (`sections[si].entries[ei] = inc.model_copy()`), unlike `_merge_experience`/
`_merge_projects`, which already update named fields only. Had the school strings matched,
the curated `gpa="3.92"`/`show_gpa=True` would have been silently wiped — the .docx writes
GPA as a free-text detail line (`Cumulative GPA: 3.9/4.0…`), which `_GPA_RE` correctly
declines to parse (it requires the `| GPA: …` form), so `incoming.gpa` is empty. Fixing only
the matching would have traded a visible duplicate for silent data loss.

**Fix:** `_is_near_miss(a, b)` — boundary-anchored suffix match on `_match_key` (`long.
startswith(short + "-")` or the mirror), scoped to `Education.school` only via a new
`_MIN_NEAR_MISS_KEY = 4` floor. Deliberately not extended to company/project/skills/list
matching: an institution's name legitimately grows a school/college suffix across two
exports of the same resume; a company's generally does not, and the user chose to keep
those exact. `_merge_education` now runs two passes — exact first (unchanged), then
near-miss only over what exact left unclaimed — so a resume already holding both a short
and a long spelling of one school resolves unambiguously rather than fuzzily contesting the
same incoming entry. A near-miss match against >1 existing candidate is refused (added as
new, with a warning) rather than guessed. `_merge_education_entry` replaces the wholesale
copy with a `_merge_contact`-style field-by-field merge: empty incoming fields never blank
a populated existing one; `show_gpa` (a bool, so truthiness can't distinguish "not found"
from a deliberate `False`) is only adopted alongside a non-empty incoming `gpa`.

**Data fixed too:** the two UCI entries already sitting in `data/workspaces/nina/
master_resume.json` from the earlier (pre-fix) merge predated this change and would not
merge themselves, so a one-time script applied the identical `_merge_education_entry` rule
to collapse them — backed up first (`.bak.json`, the same convention `_write_master_resume`
uses), then re-validated through the real `python -m resume_tailor.content.data --validate`. Result:
one EDUCATION entry, coursework populated, `gpa="3.92"`/`show_gpa=True` intact. `data/` is
gitignored, so this touched no repo state.

**Verified:** 7 new/rewritten tests in `test_resume_import.py` (the reported case; GPA
survives while coursework updates; empty-incoming-never-blanks; exact-beats-near-miss with
both spellings present; ambiguous near-miss added-not-guessed with a warning; genuinely
distinct schools stay distinct; near-miss scoping — a company differing by the same kind of
suffix still does not match). Full suite: 717 passed (was 712), 1 deselected. Also verified
live and unmocked, twice for idempotency, through the real `POST /api/master-resume/merge`
against the actual reconciled `nina` data and the real `original_export.docx`: the UCI entry
comes back `updated` (not `added`), still exactly one education entry, coursework and
`gpa=3.92`/`show_gpa=True` both stable across both runs.

## PDF import (P3-P, 2026-09)
- `resume_import_pdf.py` turns a PDF's text layer into the same `ImportedResume` draft as the .docx importer; `POST /api/master-resume/import` routes by `.pdf` extension or `%PDF-` signature. A PDF is content only: it never becomes a template.
- Library: pdfplumber (MIT, on pdfminer.six). PyMuPDF was ruled out because it is AGPL. pdfplumber pulls in Pillow.
- Lines are built from raw characters, not `extract_words`: rows by baseline, a word gap at >0.3 em (handles Canva-style letter placement), a segment break at >2 em. A tab-aligned date becomes `"\t"`, the same convention the .docx side uses.
- Two columns are detected per page by a gutter: many segments start at the same mid-page x, and almost none span across it. Right-aligned dates fail the "nothing spans" test because bullets run the full width, so single-column resumes aren't split.
- Wrapped lines rejoin when a line is indented to the previous bullet's text start (or the previous line ends in a comma/connective). A hard hyphen at a line end is kept ("cross-functional"). A soft hyphen is dropped. This is a deviation from the plan's blanket de-hyphenation, which would corrupt real compounds.
- The model-assisted pass (opt-in `use_model`) answers with line numbers, and bullets are always the PDF's own lines. Field strings (company, title, dates, location) must be substrings of their cited header lines, or a ≥0.9 difflib match of a segment. Anything else is dropped with a warning, and unplaced lines are listed in the warnings. It rides the `extract` purpose like `propose.py` rather than adding an `import` purpose. The cache key is `_PROMPT_VERSION` + `fingerprint("extract")` + the numbered text. Any model failure falls back to the heuristic draft.
- Test PDFs are written by `tests/pdf_fixtures.py` (hand-rolled PDF with standard Helvetica fonts; no reportlab). The e2e server serves one at `/e2e/resume.pdf`, so no binary fixture is committed.

## P3-D: upload clean-up, header contact, content-only import (2026-09)
- `docx_normalize.prepare` runs before analyze and before resume import. It works on a copy. It accepts tracked changes, removes comments, and unwraps content controls (deepest `w:sdt` first). On request, it also converts typed bullet glyphs into a generated bullet list. Each change becomes a non-blocking issue notice.
- Normalisation is deterministic and a clean file comes back byte-for-byte, so the hash analyze records still matches at install. LibreOffice conversion (.doc/.odt/.rtf) is *not* deterministic. For that reason `template_ops` caches the prepared bytes under the upload's sha with a `{sha}.origin` file naming the original hash, and install reuses them.
- Typed-bullet conversion (plan D8) runs at upload normalisation, as an opt-in `convert_bullets` form flag (the "Convert typed bullets" button on the `manual_bullets` issue). It does not run in `template_build`, so the build module still sees only real list items.
- A name or contact found only in the page header sets `TemplateProfile.name_in_header` / `contact_in_header` (`contact=None`). The build and verify steps skip those tags, the header stays verbatim, and the analyzer emits a non-blocking `contact_in_header` issue instead of `missing_contact`. Resume import still reads the contact from the header (`resume_import.header_contact`).
- Layout blockers (`LAYOUT_BLOCKERS`: text boxes, sidebar tables) no longer dead-end resume import. `resume_import.docx_lines` reads text boxes in anchor order and tables column by column, and `import_content_only` feeds them through the PDF importer's `clean_lines` + `import_lines`, so both formats share one structuring path.
- `.pages` is refused with export advice, because LibreOffice can't read it.
- The analyzer's loose `manual_bullets` check still flags a line like "-5% …". That is pre-existing behaviour and left alone; the test asserts only that converted lines are no longer flagged.

## P3-E: structured education months (2026-09)
- `Education.start` / `Education.end` are optional `YYYY-MM` strings, used only by application forms. The printed line is still `dates`, exactly as written, so rendering and every LLM stage are unchanged (no stage dumps Education models into a prompt).
- `edu_dates.months()` reads date *tokens* in order: ISO `2022-09`, `09/2022`, month names, seasons, `May '27`, and "Present" as an open end. It doesn't split on dashes, which broke `2022-09 to 2026-06`. Two tokens give start and end; one token is the graduation date. Bare years give "", because inventing a month would be a fabricated fact on a form. Seasons map by convention (Fall start → 09, Spring graduation → 05) and are shown in the editor for correction.
- Filling happens in `_write_master_resume` (the one web write path), and only fills empty fields, so a month the student picked survives. Editing Dates in the editor clears both months, so they are re-read on save rather than going stale.
- The packet's single-value questions ("School", "Graduation date") use `current_education()`: the row with the latest `end`, so a transfer student's new school or the later of two degrees wins. Ties and undated rows keep resume order. Repeaters still fill every row in resume order. Old files with no months fall back to `render.parse_range`, as before.
