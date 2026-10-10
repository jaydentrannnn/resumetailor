# Fit loop & calibration — implementation notes

Covers: PDF measurement (Word/LibreOffice), calibration, underflow/overflow thresholds, SHORTEN_SCHEDULE, bullet shares, widow repair.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-07-26 ? LibreOffice is a viable measurement engine (Phase 0 gate)

**What:** Compared Word-rendered PDFs against LibreOffice-rendered PDFs for all 14
`.docx` files already in `output/`, using `scripts/compare_pdf_backends.py`.

**Result:** Line counts were **identical on all 14** documents. Page counts agreed on
13 of 14. The single disagreement is `_calib_lines_final`, which is by construction the
document sitting exactly on the page boundary (it is the calibration artifact holding the
most lines that still fit one page under Word). Word fits 52 lines there, LibreOffice 51.

**Why it came out this well:** the container uses the *same font files* Word used, not
metric-compatible substitutes. `docker/fonts/` vendors the exact `Lora-VariableFont_wght.ttf`
and `NovaMono-Regular.ttf` from this machine, so glyph advances ? and therefore every wrap
point ? are identical. Wrapping is what `CHARS_PER_LINE` describes, which is why that
constant does not move.

**Impact:** `CHARS_PER_LINE` stays 101 under LibreOffice. A live `scripts/calibrate.py`
run inside the container later measured `LINES_PER_PAGE = 50` (not the 51 inferred from
the one mismatched baseline) ? use the calibrated file, not the spike estimate. The gate
passes: LibreOffice can drive the fit loop in the container.

**Notable:** Spectral (used for section headings) is **not installed on this Windows
machine**, so Word substituted it when producing the baselines. The container installs the
real Spectral. This affects only heading glyphs, never wrapping ? headings are single short
words ? which the identical line counts confirm. Georgia is referenced by an unused
`Subtitle` style and is deliberately not vendored, being proprietary.

## 2026-07-26 ? Calibration constants moved from source into data

**What:** `CHARS_PER_LINE` / `LINES_PER_PAGE` are now loaded from
`data/calibration/<backend>.json`, one file per PDF backend, with the Word-measured values
kept in `config.py` as the fallback.

**Why:** `scripts/calibrate.py` previously regex-rewrote `config.py` itself. That is fine
for a developer script and wrong inside a container, where the source tree may be
read-only and where two engines need two different answers.

**Tradeoff:** one more file to keep in sync, and a fresh container with no calibration file
silently inherits Word's constants. Mitigated by `config.CALIBRATION_SOURCE`, which records
whether real measurements or the fallback are in use so the report and the UI can say so.

**Spec delta:** the plan said `data/calibration/`; kept, since `data/` is already a bind
mount in compose. Note this makes calibration gitignored along with the rest of `data/`.
After first `docker compose run ? python scripts/calibrate.py`, `soffice.json` appears
on the host mount (`CHARS_PER_LINE=101`, `LINES_PER_PAGE=50`).

## 2026-07-26 ? UNDERFLOW_THRESHOLD lowered to 0.86

**What:** `config.UNDERFLOW_THRESHOLD` changed from 0.92 to 0.86.

**Why:** Live runs often started at ~10 bullets (~86% page fill after the first rewrite)
and triggered a grow round because 86% < 92%. Lowering the threshold accepts that fill on
the first measure and skips an extra rewrite pass.

**Tradeoff:** Slightly more whitespace at the bottom of a one-pager; raise back toward
0.92 if tighter packing matters more than API cost.

## 2026-07-27 ? UNDERFLOW_THRESHOLD raised to 0.96

**What:** `config.UNDERFLOW_THRESHOLD` changed from 0.86 to 0.96.

**Why:** Owner wants one-pagers filled at least 96?98%. At 0.86 the fit loop treated a first measure around 86% as done and skipped grow rounds.

**Tradeoff:** More grow/rewrite iterations (and API cost) when the initial selection undershoots; may also hit overflow and shorten if adding bullets tips past one page. Raise toward 0.98 only if 96% still looks sparse; lower if grow/overflow thrashing becomes common.

**Spec delta:** Reverses the 2026-07-26 cost-saving drop to 0.86 in favor of denser packing.

## 2026-07-27 ? Initial selection sizes on rewrite budget

**What:** `fit._initial_selection_size` now estimates each candidate bullet at `_TARGET_LINES_PER_BULLET` (rewrite char budget) via `_select_at_rewrite_budget`, not at master-text length.

**Why:** Master bullets are usually longer than the rewrite target, so sizing on originals started ~10/15 and left the page sparse after the first rewrite shortened them. Owner wanted the first call closer to ~12/15.

**Tradeoff:** First pass can be slightly optimistic ? if the model does not shorten enough, overflow/shorten path fires instead of grow. That is preferred over paying for grow rounds every run.

**Spec delta:** Extends budget-first sizing to assume post-rewrite length for the initial search only; `estimate_lines` for overflow reports and Word-unavailable fallback still uses real text.

## 2026-07-27 ? Initial selection overshoot (+2 lines)

**What:** Added `config.INITIAL_SELECTION_OVERSHOOT = 2` and applied it in `fit._initial_selection_size`. Stub length now matches rewrite hard max (budget minus `WIDOW_SAFETY`).

**Why:** Owner wanted first call at 12/15 or denser. Rewrite-budget sizing alone sat at 12; +2 estimated lines past capacity typically yields 13/15 on this resume.

**Tradeoff:** Slightly more likely to overflow on the first measure and pay a shorten round instead of a grow round. Preferable when the goal is a fuller page.

## 2026-08-02 - `--initial-bullet-share`: a ceiling on the first draft, not a floor

- **What triggered this:** the user reported the fit loop's opening draft almost always
  landing at "14/15 or 16/17" bullets and asked for a way to start sparser, the same way
  `--fill-target` already lets them ask for a sparser *finished* page.
- **Two semantic choices, both confirmed with the user rather than assumed:**
  1. **Ceiling only, never a floor.** The new `share` param to
     `fit._initial_selection_size` only lowers the binary search's upper bound
     (`high = max(floor, min(total, round(total * share)))`); it cannot force the search
     to claim *more* than the line estimate already says fits. At `share=1.0` the search
     is byte-identical to before this change — verified in `test_fit.py`.
  2. **First draft only, not the grow loop.** `total_bullets` (the grow loop's own
     ceiling, `fit.py` underflow branch) is untouched. This was a deliberate rejection of
     the alternative — capping the whole run — because that would have turned "page is
     only X% full" into a permanent state for a low share paired with the default
     `fill_target=0.93`, rather than a starting point the loop is free to grow away from.
  3. **Same discussion also considered making the share *set* the initial count directly**
     (bypassing the binary search, able to force an overflow the shorten schedule then has
     to claw back). Rejected: "ceiling only" was chosen specifically so this knob can never
     by itself cause a `FitError`, matching `fill_target`'s own non-destructive framing.
- **Consequence worth stating loudly, and stated in three places (the `fit.fit` docstring,
  the CLI `--help` text, and the settings-panel help string):** because the grow loop is
  untouched, a low share *alone* is often undone by that same loop at the default fill
  target — it mostly buys extra rewrite rounds for the same final page, not a sparser one.
  It bites when paired with a lower `--fill-target`, or when the shortfall is bigger than
  `MAX_GROW_ATTEMPTS` (4) rounds can recover in. Framed as a UI hint ("but the page fill
  target above may still grow it back, so lower both to end sparser") rather than a
  separate warning banner, since it is a property of the two knobs' interaction, not a
  failure state.
- **Plumbing:** followed the `fill_target` chain exactly — `config.INITIAL_BULLET_SHARE`
  (default `1.0`) → `fit.fit(initial_bullet_share=...)` (resolved locally, same
  `param if param is not None else config.CONST` pattern, never mutating the module
  constant) → `tailor.py --initial-bullet-share` (hand-rolled 0.30–1.00 range check,
  argparse has no range type) → `JobSettings.initial_bullet_share` /
  `ConfigResponse.initial_bullet_share` (`web/schemas.py`) → `web/jobs.py`'s `fit.fit`
  call → `frontend/src/api.ts` types → `DEFAULT_SETTINGS` (`null` = server default) →
  a second range slider in the Run page's Advanced fieldset, right under the fill-target
  one, reusing its integer-percent-to-fraction conversion. No new touch point was needed
  in `WorkspaceSettings`/`SettingsResponse`/`CreateJobRequest` — all three wrap
  `JobSettings` whole, so an old `settings.json` missing the field just falls back to the
  Pydantic default.

## 2026-08-02 - `SHORTEN_SCHEDULE` shifted down: (15, 25, 35) -> (5, 15, 25)

- **What triggered this:** immediately after the initial-bullet-share knob above, the user
  asked to soften the overflow rewrite's first cut from 15% to 5%.
- **Whole schedule shifted, not just the first entry.** Asked directly rather than assumed:
  the alternative was leaving attempts 2/3 at 25/35 and only softening attempt 1, which
  would have widened the jump between attempts 1 and 2 from 10 points to 20. The user chose
  the even shift, preserving the existing 10-point escalation between attempts.
  `fit.py`'s `shorten_pct = config.SHORTEN_SCHEDULE[min(attempt - 1, len(...) - 1)]` needed
  no change — it already reads the tuple positionally.
- **No other file changes needed.** `tests/pipeline/test_fit.py`'s two assertions
  (`test_fit_escalates_shorten_schedule_on_overflow`,
  `test_fit_raises_after_max_attempts_without_truncating`) both read
  `config.SHORTEN_SCHEDULE` rather than hardcoding 15/25/35, so they track the new values
  automatically. `docs/ARCHITECTURE.md` and `docs/PLAN.md` still show the old numbers —
  left alone deliberately: `ARCHITECTURE.md` is already documented stale in `CLAUDE.md`,
  and `PLAN.md` is a curated record of *why* 15/25/35 was chosen originally, not a live
  constants table — rewriting it here would misattribute this change to that history.

## 2026-08-03 - `--experience-bullet-share` / `--max-bullets-per-entry`: bullet allocation was never section-aware

- **What triggered this:** the user reported tailored resumes routinely giving projects
  more bullets than experience and asked for a weighting knob between the two, plus
  separately floated a per-entry bullet cap as another way to get the same control. Asked
  to evaluate the pipeline first rather than just bolt something on.
- **Root cause, found by tracing the selection code rather than assumed:** entry
  *selection* was already section-separated — `fit.choose_entries` calls
  `rewrite.select_entries` once for experience and once for projects, each against its own
  `MAX_*_ENTRIES` cap, specifically so a stack of projects can't evict a job. But
  `choose_entries` then returns `[*experience, *projects]`, and bullet *allocation* inside
  those chosen entries was never section-aware: `select_within_entries` gives every entry
  a floor of one bullet, then pools **every remaining bullet from every entry** into one
  flat ranked competition for the shared discretionary budget. `Bullet` carries no
  back-pointer to its parent entry, so that function could not have told an experience
  bullet from a project bullet even if it wanted to. Project bullets are typically
  keyword-dense (tech tags matching JD must-haves), so they systematically won the flat
  pool at experience's expense — not a tuning artifact, a structural gap.
- **Both knobs shipped, confirmed via a direct question rather than picking one:** an
  overall `EXPERIENCE_BULLET_SHARE` (fraction of experience vs. projects) and a
  `MAX_BULLETS_PER_ENTRY` ceiling, both `None` by default so an unconfigured run stays
  byte-identical to before — the same convention `INITIAL_BULLET_SHARE = 1.0` and
  `SEMANTIC_WEIGHT = 0.0` already set.
- **The share is of the *overall* limit, not just the remainder past floors** — chosen as
  the more intuitive read of "70% experience" a user would actually ask for, over a
  reading scoped to only the leftover discretionary budget.
- **Section discrimination is `isinstance(e, Project)`** in `rewrite.py` — safe because
  `Experience` and `Project` are independent subclasses of `_Strict` (`data.py`) with no
  inheritance between them, so no flat-list caller needed to change shape.
- **A capped entry's forfeited slot is not lost.** `rewrite._take_ranked`'s single ranked
  walk just skips a saturated entry and keeps going to the next-best bullet elsewhere, so
  spillover falls out of the existing loop rather than needing separate handling.
- **Two correctness bugs caught during implementation, not anticipated in the initial
  design:**
  1. `rewrite._section_budgets` originally sized each section's cap from its *raw* bullet
     count. Once `max_bullets_per_entry` is also set, a section can be achievably smaller
     than its raw pool, so budgeting against the raw count could hand a section more than
     `_take_ranked` can actually fill — silently under-selecting instead of spilling the
     surplus to the other section. Fixed by sizing both caps via
     `rewrite.selectable_total(section, max_per_entry=...)` instead of `sum(len(...))`,
     so the existing two-pass spillover logic operates on achievable capacity.
  2. The fit loop's grow condition compared `limit < total_bullets` (the raw pool size).
     With a per-entry cap, the achievable selection saturates below that, so unpatched the
     loop would keep raising `limit` while the selection stayed unchanged, burning up to
     `MAX_GROW_ATTEMPTS` (4) full rewrite-call-plus-render rounds for zero effect. Fixed by
     adding `rewrite.selectable_total(entries, max_per_entry=...)` and using that
     `growth_ceiling` — not `total_bullets` — in both the `can_grow` check and the
     deficit-based `limit` update. `FitResult.bullets_total` keeps reporting the raw pool
     size unchanged; it is a display value, not a loop-control one.
- **Plumbing followed the `--initial-bullet-share` / `--fill-target` chain exactly:**
  `config.py` constants (both `None`) → `fit.fit()` new kwargs, resolved locally via
  `param if param is not None else config.CONST` (never mutating the module constant) →
  `tailor.py` CLI flags with hand-rolled range checks (argparse has no range type) →
  `JobSettings` + `ConfigResponse` (`web/schemas.py`) → `web/app.py`'s
  `_config_response()` → `web/jobs.py`'s `fit.fit()` call → `frontend/src/api.ts` types →
  `DEFAULT_SETTINGS` (`null` = server default) → `RunPage.tsx`'s Advanced fieldset: a
  toggle that sets the share to `0.65` on / `null` off plus a reveal-on-toggle percentage
  slider, and a plain `<select>` for the per-entry cap (No limit / 2-6). No touch point
  needed in `WorkspaceSettings`/`SettingsResponse` — both wrap `JobSettings` whole.
- **Impact / tests added:** `tests/pipeline/test_rewrite.py` gained an explicit equivalence test
  pinning that `experience_share=None, max_per_entry=None` reproduces the original
  floors+select algorithm bullet-for-bullet (not just matching size), plus tests for
  section-share reallocation, floor preservation at the `0.0`/`1.0` extremes, per-entry
  capping with spillover, cross-section spillover when one side can't fill its budget, and
  `selectable_total` itself. `tests/pipeline/test_fit.py` gained a regression test proving growth
  stops at `growth_ceiling` (`iterations == 1`) instead of burning `MAX_GROW_ATTEMPTS` when
  a per-entry cap saturates the selection immediately — this is the bug fix in (2) above,
  pinned so it can't regress silently. `tests/cli/test_tailor_cli.py`'s two `capture()` stubs
  that spell out `fit()`'s full keyword signature needed both new kwargs added (else a
  `TypeError`), plus two new flag-plumbing tests mirroring
  `test_fill_target_flag_reaches_the_fit_loop`. `tests/web/test_web.py`'s `fake_fit` stub and
  `seen_fit` assertion gained both keys, plus a settings round-trip test. Full suite after
  this change: the same 16 pre-existing failures as a clean `main` checkout, verified
  byte-identical by diffing the failing-test list before/after — none of them are
  connected to this work. Frontend `npm run lint` (no new warnings), `npm run test`
  (10/10), and `npm run build` all clean.

## 2026-08-04 - Calibration was silently poisoning every run; hardened against a repeat

- **Found live, not hypothesized:** `data/calibration/word.json` and
  `data/workspaces/default/calibration/word.json` both held `chars_per_line: 20` —
  exactly `calibrate.py`'s binary-search floor, written to disk as if it were a
  measurement. Effect, confirmed before touching anything:
  `rewrite._length_band(2 * 20) == (20, 40)`, so the rewrite prompt was asking for
  20-40 character bullets. A third file with the identical signature
  (`data/calibration/soffice.json`, `chars_per_line: 20`) turned up once the workspace-
  scoped ones were fixed and re-measured — all three dated 2026-08-02, all deleted.
- **Root-caused, not just patched:** `calibrate_chars_per_line`'s wrapped-line filter
  hardcoded `line.strip() not in ("PROJECTS", "SKILLS")` to exclude the static section
  headings that render unconditionally on the calibration probe page even with zero
  entries (`_single_bullet_resume` empties Projects/Skills to isolate one bullet's own
  wrap behavior). A **fixed-mode profile install preserves the uploaded heading text
  verbatim** — it does not force it to literally read "PROJECTS"/"SKILLS" the way the
  legacy path does — so a resume whose heading said e.g. "Selected Projects" made that
  heading survive every filter attempt. The trailing heading line then made
  `len(wrapped_lines) == 1` false for *every* candidate length, and the search walked
  every step the same direction, converging on its own floor. Fixed by deriving the
  stop-title set from the *active template profile* (`calibrate._static_heading_texts`)
  instead of a hardcoded pair: reads `profile.projects.heading_text`/
  `profile.skills.heading_text` under `section_mode="fixed"`, returns the legacy
  4-literal set with no profile installed, and returns an empty set under
  `section_mode="generic"` — a zero-entry section renders no heading there at all
  (`render.build_context`'s `if not rendered_entries: continue`), so nothing needs
  excluding in the first place. Confirmed nina's workspace (`section_mode="generic"`,
  Skills heading literally "SKILLS & Interests") never had a `word.json` at all before
  this — consistent with the same class of bug, just never previously calibrated on
  Word to surface it.
- **Defense in depth, since the historical root cause of one specific file couldn't be
  pinned with certainty** (the corrupted files predate this session's changes by two
  days, likely measured against an earlier template/profile state): both binary
  searches (`calibrate_chars_per_line`, the bullet-count half of
  `calibrate_lines_per_page`) now raise `CalibrationError` if their result sits exactly
  on a search bound (`_check_not_collapsed`) — a converged search and a collapsed one
  are otherwise indistinguishable from the return value alone. Both final metrics are
  also checked against an absolute plausibility band, `config.PLAUSIBLE_CHARS_PER_LINE
  = (40, 200)` / `PLAUSIBLE_LINES_PER_PAGE = (25, 90)` — catches a collapse that lands
  one step off a bound rather than on it. A new resume-independent self-check,
  `verify_chars_per_line_boundary` (a `chars_per_line`-length bullet must render as one
  line; `chars_per_line + 15` must wrap to two) runs unconditionally in `run()` and
  hard-fails — unlike `verify_known_anchors`, which stays a soft warning because it's
  owner-specific (hardcoded bullet ids, page counts for one person's resume, so a
  mismatch might just mean the resume changed, not that calibration is wrong).
  `write_calibration` is only ever reached after all of the above pass, so a bad
  measurement is now structurally prevented from reaching disk, not just less likely.
- **Second line of defense on load, for a bad file that reaches disk anyway**
  (hand-edited, copied from another template, or written before this guard existed):
  `config._load_calibration` now rejects out-of-band values and falls back to the
  built-in constants rather than trusting them, same as a missing file. `source` stays
  exactly `"fallback"` in both cases (every existing `== "fallback"` check, backend and
  frontend, already means "not using a real measurement" and must not change shape); a
  new `config.CALIBRATION_REJECTION: str | None` carries the *why*, threaded through
  `RunReport`/`ReportOut`/`ConfigResponse` and surfaced as a warning banner on the
  RunPage (both the pre-run config strip and the per-job report footer) and in the
  Template tab's calibration status. Also added: when no calibration file exists for
  the active backend but one exists for the *other* backend, the message says so
  explicitly (constants are not portable between Word and LibreOffice — silently
  reusing one for the other was another way this class of bug could hide).
- **Regenerated for real**, not just fixed in code: `scripts/calibrate.py` against the
  active (default/owner) workspace via Word COM landed `chars_per_line=101,
  lines_per_page=55` — matching that workspace's existing LibreOffice measurement
  (101/55) exactly. `--workspace nina` landed `121/58` against her `soffice.json`'s
  `122/58` — a 1-char difference consistent with normal Word/LibreOffice glyph-metric
  variance, not a fluke. Both self-consistency checks passed; both runs'
  `verify_known_anchors` warned (expected — it checks Jayden-specific bullet ids and a
  39-bullet/3-page anchor against resumes that have since changed shape, nina's
  obviously so; this is the pre-existing soft-warning behavior, not a regression).
- **`tests/document/test_calibrate.py` added** (23 tests, no Word/LibreOffice): pins the
  collapsed-search guard, the plausibility band, `_static_heading_texts`'s three modes,
  and reproduces the custom-heading-text bug end to end against a stubbed renderer —
  proving both that the old (removed) hardcoded filter would have collapsed on it and
  that the fix converges correctly. Also pins that `run()` never calls
  `write_calibration` when the boundary check raises.

## 2026-08-07 - Calibration's anchor check hardcoded one person's resume; replaced with a per-workspace recorded baseline

- **What:** Calibrating the `nina` workspace in Docker printed
  `warning: anchor check failed (full master resume (39 bullets) rendered to 2 page(s),
  expected 3)`. Not a rendering bug: `nina`'s master resume has 25 bullets, not 39;
  "39 bullets" and "expected 3" were string/int literals in `calibrate.py` describing
  the owner's own `default` workspace (57 bullets today — even that number was already
  stale), and the 13-bullet subset check keyed on hardcoded ids (`aol_b1`, `vnpt_b1`,
  …) that exist in exactly one resume. `verify_known_anchors()` loaded whichever
  resume the *active* workspace's rebound `config.MASTER_RESUME_PATH` pointed at and
  compared it to those fixed numbers — it could never pass for any workspace but the
  one it was written against. The module's own docstring already called this out as
  "owner-specific"; it just had no alternative until now. Calibration itself was fine:
  `CHARS_PER_LINE=110`/`LINES_PER_PAGE=52` were both in-band and the resume-independent
  boundary check passed — 25 bullets landing on 2 pages is simply correct.
- **Why:** The anchor step's actual value is catching "the constants came out
  plausible but the render changed underneath" — a real regression signal, just aimed
  at the wrong target (one fixed resume) instead of the right one (whatever resume
  this workspace actually has).
- **Impact:** `calibrate.measure_anchors(resume)` renders the full resume and a
  scale-free half-size subset (`resume.all_bullets()[: len // 2]`, not fixed ids) and
  returns page counts plus two fingerprints — `resume_sha256` (content hash of the
  whole resume) and `template_sha256` (content hash of the tagged template, since
  `write_calibration`'s existing `template` field is only a filename and can't tell a
  *rebuilt* template from the one a baseline was measured against). `check_render_
  anchors(measured, previous, rebaseline)` is a pure decision function (no rendering,
  unit-tested without a renderer) over that block and whatever was last recorded in
  the calibration file's new `anchors` key: no previous baseline, or either
  fingerprint changed → adopt `measured` silently (an ordinary resume edit or
  template rebuild is not drift); fingerprints match and counts match → `anchor checks
  OK`; fingerprints match but a count differs → real drift, a warning, and the *old*
  baseline is kept on disk rather than silently overwritten. `scripts/calibrate.py
  --rebaseline` is the deliberate acknowledgement that adopts the new measurement
  anyway. `write_calibration`'s new `anchors` param is optional and additive — a file
  written without it (or read by old code) is byte-identical to before this change,
  confirmed with a direct test that `config._load_calibration` (which only ever reads
  `chars_per_line`/`lines_per_page`) is unaffected by the new key. `run()` now also
  preserves whatever baseline was already on disk when the anchor step is skipped
  (`verify_anchors=False`) or itself fails to render — it never had a reason to erase
  a recorded baseline on its own, and previously it silently would have (writing no
  anchors block at all). Verified directly against the real file from the bug report:
  `data/workspaces/nina/calibration/soffice.json` has no `anchors` key yet, so
  `_load_previous_anchors` returns `None` and the next real run lands on "baseline
  recorded", never the old hardcoded warning. Backend suite: 689 passed (was 671), 1
  deselected — 18 new tests in `tests/document/test_calibrate.py`, all against
  `check_render_anchors`/`measure_anchors`/`write_calibration`/`_load_previous_anchors`
  directly, no Word/LibreOffice required.

## 2026-09-01 — Widow repair: discard fabricating shortenings instead of aborting

- **Decision:** `_polish`'s widow branch records a fabricating shorten candidate in
  `RewriteOutcome.widow_repairs_rejected` and keeps the pre-polish text; `fit.fit` emits a
  `FitResult.warnings` entry naming the bullet id and offending terms. The fabrication guard
  is unchanged — `9,000+` against "at least 9,000" still fails, same class as `1,000+` vs
  "over 1,000" in `docs/PLAN.md`.
- **Why:** The pass already discarded the bad candidate (`continue`) while holding clean text;
  raising `FabricationError` afterward killed otherwise-good runs (live trigger: `t2s_b1`).
  Verb swaps and merge already discard on guard failure; widow repair was the lone outlier.
- **Impact:** Supersedes `docs/PLAN.md` Phase 12 note that "widow fabrication remains a hard
  failure" — PLAN.md stays append-only; this entry is the current behavior. `--no-widow-repair`
  remains a CLI/API control but is no longer required to unblock a run over this case.

## LibreOffice profile per process (B4/B5/PF1, 2026-09)

- `_convert_soffice` created `/tmp/lo_<uuid>` on every call and never removed it; 20 conversions left 20 profiles. It now reuses one profile per process (`rt_lo_<pid>_<rand>` under the system temp dir), serialised by `_SOFFICE_LOCK` and removed at exit. Profiles over a day old from crashed processes are pruned on first use.
- Per process, not shared across processes: a second `soffice` on a profile already in use passes its job to the first instance's pipe, which fails intermittently (the calibrate script alongside the server, for example).
- A call that produces no PDF is retried once on a fresh profile, which covers a stale `.lock` or a corrupt profile. A stale `<stem>.pdf` is deleted first so it cannot pass for success.
- `RESUME_TAILOR_SOFFICE_PARALLEL=1` restores throwaway per-call profiles with no lock, now cleaned up.
- B5: the profile URI comes from `Path.as_uri()`. `file://` plus a posix path gave `file://C:/...` on Windows.
- PF1 result (Ubuntu, LibreOffice 24.2, small docx): about 1.25 s to 1.1 s per conversion, about 10%, short of the 40% target. Process start-up dominates, not profile creation, so the bigger win is PF2 (a long-lived `unoserver`).

## 2026-09-30 - overflow ladder replaces the blanket shorten (supersedes `SHORTEN_SCHEDULE`)

- **What:** an overflowing draft is relieved on the *same* bullet set by a ladder, stopping at the first rung that fits: (1) combine via `rewrite.merge_into` (merge now on by default; still only after a measured overflow), (2) `rewrite.pull_back` — one call over only multi-line bullets whose last line is <= `PULLBACK_MAX_FILL` (0.40) full, count = overflow lines + 1, emptiest first, accepted only if shorter *and* one line fewer, (3) `fit._choose_drops` — deterministic, weakest relevance first, never an entry's last bullet, <= `MAX_DROP_ROUNDS` (3). `SHORTEN_SCHEDULE`, `MAX_FIT_ATTEMPTS` and `shorten_pct` are gone.
- **Why:** 24 of 220 live runs failed to fit, every one by 1-3 lines (Skills tail on page 2). Re-rewriting every bullet 5/15/25% shorter only freed a line when a bullet crossed a wrap boundary. 16 of 24 errors also quoted a negative "over by" because the char-budget estimate undercounts this template by 6-9 lines; `_overflow_report` now quotes measured lines.
- **Also:** the last draft that fit is kept (`_Draft`); if a fuller draft cannot be trimmed, it is returned with a warning instead of `FitError`. `grow_cap` stops the grow step re-adding what the ladder removed. `FitResult.dropped` / `.pulled_back` are reported.
- **Not verified live:** no end-to-end run (no model available in the session: Anthropic credit exhausted, Ollama down). Saved Tailor settings that stored `merge: false` still override the new default.

### 2026-09-30 ? Measured final-line repair
Widow decisions now use render.line_layout word boxes from the PDF already produced by measure_detail. The matcher omits uncertain paragraphs, strips bullet glyphs and ligatures, and reports physical line count and final-line width. Measured multi-line bullets under 50% receive one bounded shorten or source-backed extension window; estimate-only bullets retain the conservative 30% threshold. The fit pass re-renders once and restores the prior draft if it overflows. Coursework uses the rendered Relevant Coursework prefix, fills from the original education pool toward 80%, skips oversized courses, and trims a stranded short line if the pool cannot fill it.

### 2026-09-30 — Final measured pass verification
The paragraph matcher requires exact normalised text across consecutive lines and locates the text margin from the page's rightmost word edge. Coursework carries the measured final fill and line count into its deterministic pool-fill calculation, rather than replacing them with a character remainder. The six newest read-only PDFs contained 93 matched wrapped bullet/coursework paragraphs: 19 final lines below 50%, and 16 above 80%; none of the latter are widow candidates.

### 2026-09-30 — Top-up after trimming, measured pull-back, recency
Three v0.2.12 runs ended 79–83% full (7–9 empty lines) where v0.2.11 had reached 91–95%. The 15-bullet first draft overflowed; pull-back was refused by the guard (`rebound:130 students` — the source binds 130 to the single token `students/week`) and picked targets from the character estimate; the drop rung then cut 2–3 whole bullets for a 1–3 line overflow, the measured widow pass shortened 4–6 more, and `grow_cap` plus the 3-jobs/2-projects/3-bullets ceiling meant nothing refilled the page. Fixes: source-side slash compounds bind their parts (a rewrite's own compound still matches whole, so `students/semester` is still flagged); pull-back judges measured near-widows on the overflowing PDF and accepts a cut by its measured ceiling; and a top-up ladder runs where the loop gives up underfull — A re-adds cap-allowed bullets, B tries one bullet past the cap and keeps it only if that reaches the target, C adds the best unchosen entry with the fewest bullets that reach it (B's bullet is restored if no entry fits). Only added bullets are rewritten (`rewrite_bullets(verb_context=...)` re-voices them against the page's openers). Entries also get a mild recency multiplier (≤ +20%, 24-month half-life) at every code-side ranking site.

### 2026-10-01 — Widow repair asks less of the model
Two live gemma4 runs (Motorola R67731, AmerisourceBergen R2614039) still showed 4 measured widows. Causes: (1) `top_up` skipped the added bullets' widow pass whenever the ladder reached the fill target — the normal case — so a re-added bullet (`vnpt_b3`, 43%) was never checked and `widows_remaining` undercounted it; (2) the model missed narrow character windows (EXTEND aimed at 80% fill, ~15 chars wide) and `_polish` silently discarded the miss; (3) one guard rejection (by design). Fixes, at most one extra LLM call per run (only when an added bullet is a widow): top-up always runs `widow_pass(only=added)`; EXTEND aims at `WIDOW_EXTEND_FILL` = 0.55 (window ~2-3x wider); an EXTEND draft that instead saves the whole last line is accepted (`_line_saving_ceilings`); and the fit prompt asks for three versions per bullet under the same id, code keeping the longest clean in-window one (`_TARGET_VARIANTS`, `_REPAIR_PROMPT_VERSION` 3). Rejected: switching models (no LLM hits exact character counts) and a feedback retry (more calls than variants). Not verified live — needs a desktop rebuild.

### 2026-10-04 — Two-line bullet cap; the newest job keeps its lead bullet
An audit of 235 desktop runs found 9% of bullets at 3+ lines (102 at 4+), even though the rewrite prompt advertises a 2-line `max`. Roughly half were verbatim master text: guard fallbacks, unchanged replies, and top-up re-adds, chiefly `aeth_b1` (91 runs) and `aol_b1` (55 runs). The rest were rewrites that ignored `max`. Nothing in code enforced the cap, because the widow pass only looks at a near-empty final line. Fixes: `fit_lines._overlong_targets` adds a SHORTEN window at `_TARGET_LINES_PER_BULLET` lines to the measured widow pass. It runs even with `repair_widows=False`, and its numbers are checked against the bullet's current text (`_polish(number_floor=...)`), so an earlier compression is not held to every master figure; the guard still runs against the master. `_choose_pullbacks` ranks over-long bullets first and takes all of them, so an overflow shortens them before the drop rung removes whole bullets. Whatever remains is one warning line, not a per-bullet list (`_REPAIR_PROMPT_VERSION` 5). Separately, `_choose_drops` spares the first on-page bullet of the most recent experience (`_lead_bullet`) unless nothing else is droppable: the Revvity run dropped the user's headline `aol_b1` as low-relevance, and top-up re-added it verbatim at 3 lines. Not verified live; needs a desktop rebuild.

### 2026-10-04 — one-line fill tolerance and remembered overflow point

Live runs (Ollama cloud) made 15–18 calls in ~2–2.7 min, and every one ended the same
way: the first draft met the 93% target (54/58 lines), widow repair cut a line (53,
91%), then the top-up ladder spent ~4 calls and 4 Word renders — `topup-B` overflowed at
56 lines → revert → `topup-C` overflowed at 57 → revert — to close that one line.
Two code-only changes:
- `config.FILL_TOLERANCE_LINES = 1`: `_FitState._short_of_target()` (used by the grow
  check, `_finish` and `top_up`) treats a page within one line of
  `ceil(fill_target × capacity)` as full. A top-up that does run still aims at the
  full target (`_shortfall`'s goal), and its rungs stop once within tolerance; one
  rewrite costs the same for one bullet or two. `resume_quality.ResumeQuality` carries
  the same tolerance (`fill_tolerance`, as a page fraction) so Apply's quality gate
  and the SPA don't flag a page the loop accepted.
- `_FitState.overflow_lines`: the fewest measured lines any real (non-estimated)
  draw overflowed at. Calibrated capacity was 58 but the page broke at 56;
  `_shortfall`'s room is now capped one line under that, so after rung B overflows,
  rung C no longer rewrites and renders an entry that needs even more lines. Rung B
  refreshes `p.room` after a failed add for the same reason.

- **Section balance replaces "Weight bullets toward experience" in the web UI (2026-10).**
  One bar with a segment per included experience/project section; a divider trades share
  only between its two neighbours (5% steps, 5% minimum). Stored as relative weights keyed
  by section id (`section_weights`), not sum-to-100 percentages, so unticking a section
  rescales the rest and re-ticking restores it, and a deleted section's id is just ignored.
  Off (null) stays the default: one flat pool where the most relevant bullets win. A saved
  legacy `experience_bullet_share` displays as its split and is replaced on the first edit
  (only the frontend has section kinds at hand, so there is no backend migration). The CLI
  keeps `--experience-bullet-share`.
