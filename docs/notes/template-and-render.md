# Template build & render — implementation notes

Covers: template build/tagging, header/bullet formatting, project links, hyperlinks in PDF, contact/name line, template tab & library, build verification, legacy build retirement.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-07-26 ? Skills lines rendered fully bold

**What:** `build_skills` in `scripts/build_template.py` now splits its tag across two runs
? `{{ group.label }}:` in the export's bold label run, ` {{ group.entries }}` in its plain
body run ? instead of writing both into run 0 and deleting the rest. Template regenerated.

**Why:** Every SKILLS line in `original_export.docx` is exactly two runs (bold `AI/ML:`,
plain ` RAG pipelines, ...`). Collapsing to one run discarded the plain run's formatting,
so the whole rendered line inherited the label's bold. Same principle as `tag_header`:
formatting is inherited from the real XML, so the tags must land in the runs that carry it.

**Tradeoff:** The prototype selection now requires a line with ?2 runs. If a future Google
Docs export merges them, the one-run fallback clones the label run and forces `bold = False`
rather than failing ? a hardcoded assumption that the plain body is simply "not bold",
which holds for this resume but would not survive the body run gaining its own styling.

**Follow-up:** No regression test yet; `tests/document/test_render.py` skips when the template is
unbuilt, so a bolding assertion there would only run on a machine that has `templates/`.

## 2026-07-27 ? Bullet marker size and experience header bold split

**What:** `scripts/build_template.py` now (1) normalizes every lvl0 bullet definition in `numbering.xml` to `Noto Sans Symbols`, (2) retargets experience/project bullet prototypes to the education list id, (3) picks experience headers with separate company/location runs, and (4) inserts a plain run in `tag_header` when fields would otherwise merge into a bold run.

**Why:** Google Docs exported six nearly duplicate list defs; `pick_bullet_prototype` chose spacing-tight bullets whose markers drew in Lora (large dots) while education kept Noto (small dots). Experience headers used `min(header_run_count)`, collapsing `{{ job.location }}` into the bold company run.

**Impact:** Re-run `python scripts/build_template.py` after any resume re-export. Education spacing already matched experience at the paragraph-property level once numIds unified ? no education-only spacing rewrite was needed. Regression tests in `tests/document/test_render.py` cover Noto markers, shared numId, and bold company / plain location.

## 2026-07-27 ? Force single line spacing in template build

**What:** `scripts/build_template.py` now runs `normalize_single_spacing` after tagging: every body paragraph gets `w:line=240`; non-list paragraphs use `lineRule=auto` (Word ?Single?), list paragraphs use `lineRule=exact` (240 twips = 12pt). Rebuilt `templates/main_template.docx`.

**Why:** Owner reported line spacing > 1. Export already had auto/240 on most content, but name/contact/spacers were unset, and LibreOffice PDFs showed ~15.7pt wrap pitch on bullets for 10pt text ? auto line boxes inflate when the bullet marker font is substituted (DejaVuSans when Noto is missing). Exact locks bullet line height.

**Tradeoff:** Exact 12pt on bullets is slightly tighter than Word?s font-metric ?Single?; may shift fit calibration. Re-run `scripts/calibrate.py` (and inside Docker for soffice) if page packing looks off.

**Follow-up:** Optional: install Noto Sans Symbols in the container so marker metrics match Word without relying on exact.

## 2026-08-01 ? Project link toggle (`--no-project-links`)

- **Decision:** Negative opt-out (`no_project_links` / `--no-project-links`), default
  off so links still render. Threaded `include_project_links` through `render` ? `fit`
  ? CLI and web; UI toggle labeled "Hide project links".
- **Why:** Some postings/applications want the project name without a Github hyperlink;
  the link is built per-entry as RichText in `build_context`, so the suppress path emits
  the same empty RichText link-less projects already use (template `{{r }}` still safe).
- **Tradeoff:** Hiding the link frees no page lines (inline in the header). Named as a
  negative flag to match `--no-expand` / `no_semantic`.
- **Impact:** Rebuild Docker for the SPA toggle; CLI works after API restart alone.

## 2026-08-01 ? Drop ` | ` with suppressed project links

- **Decision:** Moved the ` | ` before the project link out of the template tech run
  into the link `RichText` in `render.build_context`. Template rebuild required
  (`scripts/build_template.py`).
- **Why:** `include_project_links=False` already emptied the link RichText but left the
  baked-in separator after tech (`"{{ proj.tech }} | "`), so headers ended with a
  dangling pipe.
- **Tradeoff:** None ? same visual when links are on; separator still plain (not part of
  the hyperlink run).
- **Impact:** Rebuild template (done locally); Docker needs a rebuild/restart if the
  container copies `templates/` at image build time.

## 2026-08-02 ? Contact + education become data-driven

- **Decision:** `build_template.py` now tags the contact line as `{{r contact }}` and
  loops EDUCATION from the master resume. Contact shows hyperlinked "LinkedIn" /
  "GitHub" labels (not full URLs). Coursework is a `list[str]` joined into one
  "Relevant Coursework:" bullet; GPA appends to the degree line when `show_gpa` is on.
- **Why:** Editing those fields in the UI previously changed JSON only ? the template
  still carried literal text from the Google Docs export.
- **Tradeoff:** First deliberate visual change to the baseline (URL ? labelled link).
  Name line stays literal. Deleted the NYU summer-program education entry so it would
  not start appearing once education rendered from data.
- **Follow-up:** Look at a rendered PDF to confirm the contact line still fits one line
  with both LinkedIn and GitHub.

## 2026-08-01 ? Template tab (view + upload/rebuild)

- **Decision:** Third UI tab at `/template` with `GET/POST /api/template` and `GET /api/template/preview.pdf`. Upload replaces `templates/original_export.docx`, shells out to `scripts/build_template.py`, and regenerates a filled PDF preview under `output/template/`.
- **Why:** Matches the documented re-export workflow (copy baseline -> rebuild) without hand-editing the tagged template. Subprocess keeps `build_template.py` the sole producer of `main_template.docx` (CLAUDE.md hard rule) with no 770-line refactor.
- **Tradeoff:** Build failures surface stdout/stderr as a string log rather than structured section-missing errors. Fit constants stay module-level; after a template swap the UI flags `calibration.stale` and tells you to run `calibrate.py` + restart ? auto-calibrate from the web process is out of scope.
- **Spec delta:** Writes to `original_export.docx`. CLAUDE.md hard rule updated to allow
  the documented re-export path (CLI copy or the Template tab); hand-edits remain forbidden.
- **Follow-up:** Optionally extract build logic into `src/resume_tailor/document/template_build.py`
  for structured errors.

## 2026-08-01 ? PDF hyperlinks dead under LibreOffice

- **Decision:** After `render.render` saves a .docx, patch hyperlink runs with `InternetLink`
  character style and register that style in `styles.xml`. RichText adds also pass
  `style="InternetLink"`.
- **Why:** Docker/soffice paints blue underlines but emits zero PDF Link annotations unless
  the run has `w:rStyle w:val="InternetLink"` *and* `styles.xml` defines that styleId.
  Word keeps links without either. Google Docs exports omit the style; docxtpl alone was
  not enough.
- **Tradeoff:** Small zip rewrite on every render (harmless for Word). Existing job PDFs
  stay unclickable until re-tailored after the image rebuilds.
- **Follow-up:** Rebuild the Docker image so the container picks up `src/` (not bind-mounted).

## 2026-08-01 - Name line driven by contact.name

- Decision: build_template.py now tags the name paragraph as {{ name }} (a new top-level context key, not contact.name), and render.build_context adds "name": resume.contact.name.
- Why: The name was previously literal text from the Google Docs export, so editing contact.name in the master resume (or the web editor) had no visible effect on the rendered resume. User asked for it to be driven by contact.name.
- Why a separate "name" key instead of contact.name: the "contact" context key is already bound to the RichText contact *line* built by _contact_richtext (location/email/phone/LinkedIn/GitHub), which has no .name attribute - reusing it would have broken the tag.
- Impact: templates/main_template.docx was regenerated via scripts/build_template.py to pick up the new tag. Verified end-to-end (render with a different contact.name changes paragraph 0) and full suite (221 tests) still passes.
- Spec delta: CLAUDE.md's template-generation section previously said "the name line stays literal (it does not vary by posting)" - corrected to describe the new tagged behavior.

## 2026-08-01 ? Optional calibrate-after-install from the Template tab

- **Decision:** Multipart `calibrate=true` on `POST /api/template` runs
  `resume_tailor.document.calibrate.run()` after a successful install, then
  `config.reload_calibration()` so the live process picks up new CHARS_PER_LINE /
  LINES_PER_PAGE without a restart. UI checkbox defaults **on**.
- **Why:** User asked for one upload path that does build + calibrate. Leaving it optional
  keeps fast installs when only the mapping changed.
- **Tradeoff:** Owner-specific anchor checks soft-fail (warnings in the log) so a different
  layout does not undo a good build. Calibration still needs Word/LibreOffice and can take
  tens of seconds; failures leave the installed template intact.
- **Spec delta:** `scripts/calibrate.py` is now a thin wrapper over the package module.

## 2026-08-02 ? Named template library

- **Decision:** Successful Template-tab installs snapshot baseline + tagged (+ optional
  profile) under `templates/library/<id>/` with a user label. Live paths remain
  single-slot; activate copies a snapshot in. Cap 20; unique labels (case-insensitive).
  Empty library seeds `Default` from the current live files.
- **Why:** User asked for a named library to choose among uploaded templates without
  re-uploading.
- **Tradeoff:** No per-template calibration files ? activate can re-run calibrate into
  the global backend file. Orphan live content that is not yet in the library is
  auto-snapshotted before overwrite/activate when space allows. `templates/backups/`
  stays install-rollback only and is not exposed in the UI.
- **Spec delta:** New APIs `GET/PATCH/DELETE /api/template/library`,
  `POST .../activate`; multipart `label` on `POST /api/template`;
  `TemplateInfo` includes `active_library_id` / `active_label`.

## 2026-08-02 ? Project header `name | tech | Github` span overlap

- **Decision:** `_header_fields_from_text` only maps the first two pipe segments to
  primary/secondary. Trailing segments (project link labels) stay unclaimed so link
  detection can own them without overlapping `tech`.
- **Why:** Live resume line
  `Text-to-SQL ? | GRPO, ?, SQL | Github\\tdates` made tech include `| Github`, then
  link span `Github` overlapped and staged install raised.
- **Tradeoff:** A third pipe field on experience/education headers is ignored (those
  sections do not use a link field). Acceptable for the single-column contract.

## 2026-08-02 - Profile-mode header tagging: bold bleed, lost tab, doubled link separator

- **Decision:** Replaced `_tag_mapped_header`'s flatten-into-one-run splice with a
  segment-based rebuild (new `docx_text.py` + `template_build.build_segments` /
  `rebuild_paragraph` / `retag_paragraph`). Each surviving literal or tag now gets its
  own run cloned from whichever source run covered that character offset in the
  uploaded document, instead of everything collapsing into `paragraph.runs[0]`.
  `build_projects_profile` no longer calls `strip_hyperlinks` before tagging, and the
  `" | "` before a project link is now dropped by the builder (keyed off which field
  owns a render-supplied separator, via a punctuation character class rather than a
  fixed string) instead of being emitted into the template at all.
- **Why:** Three live bugs, confirmed against the user's own uploaded template
  (`templates/library/.../<owner> Resume.docx`): project dates lost their
  right alignment, the whole skills line rendered bold, and project tech tags rendered
  bold with a phantom/doubled `|` before the GitHub link. Bold bleed: `_tag_mapped_header`
  and `build_skills_profile` both wrote the whole reconstructed line into run 0 and
  deleted the rest, so the bold company/label run's formatting leaked over everything —
  same failure mode the 2026-07-26 skills-bold fix addressed in *legacy* mode, just not
  yet ported to profile mode. Lost tab: `python-docx`'s `Paragraph.text` includes
  hyperlink visible text while `Paragraph.runs` excludes hyperlink-nested runs;
  stripping the hyperlink *before* tagging shortened the text the profile's spans were
  measured against, sliding every later offset left until the tab character fell inside
  the link's span and was deleted along with it. Phantom separator: `render.py` already
  puts `" | "` inside the link `RichText` (so a link-less project doesn't render a
  dangling pipe), but `_tag_mapped_header` also emitted the literal `" | "` between the
  tech and link spans verbatim, so a project with a link rendered `Tech | | Github`.
- **Tradeoff:** Experience/education profile headers that used to collapse into 1-2 runs
  now produce one run per tagged field (functionally identical in Word, more runs on
  disk — pinned by `test_profile_and_legacy_headers_agree`). `validate_profile_against_doc`
  is now stricter — checks every mapped span (previously only `company`/`title`), and
  rejects a span that straddles a tab or overlaps another — so a previously-installed
  `templates/library/` profile that silently produced a garbled template may now fail
  re-validation on install. Intentional (fail loudly beats a silent garble), but worth
  knowing if an old saved template stops installing.
- **Impact:** Also de-hardcoded the project link-label detection in `template_analyze.py`
  — it now reads the hyperlink's own visible text (`docx_text.hyperlink_char_spans`)
  instead of matching `("Github","GitHub","Demo","Link","Live")`, and fixed a crash where
  a link-but-no-tech header (`"Name | Github\tdate"`) made `tech` and `link` claim the
  same span. Verified by rebuilding the user's real saved profile
  (`templates/library/20260802T073928Z-8bd4/`) and diffing run structure against the
  known-good legacy build; live template files (`templates/main_template.docx`,
  currently the legacy "Default") were left untouched per the user's choice — re-upload
  through the Template tab to pick up the fix. 15 new tests across
  `tests/document/test_template_build.py` / `tests/document/test_template_analyze.py`; full suite 272 passed.
- **Spec delta:** None — bug fix within the documented profile-mode contract
  (CLAUDE.md "Template generation").

## 2026-08-05 - Build verification: hold a tagged template accountable to its own mapping

- **The gap this closes**: `_smoke_render` (`web/template_ops.py`) only proves a built
  template opens and renders without an exception — it says nothing about whether the
  render used the fields it should have. A profile whose `dates`/`location` never got
  detected on an experience header builds a template that opens fine, smoke-renders
  fine, and silently drops every job's dates from every resume built with it,
  forever, with nothing in the install flow ever saying so.
- **`template_build.py`'s Jinja tag strings hoisted to module constants**
  (`NAME_TAG`, `CONTACT_TAG`, `EXPERIENCE_HEADER_TAGS`, `BULLET_TAG`,
  `EDUCATION_HEADER_TAGS`, `PROJECT_HEADER_TAGS`, `SKILLS_LABEL_TAG`/`_BODY_TAG`,
  `LIST_ITEM_TAG`, `SECTION_TITLE_TAG`, `SECTION_LOOP_OPEN`, …) — every
  `_tag_*_prototype` function updated to reference them instead of inlining the
  literal string a second time. Purely mechanical (verified against the existing
  33-test `test_template_build.py` suite, unmodified, before writing anything new);
  the point is that `template_verify.py` can read the exact same constants tagging
  emits, so the two can never quietly drift into disagreement about what "tagged
  correctly" means. `BULLET_TAG` is deliberately shared between experience and
  projects (each is a different `{%p for bullet in ... %}` loop's own variable, so
  identical tag *text* is not evidence of a leak) — documented at the constant so
  `expected_tags` doesn't try to assert an exactly-once count for it.
- **New `src/resume_tailor/document/template_verify.py`**, two checks:
  - `verify_tagged(tagged, profile)`: `expected_tags(profile)` (every tag a correctly
    built template must contain, derived by walking the profile's own `OptionalSpan.
    present` flags against the same module constants) must all appear somewhere in
    the built document; `{%p for %}`/`{%p if %}` control tags must be balanced *and*
    correctly nested (a stack walk, not just a count match, since a miscount-free but
    misnested structure would pass a naive count comparison); under generic mode,
    exactly one outer `{%p for section in sections %}`; and no `w:hyperlink` element
    survives anywhere in the built template — every path that ever touches one
    (`build_contact_profile`, a project header's link) strips it, since the real
    per-item URL is only ever reinstated at render time as a `RichText`.
  - `verify_roundtrip(tagged, profile, resume)`: renders `resume` through `tagged`
    and confirms each mapped field's actual *value* reaches the output — catches a
    tag that is present (passes `verify_tagged`) but wired to the wrong span, which
    builds and renders without error, just with the wrong text. Skips entries with no
    surviving bullets, matching `render.build_context`'s own filtering.
- **Found and fixed while writing this, not before**: `verify_roundtrip` initially
  called `render.render()` directly, which has no way to pass an explicit layout —
  `build_context`'s default `active_layout()` call reads `config.
  TEMPLATE_PROFILE_PATH` from disk, meaning a staged, not-yet-committed profile being
  verified would silently render against whatever profile is *already live* instead
  of itself. Caught immediately by a smoke test against the fixture (a project
  section rendered empty because the developer machine's own live profile happened
  to have `enabled.projects: False`) — the same class of bug Phase 2's
  `_isolated_template_paths` fixture exists to catch in tests, just in production
  code this time. Fixed by adding a `layout: dict | None = None` passthrough
  parameter to `render.render()` (backward compatible — `None` keeps every existing
  caller's behavior unchanged) and having `verify_roundtrip` pass
  `template_profile.active_layout(profile)` explicitly. This also directly enables
  Phase 5's draft-preview endpoint, which has the identical need.
- **Wired into `web/template_ops.py`**: `_verify_staged_build(tagged, profile)` runs
  `verify_tagged` + `verify_roundtrip` (against `data.load()`) right after
  `_smoke_render` inside `_install_with_profile`'s staged build, before the staged
  files ever replace the live baseline/tagged/profile trio. A blocking issue raises
  `TemplateBuildError`, the same exception type (and the same rollback path) a
  smoke-render failure already produces. Profile-only, matching `_smoke_render`'s own
  scope — `_install_legacy` has no `TemplateProfile` for either check to run against.
- **One test exposed a stub that was too fake to be useful**:
  `test_profile_template_install_works_on_a_freshly_created_profile` stubbed
  `_run_build` with a function that wrote a bare "Tagged template" placeholder
  document — sufficient to pass `_smoke_render` (which only opens the file) but not
  the new tag-presence check. Its own docstring already said "Only `_run_build` is
  stubbed here; the smoke render is real" — the fix makes that literally true: the
  stub now calls `template_build.build_from_profile` in-process instead of writing a
  placeholder, skipping only the subprocess spawn, exactly as documented.
- **Exposed on the CLI**: `template_build.build()` gained a `verify: bool = True`
  parameter, run after a successful profile build (skipped for a legacy build, same
  reason as the web path). `scripts/build_template.py --no-verify` opts out.
  Verification failure prints each blocking issue and returns exit code 1; unlike the
  web install this path is not staged/atomic, so the just-written file is not rolled
  back — re-run after fixing the mapping, matching how a build failure already
  behaved here.
- **`tests/document/test_template_verify.py` added** (13 tests): known-good builds (fixed mode
  via the Phase 2 `_full_featured_resume` fixture, generic mode via the pre-existing
  `_multi_section_resume` fixture) verify clean on both checks — regression guard
  against the checks themselves drifting from what tagging emits. Corruption tests
  inject a defect into an already-successfully-built template's XML directly (delete
  the paragraph carrying `{{ job.dates }}`; delete an `{%p endfor %}`; delete the
  generic section loop-open; append a stray `w:hyperlink`; swap
  `{{ job.company }}`'s text for `{{ job.location }}`) rather than trying to first
  reproduce a specific analyzer bug that happens to produce that state — proves each
  check catches something real without depending on Phase 4's not-yet-written
  analyzer fixes.
- **Verified against both real, live templates**, not just synthetic fixtures:
  `python scripts/build_template.py` (default/owner workspace, fixed mode) and
  `python scripts/build_template.py --workspace nina` (generic mode) both rebuild and
  verify clean with the mechanical tag-hoisting in place — confirms the refactor
  changed nothing about what either real template produces.
- **Full suite**: 608 passed, 1 deselected (the Phase 2 `owner`-marked test).
  Frontend (`tsc -b`, `oxlint`, `vitest`) unaffected — no frontend files touched.

## 2026-08-05 - Phase 7 cleanups: retiring the legacy build path and its debts

**What:** The last remediation-plan phase — four cleanups the earlier phases either
required or made safe to finally do.

- **Retired `build_legacy` and everything only it used**, after confirming both real
  workspace templates (`default`, `nina`) analyze `ready: true` with zero blocking
  issues under the current analyzer — the precondition the plan named, verified rather
  than assumed. Removed from `template_build.py`: `build_legacy`, `build_name`,
  `build_contact`, `build_education`, `build_experience`, `build_projects`,
  `build_skills`, the legacy `split_entries`, and three helpers that turned out to be
  legacy-only despite living in the shared-looking part of the file once traced
  (`header_run_count`, `vertical_cost`, `pick_bullet_prototype`, `leading_runs_before_tab`)
  — each confirmed by grep to have no caller outside the functions being removed
  before deletion, not assumed from the plan's own list. **`SECTIONS` and
  `find_sections` were deliberately kept**, contradicting the plan's literal text: the
  plan predates this phase's own discovery that `discover_noto_num_id` (used by *both*
  build modes, to find which bullet numbering instance uses Noto Sans Symbols) depends
  on `find_sections` to locate the EDUCATION section as a heuristic anchor — removing
  it would have broken bullet-marker-font normalization in the still-live profile
  path. `build()`'s profile-absent branch now prints a clear error and returns exit
  code 1 instead of silently calling `build_legacy`; the CLI's `--legacy` flag,
  `template_ops._install_legacy`, `install_baseline`'s `legacy` parameter, and
  `POST /api/template`'s optional-profile fallback are all gone — `profile` is a
  required multipart field now, both at the FastAPI layer (`Form(...)`, not
  `Form(None)`) and in `uploadTemplate`'s TypeScript signature. Frontend:
  `uploadLegacy` removed from `templateState.tsx`, "Legacy install (no mapping)"
  button removed from the wizard.
  - **Real cost, not just a rename**: ~10 `tests/web/test_web.py` tests had quietly come
    to depend on the profile-less upload path as a *convenience shortcut* for testing
    unrelated concerns (library snapshots, backup/restore, the calibrate flag, queue-busy
    rejection) — none of them were actually testing legacy-headings behavior on
    purpose. Fixing them properly (new shared helper `_resume_upload_with_profile()`:
    a real analyzable upload plus its own suggested profile) surfaced a real behavioral
    difference worth documenting: the profile path's staged/atomic design means a build
    failure during staging never touches the live baseline at all (nothing to
    "restore" — the live files were simply never written), which is a *stronger*
    guarantee than the old legacy path's write-then-restore-on-failure, not just a
    different implementation of the same guarantee. One test's docstring/assertions
    were rewritten to say so rather than papering over the difference.
- **`_section_body_paragraphs` now stops on paragraph *identity*, not paragraph
  *text*.** The old code matched a walked paragraph's text against every other
  enabled kind's `heading_text` to find where the current section's body ends — which
  reads a bullet whose own text happens to exactly equal another heading's text (a
  bolded "SKILLS" label inside an experience bullet, say) as *that* heading, silently
  truncating the section early with no error. Fixed by resolving every enabled kind's
  heading paragraph *object* once, up front — before any section's body is touched —
  via `_para_by_id`, and passing the resolved `other_headings: list[Paragraph]` down
  into `build_experience_profile`/`build_education_profile`/`build_projects_profile`/
  `build_skills_profile` and `build_generic`'s own loop, all five call sites. This is
  safe regardless of the bottom-up processing order specifically because heading
  paragraphs themselves are never moved, inserted around, or deleted mid-build — only
  the *space between* headings is — so a reference captured before processing starts
  stays valid throughout, unlike a re-derived index (which an earlier section's own
  insertions could shift) or re-matched text (works, but can't tell a real heading from
  an entry line that happens to say the same thing). Verified the bug was real before
  fixing it: reproduced the old text-matching logic standalone against a synthetic
  fixture and confirmed it silently stopped short exactly as suspected, before writing
  the fix or the regression test. New test:
  `test_entry_bullet_matching_another_headings_text_does_not_truncate_body`.
- **Removed `data.to_legacy_dict`.** Confirmed `GET /api/master-resume` no longer
  calls it (returns `resume.model_dump(by_alias=True)` directly, already
  `sections`-native) — its only remaining callers were two tests constructing a
  legacy-shaped payload to exercise `PUT`'s acceptance of that shape, which is
  `MasterResume._migrate_legacy_sections`'s before-validator's job, not a dedicated
  function's, matching the plan's own reasoning. `test_data.py`'s test of
  `to_legacy_dict` itself was deleted outright (nothing left to test once the function
  is gone); its one non-redundant assertion — a legacy-shaped dict round-trips through
  `model_validate` — was already independently covered by `_RESUME_TEMPLATE`-based
  tests elsewhere in the same file. `test_web.py`'s legacy-payload test was kept and
  rewritten to hand-build the same shape inline.
- **New `tests/test_config_rebinding.py`**: an AST scan asserting no first-party module
  (`src/`, `tailor.py`, `scripts/`) does `from config import <X>` for any name
  `set_active_workspace` reassigns — that import would bind a name at import time,
  permanently decoupled from any later workspace switch, silently leaving that one
  reader on the previous (or default) workspace's path forever. The rebound-name set
  is extracted from `set_active_workspace`'s own `global` statements via AST rather
  than hardcoded, so a rebound global added later is covered automatically instead of
  falling outside a stale list. Verified the detector has teeth (not just checking it
  passes on a clean tree) by running its own extraction-and-match logic against a
  deliberately bad synthetic snippet and confirming it flags it.
- **Docs**: `CLAUDE.md`'s testing-conventions section was still describing the
  pre-Phase-2 state (`data.load()` against a personal `data/master_resume.json`) —
  updated to describe the actual hermetic fixture/`owner`-marker setup, plus a new
  note on the in-process build fallback tests rely on. "Template generation" gained
  three new subsections (analyzer correctness, wizard confirm+preview, DOCX import)
  covering Phases 4-6, and its "Two upload paths" note was corrected to one (legacy
  retired this phase). Added one new "Non-obvious gotchas" entry for the
  identity-vs-text section-boundary bug. `README.md`'s `--legacy` CLI example removed.
- **Verified against both real workspace templates end to end** after every change in
  this phase, not just at the end: `python scripts/build_template.py` (default, fixed
  mode) and `--workspace nina` (generic mode) both still build successfully with the
  legacy path gone and the identity-based boundary fix in place; a full
  analyze → build → `verify_tagged` → `verify_roundtrip` pass came back clean for both.
  Full backend suite: 649 passed, 1 deselected. Frontend: `tsc -b`, `oxlint`,
  `vitest run`, `vite build` all clean.

## Decorative drawings (B15, 2026-09)

- `_document_has_textboxes` used to block on any `w:drawing`: a divider line, an icon, a headshot, a logo. It now blocks only when a `w:txbxContent` (DrawingML or VML text box) holds text. Other drawings produce the non-blocking `decorative_drawing` note.
- The build removed every run but the first when collapsing a paragraph to one tag, which deleted an icon beside the name or contact line. `collapse_runs`/`_drop_run` in `template_build.py` now keep drawing runs (`w:drawing`, `w:pict`, `w:object`) in place, strip only their text, and put the tag in the first text run even when an icon comes first. Covered by `tests/document/test_template_drawings.py` through analyze, build and render.

## Templates without an Experience section (B16, 2026-09)
A first-year student's resume often has Education, Projects and Activities but no
Experience. `TemplateProfile.experience` is now optional and `enabled.experience` can be
False; the validator only requires *some* entry section (experience, projects or a list
section). `missing_experience` blocks only when neither a Projects nor a list heading
exists. With experience disabled, `fit.choose_entries` forces experience-kind sections
to 0 (even over `section_limits`, since nothing could render them), `estimate_lines`
skips them in both section modes, and `render.build_context` leaves the legacy
`experience` key empty. The resume's experience entries stay in the master store; they
just have nowhere to go in this template. The SPA's section-map toggle refuses to turn
off the last entry section.

## Master resume version history (S4, 2026-09)
`resume_versions.py` records every in-app save of `master_resume.json` into the
`resume_versions` table of `app.db` (last 50, deduplicated by SHA-256). Deviation from
the plan: the JSON file stays the source of truth (CLI, `data.load`, hand edits all read
it; making the DB authoritative would fork every reader). A hand edit is caught by
`sync_external()` (file digest ≠ newest version) before each save and on every history
listing, and kept as its own "edited outside the app" version, so a restore never
silently drops it. Restore (`POST /api/master-resume/restore/{v}`) writes through the
normal `_write_master_resume` path (backup + new version), so a restore is undoable.
History failures are logged and never block a save. The timestamped `.bak.json`
siblings are unchanged.

## P3-T: starter templates are generated, not committed (2026-09)
- The plan called for committed `default_templates/<name>/{original_export.docx, main_template.docx, calibration/soffice.json}`. We don't commit them: `.gitignore` and the pre-commit path guard keep every `.docx` out of git, and a committed `main_template.docx` would be a second producer of tagged templates. `default_templates.build(name)` makes the baseline in memory, with fixed zip timestamps and core-property dates so the bytes and hash are reproducible. The install runs the ordinary upload path, so `template_build` stays the only thing that tags.
- There is no shipped calibration. The install calibrates against the student's own resume when "Tune page fit" is on (the default); otherwise the estimates apply until the Page fit card is used. That is the same as for an uploaded template.
- Each design includes Education, Experience, Projects, Leadership (a second experience-kind section), Skills and a bulleted Certifications list. That makes the analyzer choose `generic` mode, so any section the student has renders under its own title in the student's order. A design missing a kind would silently omit that kind's sections (`omit_*`).
- Business capitalises the name with `w:caps` run formatting rather than upper-case text, so the student's own name renders in capitals too.
- Re-installing a design already in the library activates the saved entry (matched by sha256) instead of adding "Classic (2)". A label a student already used for their own template gets a " (2)" suffix.
