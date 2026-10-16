# Pipeline stages & guards — implementation notes

Covers: rewrite prompts, fabrication/rebound-number guards, merge, polish, facets, skills stage, expansion, vocabulary packs, writing style, career-ops bands.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-07-26 ? Bullet merging feature (opt-in)

**What:** Implemented an optional `--merge` pass that merges redundant bullet points within the same entry. The fit loop calls `merge.propose` (pure heuristic), and `rewrite` applies accepted merges via `rewrite._merge_bullets`.

**Why:** This is a non-truncation space lever: merged output is accepted only if it is non-regressive in line-span, passes a multi-source fabrication guard, preserves every number-bearing token, and does not create a new widow (widow repair remains a later step).

**Impact:** Accepted merges delete absorbed bullet ids from the `bullets: dict[id -> text]` currency so the existing renderer automatically places the merged line where the survivor bullet appears in the master resume.

## 2026-07-27 ? Reduce repetition (merge gating + verb polish)

**What:** Merges now propose only after a measured overflow (`attempt >= 1`). Merge candidates that restate significant tokens or stack same-family verbs are rejected via `redundancy_offenders`. Opening-verb collisions are detected with `VERB_FAMILIES` / `verb_collisions` and repaired in the shared `_polish` follow-up (formerly `_tighten_widows`). Web UI exposes "Merge redundant bullets" and "Skip verb variety repair"; CLI adds `--no-verb-repair`. Master resume openers diversified away from 4? Designed / 2? Built / 2? Reduced.

**Why:** Eager merges picked the most similar adjacent pair and produced repetitive lines; the rewrite prompt only asked for "strong-verb-first" with no variety rule; the source data itself collided.

**Tradeoff:** A run with verb collisions but no widows costs one extra call (still within the five-call cap). Verb-swap fabrication discards the candidate instead of failing the run ? cosmetic polish must not abort a valid draft. Score caches invalidate after master-resume text edits.

**Spec delta:** Extends Phase 11 merge behavior and Phase 10 widow repair into a combined polish pass; overflow gating was not in the original merge ask.

## 2026-07-27 ? Stop forcing soft-skill keywords into bullets

**What:** Four edits in `src/resume_tailor/pipeline/rewrite.py`. (1) `_SYSTEM`'s mirroring rule now narrows to "only where the posting names something the bullet already does" and states that an unclaimable keyword is meant to go unused. (2) Two new `_SYSTEM` rules: soft skills are demonstrated, never named (with the two live offenders quoted as counter-examples), and bullets must read as plain description rather than assembled vocabulary. (3) `_format_keywords` labels `kind == "soft"` keywords `[soft ? demonstrate, never name]` instead of `[REQUIRED]`. (4) The shorten instruction and `_REPAIR_INSTRUCTION` now preserve "required *technical* keywords" rather than all REQUIRED keywords.

**Why:** A Mistral posting produced "Applied problem-solving skills to a 45% accuracy bottleneck", "Utilized verbal communication skills to facilitate three weekly labs", "Demonstrated attention to detail by...", and "Exercised organizational skills to mentor...". Not a model defect: `_SYSTEM` opened by asking for mirrored JD language, and `_format_keywords` handed the model soft-skill phrases marked `REQUIRED` with no `kind` distinction ? `Keyword.kind` existed but was consumed only by ranking (`_keyword_weight` / `SOFT_SKILL_WEIGHT`), never by the rewrite prompt. The fabrication guard passed these correctly; the phrases trace to the bullets' own tags, so this was never a fabrication failure.

**Tradeoff:** Literal soft-skill keyword coverage drops, which may matter for naive ATS substring matching ? the judgement is that a hiring reader discounts asserted soft skills more than a keyword scanner rewards them. Soft skills still carry their `SOFT_SKILL_WEIGHT` in ranking, so they keep influencing *which* bullets are selected; only the verbatim phrasing is withheld.

**Impact:** No cache-version bump needed ? rewrite output is not cached, and `jd._PROMPT_VERSION` / `rewrite._SCORE_PROMPT_VERSION` are untouched, so existing `output/*.requirements.json` and `*.scores.json` stay valid and the change takes effect on the next run. Full suite passes (187); no test asserted on the old prompt strings.

**Follow-up:** Effectiveness depends on `jd.extract` classifying these as `kind="soft"`. `kind` defaults to `"technical"`, so any soft skill it mislabels bypasses edit (3) and relies on the `_SYSTEM` rule alone. Worth checking `output/*.requirements.json` for "problem-solving skills" and "attention to detail" on the next run.

## 2026-07-27 ? Application-form experience expansion

**What:** Added a fourth LLM stage (`expand`) that produces expanded work-experience descriptions for online application paste fields. New module `expand.py`; hard facts (title, company, dates, location) are copied from `MasterResume` in code ? the model returns bullets only. Fabrication failures drop the bullet with a warning instead of raising. Web UI shows an `ExperienceCard` tile; CLI writes `<out>.expansion.md`.

**Why:** Application forms have a separate experience section that is not page-constrained like the one-pager. Expanding beyond resume bullets there is useful, but inventing tools/metrics is still unacceptable.

**Tradeoff:** Multi-source vocabulary (all bullets in an entry) lets the model attach a tool from bullet A to a claim in bullet B ? same relaxation `_merge_bullets` already accepts. Expansion is non-fatal so a dead backend cannot fail a successful `.docx` run. `hybrid` routes expand to Ollama (guard-protected, advisory); use `--expand-model` to override.

**Spec delta:** New purpose in `config.PURPOSES`; clean run is now four calls. Profile still followed (user chose not to hard-wire expand to Ollama under `claude`).

**Follow-up:** Live quality check under `--model ollama` / `hybrid` against a real posting; rebuild frontend (`npm run build`) or run Vite dev for the new tile in Docker.

## 2026-08-01 ? Rewrite prompt: no cross-bullet metric moves

- **Decision:** Added an absolute rule to `rewrite._SYSTEM`: never move a number/metric
  from one bullet id to another (with an eval-suite example).
- **Why:** Live runs kept pasting `zot_b3` metrics (0.88, p95, 5.13s, ?25%) onto
  `aeth_b3` when both eval harness bullets were rewritten in one batch; the fabrication
  guard correctly hard-failed, but the model needed an explicit id-scoped rule.
- **Tradeoff:** Prompt-only; models can still slip. Merge still uses the same `_SYSTEM`
  plus `_MERGE_INSTRUCTION` (numbers from any *member* are intentional). No rewrite
  prompt-version cache to bump ? rewrites are not cached like JD/scores.
- **Follow-up:** If it keeps firing, soft-fail to source text or differentiate the two
  master bullets further.

## 2026-08-01 ? Fabrication retry of failing ids only

- **Decision:** On a first-draft fabrication, `_retry_fabrications` re-asks only the
  offending bullet ids once, naming the exact rejected terms and re-shipping the master
  source text. A second fabrication or a dropped id still raises `FabricationError`.
- **Why:** Recurring live failures (`130+` vs `over 130`, invented `OS`, cross-bullet
  metrics) are often fixable when the model is told which tokens failed; aborting the
  whole run was blocking bulk apply for a local slip.
- **Tradeoff:** At most one extra rewrite call per `rewrite_bullets` invocation (and
  thus up to `MAX_FIT_ATTEMPTS` extras across a fit loop that keeps fabricating). Guard
  is not relaxed ? only the call budget changed. Widow-repair fabrication remains
  immediately fatal.
- **Follow-up:** Soft-fail to source text if the retry keeps firing in practice.

## 2026-08-02 ? Stored tag vocabulary + chip editors

- **Decision:** `MasterResume.tag_vocabulary` is the shared tag option list (seeded from
  the 102 in-use tags). Editor uses `ChipListField` tiles for tags, skills, coursework,
  and project tech. Removing a vocab option confirms and strips it from every bullet.
- **Why:** Comma-parsed strings made add/remove awkward; a derived-only vocab could not
  express "remove an unused option."
- **Tradeoff:** Vocabulary can drift from tags in use if the user adds options they
  never assign; canonicalisation on save keeps aliases consistent.

## 2026-08-01 ? JD-driven tech tags and coursework (facets)

- **Decision:** New cached LLM stage `facets.select_facets` (purpose `facets`, effort
  `low`, hybrid ? Ollama). Model picks project tech (?4, best-first, optional JD-anchored
  renames) and coursework titles (original names only). Pure code then enforces a one-line
  project-header budget and a two-line coursework budget. `--no-facets` / `no_facets` still
  run budget-only truncation over pools in listed order.
- **Why:** User wanted posting-aware tech and coursework without inventing content.
  Widening `Project.tech` / `Education.coursework` in place (no schema change) ? those
  fields are display-only and do not feed ranking.
- **Rename guard:** Accept only when the new label is JD-anchored *and* equivalent via
  `canonical_tag`, acronym expansion, alphanumeric *prefix* containment, or token-set
  containment. Prefix (not substring) so `Postgres?PostgreSQL` passes and `SQL?MySQL`
  fails. Rejected renames keep the original label and warn.
- **Tradeoff:** Header one-line guarantee uses `CHARS_PER_LINE` calibrated on bullet body
  text plus `PROJECT_HEADER_GAP=4`; bold name + tab stop mean it is an approximation.
  Tune the gap if a header still wraps after rendering.
- **Spec delta:** CLAUDE.md "four calls" / "education never tailored" claims updated;
  architecture diagram includes facets before the fit loop.
- **Follow-up:** Widen tech/coursework pools in `master_resume.json` for live usefulness;
  optionally re-calibrate `PROJECT_HEADER_GAP` after a full-master render.

## 2026-08-02 - Keyword-coverage instability, a live rename-guard fabrication hole, and
"why did this miss" diagnosis

- **What triggered this:** a user reported must-have coverage dropping from 5/10 to 3/10
  on a real posting (Two Sigma "Research Intern") right after they *improved* the master
  resume — added 35 real bullet tags (`aws`, `bedrock`, `distributed training`, `vllm`,
  `trl`, `accelerate`, …), removed exactly one (`deeplearn`, a typo). A resume getting
  richer while its score drops was the anomaly worth chasing.
- **Measured: most of the "drop" was extraction noise, not a data regression.** Scoring
  all 8 cached extractions of that one JD against the *current* resume: coverage ranged
  **3/10 to 6/11** — same posting, same resume, same backend, `temperature: 0` already the
  default (`llm.py:350`). The denominator itself was unstable (10/11/13 must-haves across
  runs) and "multi-machine setups" canonicalised to `distributed computing`, `multi
  machine`, and `distributed systems` across three different runs — never once to
  `distributed training`, a tag the resume genuinely has. One run invented `financial data
  modeling` outright. Only 5 keywords missed in *every* run: `tensorflow`, `pytorch`,
  `deep learning`, `statistics`, `cloud computing` — that was the real, stable gap.
- **Root cause of the one genuine regression:** `t2s_b3`'s old text read "the DeepLearn
  accelerator" — a garbled reference to Hugging Face **Accelerate** — and was tagged
  `deeplearn`. The JD's "Deep Learning" happened to canonicalise to that exact typo, so it
  was an accidental match, not real coverage. The master-resume cleanup correctly fixed the
  wording and removed the tag; the honest fix (add a real `deep learning` tag backed by
  real content) is below.
- **Decision — a live fabrication-adjacent bug, found by accident while building the
  diagnosis feature, not something we went looking for:** `facets.labels_are_equivalent`
  reported `"C++" ~ "cloud computing"` as equivalent. `_alnum_compact("C++")` is `"c"` (the
  `+`s are stripped), so `"cloudcomputing".startswith("c")` passed the alphanumeric-prefix
  branch — and this project's own `Tools & Languages` skill group contains `"C++"`, so it
  was reachable end to end (`rename_is_jd_anchored` also passed, since the posting literally
  said "cloud computing environments"). A sibling bug lived in `_aligns` (the word-by-word
  acronym-alignment branch): `_aligns("curiosity", "C++")` returned `True` for the same
  reason — "curiosity".startswith("c"). **Fix: both branches now require a 2-character floor
  on the shorter side of a prefix match** (exact single-character matches, e.g. identical
  one-letter tokens, stay legal — only the *prefix shortcut* needed the floor).
  `Go`/`Golang`, `CI`/`CI-CD`, `Postgres`/`PostgreSQL`, and the RAG/GRPO acronym-expansion
  tests all still pass; `C++`/`cloud computing` and `R`/`React` now correctly fail. This
  found itself because the new `diagnose_gaps` feature (below) initially misreported
  "Curiosity" as evidenced by this resume's "C++" skill — a wrong answer from the very
  feature meant to give more precise answers, so it had to be fixed before that feature
  could ship.
- **New: `jd.extract_consensus(jd_text, known_tags=, runs=3)`** votes over `runs`
  independent extractions instead of trusting one. Groups by verbatim `phrase` (guaranteed
  literal by `verify_verbatim`, unlike `canonical` which is exactly what varies), keeps a
  phrase only if a majority of runs proposed it, and — the part that actually recovers real
  matches — among the canonicals a phrase's own surviving runs proposed, prefers one that
  hits `known_tags` over a more frequent one that doesn't. This never invents a mapping no
  run proposed; it only arbitrates between what the model itself already said across calls.
  `runs=1` is byte-identical to calling `extract` directly (existing behaviour, existing
  cache file) — `--extract-runs 1` on the CLI, or `extract_runs` in `JobSettings`, is the
  control. Cost: a clean CLI run goes from 5 calls to 7 at the default `runs=3`; `extract`
  is the cheapest stage (`effort="low"`), so this is the affordable place to spend it.
- **New: `report.diagnose_gaps(requirements, master) -> list[KeywordGap]`** answers *why*
  a must-have missed, not just that it did. Three reasons, first hit wins: `near_miss` (a
  bullet tag names the same thing under a different spelling — reuses the now-fixed
  `facets.labels_are_equivalent` rather than a second string-similarity implementation, so
  it inherits the acronym ladder, prefix containment, and token-set containment for free);
  `untagged_evidence` (the JD keyword matches `Project.tech`, a skills item, or coursework,
  but no *bullet tag* — real evidence, just not wired into the tag graph the scorer reads);
  `no_evidence` (nothing anywhere — the honest "you don't have this" answer). Verified
  against the real posting: `PyTorch` → `untagged_evidence` naming `proj_text2sql` (it was
  only ever in the project's `tech` array, never a bullet tag); `Tensorflow`, `statistics`,
  `cloud computing`, `Curiosity` → `no_evidence`, correctly, even after the `_aligns` fix.
- **Decision — `Project.tech` feeds `diagnose_gaps` but must never feed scoring.** `tech`
  is per-*project*; `rewrite._keyword_score` and `score_entry` are per-*bullet* and *sum*
  across a project's bullets. Folding tech into scoring would let one label like "PyTorch"
  earn a 4-bullet project `4 × MUST_HAVE_WEIGHT = 12.0` for a single fact, which is enough
  to evict a real employer under `MAX_PROJECT_ENTRIES`, and would require touching
  `merge.py`'s independent duplicate `_keyword_score` too. Reporting-only is zero risk;
  scoring it is a ranking change nobody asked for.
- **Trap, and how it's closed:** `facets.apply` truncates `Project.tech` to its ≤4-label
  render budget *before* `report.format_report`/`report_data` are called in both
  `tailor.py` and `web/jobs.py` — so diagnosing the post-facets resume can make
  `diagnose_gaps` wrongly say `no_evidence` for evidence that exists but got trimmed for
  display. Both functions gained a keyword-only `master: MasterResume | None = None`
  parameter (defaults to `resume`, so every pre-existing 3-arg call site is unchanged); both
  call sites now capture the resume *before* the `facets.apply` rebind and pass it through.
  Regression-tested (`test_diagnosis_reads_the_unfaceted_master`) by constructing a resume
  where the JD-relevant tech label is intentionally 5th of a `MAX_PROJECT_TECH`-4 pool.
- **Closed a related cache-invalidation hole:** `jd._slug` covered `_PROMPT_VERSION`, the
  backend fingerprint, the JD text, and `known_tags` — but not `TAG_ALIASES`, even though
  `extract` re-canonicalises every keyword through that table right before the cache write.
  Editing an alias therefore silently changed what a fresh extraction would produce while
  every already-cached `.requirements.json` kept serving the pre-edit mapping — exactly the
  failure class `config.fingerprint()` exists to prevent for the model/effort triple.
  `config.tag_alias_fingerprint()` (a 12-hex digest of the sorted table) is now folded into
  the payload. **One-time cost accepted, not worked around:** every existing cached
  extraction invalidates on the next run, same as when `config.fingerprint` was added for
  Gemini.
- **Data edits, made only after the diagnosis above could measure them:**
  - Added `deep learning` to `t2s_b1`/`t2s_b2`/`t2s_b3`'s tags (not `t2s_b4` — no deep
    learning content there — and not `inc_b1`, whose Random Forest/KNN/XGBoost content is
    classical ML, already covered by the `machine learning` tag). **Zero fabrication-guard
    widening, verified**: `deep` and `learning` are both already-permitted common words
    under `rewrite._is_factual_claim` (no digit, not `_ACRONYM`, not `_INTERNAL_CAPS`, not
    `_CAPITALISED` mid-sentence) on every bullet in the file regardless of tags — the tag
    adds no new licence to the guard.
  - `t2s_b3`'s text now reads "Optimized **PyTorch** GPU memory utilization…" (was:
    "Optimized GPU memory utilization…"), with a `pytorch` tag added alongside. Tag-only was
    rejected: `PyTorch` is `_INTERNAL_CAPS` (a real factual claim under the guard), so a
    bare tag with no text support would have inverted `data.py`'s own invariant ("tags …
    must name every technology mentioned in `text`") from a description into a licence.
    Naming it in the text first — true, since PyTorch is already in the project's `tech`
    array and TRL/DeepSpeed/Accelerate/vLLM are all PyTorch — makes the tag legitimate and
    adds zero new guard surface, since the text now licenses the token itself. Verified with
    `rewrite.check_fabrication` against a plausible rewrite: zero offenders.
  - Left `tensorflow`, `statistics`, `cloud computing` alone — `no_evidence` is the correct,
    honest answer, and the new report now says so explicitly instead of leaving it a
    mystery. Adding an umbrella `cloud computing` tag over the real AWS/Bedrock work would
    be `TAG_ALIASES`-by-another-name at the data layer; `SEMANTIC_WEIGHT` already gives that
    resonance to ranking, which is where it belongs.
  - Measured effect on the real posting: coverage went 3/10 → 4/10 on the same (noisy,
    unrevoted) cached extraction, with `Deep Learning` now correctly reported as `near_miss`
    (evidenced by the new tag) rather than `no_evidence`.
  - **Only `data/workspaces/default/master_resume.json` was edited.** The legacy
    `data/master_resume.json` (pre-workspaces path) was already stale before this session —
    it still reads `deeplearn`/no-PyTorch — and remains so. `config.MASTER_RESUME_PATH`
    defaults to the *legacy* path unless something calls `workspace.bootstrap()` first, which
    `python -m resume_tailor.content.data --validate` does not — so a bare `--validate` with no
    `--path`/`--workspace` silently validates the stale copy, not whatever profile is
    actually active. Logged here as a known gap, not fixed: `tailor.py` / `build_template.py`
    / `calibrate.py` all take `--workspace`; `data.py --validate` does not, and adding one
    is a small, separate, unrequested change.
- **New: `--validate` now surfaces `TAG_ALIASES` rewrites.** `Bullet._normalise_tags` runs
  `config.canonical_tag` silently at load — a tag typed `"performance measurement"` becomes
  `"performance"` with no signal to whoever typed it. `data._alias_rewrites` walks the raw
  (pre-validation) JSON and reports every raw tag that hit `TAG_ALIASES` specifically (not
  every tag `canonical_tag` touched — a pure case fold like `"Python"` → `"python"` is
  expected and would drown out a genuine substitution). This resume's own file currently
  reports zero rewrites — every tag in it is already written in canonical form.
- **On cross-industry generalisation (asked, not built — analysis only):** `TAG_ALIASES`
  should not become per-workspace. Its own docstring in `jd.extract` already concedes it
  "was hand-tuned for retrieval vocabulary and a different-domain posting re-opens the same
  gap" — per-workspace copies would multiply that hand-tuning per profile rather than fix
  it. What actually generalises: `known_tags` steering the LLM's own synonym judgement
  (already domain-agnostic — nothing about "reuse the candidate's vocabulary" is
  CS-specific), `diagnose_gaps`'s feedback loop (a business resume's first run reports
  `no_evidence: media planning` with the JD's verbatim phrase; tag the bullet; second run
  matches — feedback beats prediction because it cannot be wrong about what the posting
  asked for), `extract_consensus` (domain-agnostic by construction), and `SEMANTIC_WEIGHT`
  (already the mechanism for conceptual relatedness no tag encodes, in any domain). The
  fabrication guard also generalises unmodified — it keys on token *shape* (digits,
  acronyms, internal caps), not a CS dictionary, so `P&L`, `SEO`, `B2B` all behave.
- **Impact / tests added:** `tests/pipeline/test_facets.py` (rename-guard + `_aligns` regressions,
  9 new), `tests/pipeline/test_jd.py` (consensus voting + alias-fingerprint slug sensitivity, 9
  new), `tests/pipeline/test_report.py` / `test_report_data.py` (`diagnose_gaps`, the facets-trap
  regression, 7 new), `tests/test_config.py` (new file — `canonical_tag` and
  `tag_alias_fingerprint` had no unit test before this), `tests/content/test_data.py` (new file —
  `data.py` had no test file before this), `tests/cli/test_tailor_cli.py` /
  `tests/web/test_web.py` gained an autouse stub routing `extract_consensus` back to `extract`
  so existing wiring tests don't multiply their call counts or touch the real on-disk
  cache. Full suite: 377 collected, 361 passing, 16 pre-existing failures untouched
  (verified identical on `main` before this work — `test_facets`/`test_fit`/`test_merge`/
  `test_render`/`test_rewrite`, unrelated to anything here).

## 2026-08-08 — Added a sixth pipeline stage, skills.py, for a tailored skills list

**What:** New optional LLM stage `skills.py` selects and ranks a closed pool of the master
resume's own skill evidence (skills-group items, `Project.tech`, coursework titles, bullet
tags) against a posting, producing required/preferred/additional tiers with an optional
JD-anchored display rename per skill. Surfaced as a new "Skills to list" tile below
Application experience on the run page, backed by `GET /api/jobs/{id}/skills.md`,
`--skills-model`/`--no-skills` CLI flags, and a sixth `config.PURPOSES` entry (`"skills"`)
that inherits every model profile's routing (Ollama by default, same as the other five).

**Why:** Application forms almost always ask for a flat Skills list alongside a Description
field, and nothing in the existing pipeline answered that — `facets.py` only rewords
skills-section items, it never selects, drops, or ranks them. Tier and JD evidence are
computed in code rather than asked of the model, because `jd.Keyword.importance` is already
a *voted* field (`jd.extract_consensus` runs 3 extractions and votes specifically because
single-call importance classification was measured unstable). A second call re-deriving
required-vs-preferred would reintroduce that same noise, and could let this tile disagree
with `ReportCard`'s own coverage summary about the same posting.

**Impact:** The stage is fed `master_resume` — post-`include.apply`, pre-`facets.apply` —
deliberately: pre-facets so `Project.tech` isn't truncated to its ≤4-label render budget
before the pool sees it (the same hazard `report.diagnose_gaps`'s own `master=` parameter
exists for), and post-include so an excluded entry's skills are never suggested for the
package actually being submitted — the opposite of `expand.py`, which deliberately gets the
*unfiltered* resume. Pool membership is exact-key (`config.canonical_tag`), never
`facets.labels_are_equivalent` — that matcher's containment branches would collapse
"retrieval" into "hybrid retrieval & reranking" and silently drop half a claim, so it's used
only for JD *matching* (tiering), never for pool *construction*. Several tests hardcoded
`len(config.PURPOSES) == 5` or a 4-stage hybrid set and had to be updated for the sixth
stage — worth grepping for literal stage counts if a seventh stage is ever added. The
`expand.expand_experience` seam in `tests/web/test_web.py`'s job tests was already
unstubbed-by-default (silently attempting and swallowing a real call); `skills.select_skills`
got a proper default stub in the `client` fixture instead of repeating that gap.

## 2026-08-23 — Editable shipped vocabulary packs

- **Decision:** Move shipped pack tables from `library_seeds.py` Python constants into
  packaged JSON under `src/resume_tailor/library_seeds/`. `read_pack` now prefers a store
  file over the seed; the first edit writes a shadow to `data/libraries/packs/<id>.json`;
  `POST /api/libraries/packs/{id}/reset` deletes it.
- **Why:** User wanted full edit access to starter packs and a scrollable item viewer.
  Seeds cannot live in gitignored `data/` — Docker/fresh clone would boot with no
  vocabulary. `config.py` still imports `BUILTIN_PACKS["core-tech"]` at module load, so
  the loader keeps the same symbol/path.
- **Tradeoff:** Lazy shadow (not eager materialize on boot) — unedited installs pick up
  future seed improvements automatically; edited ones stay frozen until reset.
- **API/UI:** `builtin` now means "shipped, resettable"; new `customized` flag when a
  shadow exists. Settings Packs list: Edit on every pack, inline filterable item viewer,
  Reset to starter when edited, proposals can target shipped packs.
- **Follow-up:** Rebuild frontend (`npm run build`) before testing the Settings tab in the
  served SPA.

## 2026-08-23 — Editable writing-style prompts

- **Decision:** Split `rewrite._SYSTEM` and `expand._SYSTEM` into a locked core
  (fabrication, numbers, ids, length cliff) plus an editable style block stored as
  `JobSettings.rewrite_style` / `expand_style` in `settings.json` (`null` = shipped
  default). New `style.py` holds defaults, per-run `activate()` state, and
  `digest("expand")` for cache keys. `tailor.py` reads the active profile's saved style
  after `workspace.bootstrap()` so CLI and UI share one voice.
- **Why:** User wanted to edit the voice/tone instructions without touching safety rules.
  Nullable fields (not seeding default text into JSON) let future default improvements reach
  profiles that never customized.
- **Tradeoff:** Module state (`style._ACTIVE`) rather than threading through `fit.fit` →
  six function signatures — same pattern as `config._ACTIVE`.
- **UI cleanup:** Tailor tab Models section collapsed four per-stage model fields into one
  `model_name` blanket override (hidden under `hybrid`). Removed three skip toggles from
  the UI (semantic/widow/verb — still always on; CLI flags unchanged). Style editors live
  in the Advanced panel with locked-core preview and Reset to default.
- **Follow-up:** Verb variety and length are still enforced in code by `_polish` and
  `widowed()` even if the style text softens those instructions.

## 2026-09-21 — career-ops adoption (bands, guards, jdsim, cover angles, review)

- **Decision (bands score-neutral):** Added `Keyword.band` / `Keyword.evidence` orthogonal
  to `importance`. Nothing in ranking, selection, or the fit loop reads them — report and
  gap ordering only. Inferred evidence cannot reach critical/high (`_apply_evidence_cap`
  after extract and after vote). `jd._PROMPT_VERSION` bumped to 3 (deliberate cache bust
  of every extraction and, via `requirements.model_dump_json()` in the cover cache key,
  every cached cover letter).
- **Decision (`KeywordGap.evidence_tier`):** Plan asked for `evidence: str` on gaps, but
  `KeywordGap.evidence` already holds diagnostic snippets (`list[str]`). Named the new
  field `evidence_tier` to avoid a breaking rename across the API/SPA.
- **Decision (number rebinding, conservative):** `rebound_numbers` flags only when the
  source already binds the same number to a *different* noun. An unbound source number
  stays silent — a false positive that blocks a truthful rewrite is worse than a miss.
  Collects all significant nouns in a 3-token window so "40 remote engineers" still shares
  the source noun. Routed through new `guard_offenders` composite at the four rewrite
  call sites; `check_fabrication` unchanged for coverletter/expand.
- **Decision (authorship):** Whole-bullet `delegated_authorship` with closed verb/noun
  lists; joins the same composite. Internal "led a team that built X" never fires.
- **Decision (inconclusive coverage):** `extraction_diagnosis` replaces `0/0 (n/a)` with an
  explicit inconclusive line. `_vote` returns `consensus_dropped_all` via a PrivateAttr so
  the LLM output schema is untouched.
- **Decision (jdsim advisory-only):** `--suggest-reuse` prints the closest prior run; does
  not feed prior bullets into the fit loop. CLI archives under `output/jobs/cli-<stem>/`
  plus a `.jd.txt` sidecar so CLI runs join the web corpus.
- **Decision (cover angles ≠ instruction):** `CoverAngles` is its own parameter — routing
  through `instruction` would skip cache read/write and the guard retry. Soft genericness
  check warns without retry. `_COVER_PROMPT_VERSION` → 2.
- **Decision (review CLI-only first pass):** New `"review"` purpose in PURPOSES /
  DEFAULT_EFFORT / hybrid profile (missing hybrid entry is a KeyError, not a fallback).
  Suggested rewrites run through `check_fabrication`; nothing auto-applied. Web UI not
  wired yet (runProgress stage bands untouched).
- **Tradeoff:** Two importance axes can contradict (`nice_to_have` + `critical` band);
  report presents both without implying scoring disagreed. If that reads badly, clamp
  later.
- **Follow-up:** Tune rebound window against live runs; consider web exposure for review.

## 2026-09-21 — Rebound-number guard: alias-aware nouns, one offender per number

- **Decision:** `rewrite._noun_key` now normalises a bound noun through
  `config.canonical_tag` on top of `_significant`, and `rebound_numbers` reports a single
  claim per rebound number (the nearest bound noun) instead of one per window token.
- **Why:** A live `uci_b1` rejection surfaced as three offenders — `130 students`,
  `130 clarifying`, `130 python` — which read as three unrelated fabrications and got
  misdiagnosed as a missing `python` tag. It was one rebinding; the extra strings were
  just the other tokens in the 3-token bind window. Separately, a truthful rewrite that
  renames the same subject ("students" -> "undergraduates") had no way to pass short of
  editing the master resume text.
- **Tradeoff:** Equivalence now depends on the active vocabulary packs, so the guard's
  verdict can differ per workspace; that is the same "aliases generalise, code enforces"
  split `facets`/`jd` already use. Reporting only the nearest noun loses the adjective
  detail in the retry prompt — nothing about *what is rejected* changed, only its name.
- **Spec delta:** No weakening of the guard. `40 engineers` -> `40 hours` still fails,
  and a number with no source noun binding is still unjudgeable and silent.
- **Follow-up:** If `uci_b1` still trips after this, the source text binds `130` to a
  noun the packs don't alias — add the alias in a pack rather than editing the guard.
  Also fixed `tests/web/test_web.py::test_ollama_model_setting_repoints_only_the_ollama_stages`,
  which predated the `review` stage override.

## 2026-09-21 — Fabrication guard falls back and warns instead of hard-failing; screening's must-have coverage is informational only; fixed a years-regex false positive

- **What:** Three changes from evaluating a fresh apply-funnel run where every one of
  15 discovered postings failed for a different reason:
  1. `rewrite.rewrite_bullets`: a bullet that still fabricates after its one targeted
     retry (`_retry_fabrications`) no longer raises `FabricationError`. It falls back to
     that bullet's original, guard-clean master-resume text and is recorded in the new
     `RewriteOutcome.fabrications_rejected: dict[id -> offending terms]` — same shape and
     rationale as the existing `widow_repairs_rejected`. Applies everywhere
     `rewrite_bullets` is called (CLI, web tailoring, apply funnel), per explicit user
     choice over scoping it to the apply funnel only. `FabricationError` itself still
     exists (still importable/catchable by `tailor.py`/`web/jobs.py`) but is no longer
     raised anywhere in `rewrite.py`.
  2. `apply/funnel/screen.py`'s `screen()`: removed both must-have gates
     (`min_must_have_coverage`, `max_no_evidence_must_haves`) — coverage is still
     computed and surfaced on `ScreenResult`/the application record, but never rejects a
     posting. Both fields dropped from `ScreenSettings` and the frontend's mirrored type/
     defaults (`api.ts`, `runState.tsx`) since nothing else read them.
  3. `apply/funnel/eligibility.py`'s `_YEARS` regex: `\d{1,2}` had no boundary against starting
     mid-number, so "over **175** years" (company-history boilerplate) matched as "17"
     followed by "5 years", producing a false `requires_17_years` hard-reject. Added
     `(?<!\d)`/`(?!\d)` guards around both digit groups.
- **Why:** All three came out of reading `log-2026-09-21.txt`/`applications.json` from a
  run where zero of 15 postings reached `ready`: 2 Lazard postings hard-rejected on the
  regex bug, 1 AutoZone posting screened out purely on coverage (a heuristic the user
  decided shouldn't gate at all — tailoring exists to bridge exactly this gap), and 1
  AutoZone posting hard-failed the whole run over one bullet's fabrication rather than
  degrading gracefully.
- **Tradeoff:** The fabrication guard's *detection* is unchanged and still runs every
  time (CLAUDE.md's "do not weaken it" refers to `check_fabrication`/`guard_offenders`
  themselves, both untouched) — only the *consequence* of an unresolved fabrication
  changed, from "fail the whole tailoring run" to "keep the one bullet untailored and
  say so." The fallback text is always the verbatim master-resume source, so the
  documented invariant ("never invent resume content") still holds byte-for-byte; a
  run can no longer be blocked by one stubborn bullet, at the cost of that bullet
  possibly reading less tailored to the JD than its neighbors.
- **Follow-up:** Updated `tests/pipeline/test_rewrite.py`'s three fabrication tests
  (`test_fabrication_retry_still_fabricating_*`, `test_fabrication_retry_missing_id_*`,
  `test_rebound_*`) from `pytest.raises(FabricationError)` to asserting the fallback text
  plus `fabrications_rejected`. Added
  `test_company_history_number_does_not_read_as_years_requirement` to
  `tests/apply/funnel/test_eligibility.py`. Full suite green (983 passed), frontend `tsc -b`/lint/
  vitest green.

## P3-V: business vocabulary packs (2026-09)
- `finance-consulting` gains the valuation, modeling and data-terminal vocabulary. There are three new shipped packs: `accounting`, `marketing` and `ops-supply-chain`. Onboarding's "Business" field enables all four; choosing another field turns them all off.
- Composition rule for the launch set: new verbs join existing family names, and each verb belongs to exactly one shipped pack. Otherwise `_resolve_effective_uncached` reports "'x' moved from … to …" even when both packs name the same family. One real case was caught: accounting's "tested" collided with core-tech's `analyse`.
- Deviation from the plan: bare `ib`, `ap` and `ar` are not alias keys. They are too often International Baccalaureate, Advanced Placement or augmented reality on a student's resume. `ibd`, `a/p` and `a/r` carry the finance meanings instead. `pe → private equity` stays because it only runs when a business pack is enabled.
- Aliases fold Excel sub-features (VLOOKUP, pivot tables) into `excel`. That is deliberate: a posting naming VLOOKUP should match a bullet tagged Excel. The cost is that a VLOOKUP-specific requirement can't be told apart from general Excel.
- Cache keys: `config.tag_alias_fingerprint` (JD extraction) and `libraries.effective_fingerprint` (proposals) both change when a pack is enabled; `test_enabling_a_business_pack_changes_the_cache_fingerprints` pins it.

### 2026-09-30 ? Lower-bound token equivalence and targeted repair retry
The fabrication guard now treats N+ as equivalent to over N, more than N, at least N, and N or more only when that exact number and lower-bound claim occur in the source bullet. Bare N and under N do not license N+, and a different number remains rejected. The number-preservation check uses the same equivalence. This fixes tokenisation false positives without adding any new source claims. A percentage reduction expressed as by N% keeps its outcome subject before the number, so a following authoring action is not treated as a rebound; ordinary number-to-new-noun rebound checks remain. Measured widow and extension candidates receive one targeted fabrication retry, then retain their original guard-clean text if still invalid.

### 2026-09-30 — Preserve rebinding checks under lower-bound equivalence
Number-noun bindings normalise numeric N+ to N, so a source claim about over 30 staff still rejects a rewrite about 30+ hours. Percentage outcomes expressed as by N% bind to the preceding outcome nouns; changing troubleshooting time to office costs remains a rebound. The real aol_b2, uci_b1, and mro_b3 plus-form rewrites pass both the fabrication and numeric-preservation checks.

## 2026-10-01 — Profile target-field guidance and frozen run snapshots

**What:** Target field is profile metadata, separate from JobSettings. Presets compose with existing vocabulary packs and explicit overrides without rewriting libraries. Existing profiles retain the legacy path; new empty profiles start with General. Submitted runs capture effective prompts, styles, aliases, verb families, and entry context for later cover-letter regeneration.
**Why:** A posting supplies relevance rather than changing the candidate's field. Profile edits and shipped preset updates must not alter queued work or an older cover letter. Existing custom styles continue to replace only the editable style portion.
**Impact:** Six presets cover the existing vocabulary domains. Scoring weights, layout budgets, discovery, and form answering remain unchanged. New guidance makes verb variation optional when alternatives would change the claim; fabrication and numeric guards remain active.

2026-10-01 validation: the full hermetic backend suite passed (2,575 passed, 2 skipped), then 218 focused checks passed after the fresh-install default and CLI coverage additions. All 345 frontend tests passed; final selector/state tests, production build, typecheck, and frontend lint also passed (existing Fast Refresh warnings). Fresh installs with no migrated content use General; migrated profiles keep legacy guidance. Local Ollama was unavailable, so no live model evaluation was performed.

### 2026-10-04 — People-facing verbs and soft-skill tags stop losing every ranking
Resume Worded scored the user's tailored resumes 55-65 for teamwork and leadership. Two causes in code: (1) `core-tech`'s single `lead` verb family held all 14 leadership/teamwork openers (led, mentored, facilitated, trained, coordinated, partnered...), and `MAX_SAME_FAMILY_OPENERS` = 2 meant a third such opener on the page was always re-voiced. The audit found about 2.7 per resume. That family is now `lead` / `teach` / `coordinate` / `collaborate`; `collaborate` is the name `finance-consulting` already uses. The other shipped packs have no people-verb family to split (`finance-consulting`'s `lead` is only chaired/headed). (2) Soft must-haves were canonicalised to `teamwork`/`communication` but only matched those literal tags, so "Led a 3-person team" (tagged `leadership`) scored zero against a teamwork requirement. `config.SOFT_SKILL_RELATED_TAGS` widens a soft keyword's match to related tags at the same discounted `SOFT_SKILL_WEIGHT`, once per keyword, so a volunteer entry still cannot outrank a relevant job on soft tags alone. Workspaces can apply the split before a release through `libraries.json` `overrides.verb_families`.

### 2026-10-04 — length repairs keep the bullet's current opener

Live runs on v0.2.23 still showed "Built" opening three bullets with
`verb_collisions_remaining = 3`, even though the verb pass had re-voiced five. The
measured widow/over-long pass (and the pull-back) asks for a shorter version while
showing the master `<source>`, and a master that opens "Built…" pulls the old verb
back; that path never re-checked openers. `followups._keep_opener` now runs on every
length candidate (targets, ceilings, the fabrication retry): a candidate that adds a
verb collision gets the current opener back when its own opener is a known family
verb (a one-word swap), and is discarded otherwise. The prompts also ask to keep the
opener (`_REPAIR_PROMPT_VERSION = 6`).

## 2026-10-05 — dropped source numbers share the factual retry

**What:** Initial rewrites and their existing one-shot retry must retain every number-bearing token from source text. Missing figures receive a distinct retry instruction; a still-invalid or omitted reply falls back to verbatim source text with a run warning. The retry prompt version is 3.
**Why:** The vocabulary guard rejects invented figures but previously accepted omission of true ones. Numeric tags license terms without requiring them in prose. Verb-only polish now preserves its accepted text's numeric floor too, closing a path that could discard an initial rewrite's preserved metric.
**Impact:** Clean drafts add no calls, mixed failures share one retry, and missing-number detection/repair/fallback counts enter telemetry. Existing measured-repair floors and merge policies are retained.

## 2026-10-05 — entry ranking sums best three usable bullets

**What:** Entry scores sum their three highest existing bullet scores, reduced by a tighter per-entry cap, then apply the existing recency multiplier. Initial fit selection, new-entry top-up, and expansion extras receive the same resolved cap.
**Why:** Summing every stored bullet favored entries rich in weak material that could not all fit. The cap changes ranking, not the number of bullets the fit loop may render.
**Impact:** Individual semantic scores and their cache keys are unchanged; existing expansion cache keys already identify the selected source entries. Forced expansion entries, section isolation, chronological output order, stable ties and bullet floors are preserved. Telemetry marks this algorithm as best_three so measurements remain comparable.

## 2026-10-05 — rebound-number check: names, versions, acronyms, percentages

**What:** `bullet_checks._number_noun_surface` skips digit-bearing names (`EC2`, `S3`, `GPT-4`) and a version after a mid-bullet name (`Next.js 15`, `Python 3.11`); `_noun_key` lets a short all-caps acronym (`ARR`, `UI`) bind; a percentage binds the words before it (past a "by") and after it.
**Why:** Every widow repair discarded since 2026-10-02 was a rebound false positive: `ec2 natural-language`, `15 streaming`, `12 increasing` (source "increasing ARR by 12%" bound 12 only to the verb, because `_significant` drops "ARR" as short). Discarded repairs left near-empty last lines (128 warnings across 252 runs).
**Impact:** True rebinds still flag ("40 engineers" → "40 hours", "130 students/week" → "130 students/semester", "ARR by 12%" → "costs by 12%"). The term guard still checks the skipped tokens themselves. `tests/pipeline/test_rebound_false_positives.py`.

## 2026-10-05 — verb-family cap scales with page length

**What:** `config.family_opener_cap(n) = max(MAX_SAME_FAMILY_OPENERS, ceil(n / BULLETS_PER_FAMILY_OPENER))` replaces the flat cap of 2 in `bullet_checks.verb_collisions`: 3 on a 15-bullet page. Exact repeated openers stay forbidden. The rewrite prompt still asks for at most two (aiming stricter than the check is harmless and keeps the locked-style text unchanged).
**Why:** ~95% of runs ended with 2-3 "still open with a verb" warnings: a technical page carries four build-family openers and polish has one round, so the repair dodged to weaker unlisted verbs ("Coded", "Programmed").

## 2026-10-05 — scoring and facets run concurrently; coverage selection stays off

**What:** Web (`_TailorJobRun._score_with_facets`) and CLI (`_CliRun._score_with_facets`) score relevance on the calling thread while facets run on a worker (`config.submit_in_context`). Both read the unfiltered resume captured beforehand (`full_resume`), so the score cache key is unchanged; facets filters its own copy. A scoring failure waits for facets before propagating.
**Coverage-aware selection:** `config.COVERAGE_SELECTION` (env `RESUME_TAILOR_COVERAGE_SELECTION=1`) switches `selection._take_ranked`'s remainder to a greedy pick that discounts posting keywords already shown (1.0, `COVERAGE_REPEAT_DISCOUNT`, then 0; shared across section pools). Off by default: `scripts/eval_selection.py` over 255 saved runs changed picks in 164 but added no must-have (2.94 → 2.94 of 6.33; keywords 5.62 → 5.69). The unshown must-haves are not tagged on any bullet of the chosen entries, so it is an evidence gap, not a ranking one.

## 2026-10-05 - Project headers wrapped past one line (measured header width + PDF trim)

- **Symptom:** IDT posting run `348d2addba09`: `ResumeTailor - JD-Tailored Resume
  Pipeline | Python, FastAPI, Docker, GitHub Actions | Github  Jul 2026 - Present` pushed
  "Present" to a second line. A scan of 198 desktop runs found 19 wrapped headers (~5%),
  13+ on the ResumeTailor project.
- **Cause:** the tech budget was `CHARS_PER_LINE(121) - overhead - PROJECT_HEADER_GAP(4)`.
  121 is measured on lowercase bullet prose; a header (bold name, capitals, right tab)
  holds ~108 on the Lora/Word template. Every header of 109+ chars wrapped, none of 108-.
- **Fix, two layers:** (1) `fit_shrink.header_pass` runs last in `_FitRun._finish`: it
  matches each project header in the PDF (`fit_lines._wrapped_headers` via
  `render.line_layout`) and drops the last (weakest) tech tag of any that span >1 line,
  re-rendering until none wrap; with no tags left it warns. Trimming only frees space, so
  it cannot overflow. (2) `calibrate.calibrate_header_chars` binary-searches a real header
  probe and writes optional `header_chars_per_line` (109 on this template);
  `config.project_header_chars()` reads it, else `CHARS_PER_LINE - PROJECT_HEADER_GAP`
  (gap raised 4 -> 13 from the scan). Header calibration is soft: failure omits the key.
- **Also fixed:** `render._layout_from_words` joined a line's words in (top, x0) order; a
  hyperlink run Word sets ~2pt high ("Github") led its line, so no header with a link
  ever matched. Words are now x-sorted within a line (bullets with links benefit too).
- **Cache:** facets cache key now includes `project_header_chars()` (it changes the
  advertised `tech_char_budget`).

## 2026-10-08 - Weak openers and finance/consulting vocabulary
**Decision:** "Remove weak verbs" is enforced in code, not only by pruning packs, because `config.verb_family` only drives the repeated-opener cap and an unlisted verb is never flagged. `config.WEAK_OPENERS` is a short constant; `bullet_checks.verb_collisions` flags those openers as offenders (never claiming their word), so the existing bounded `followups._polish` call re-voices them. No extra call. `_REPAIR_PROMPT_VERSION` 6 -> 7, and the verb-repair instruction now requires equal scope (never upgrade helping into leading) because the fabrication guard checks terms, not verb scope.
**Pruned from core-tech:** handled, addressed, supported (operate); selected, reviewed (analyse); communicated (write). Pack edits only reach a profile that never edited the pack (a shadow under `data/libraries/packs/` wins until `reset_pack`).
**finance-consulting:** adds data-tool and credential spellings (Refinitiv/Eikon/LSEG, FactSet, Alteryx, FRM, CFP, CFA levels 2 and 3, Series licences) and consulting terms; `pitch book` (the document) deliberately does not alias to `pitchbook` (the platform). Verbs added: analyse (appraised, synthesized, hypothesized, triangulated, sized, scoped), advise, improve, and a new `execute` family. Aliases that would chain through ops-supply-chain's `process improvement` were dropped.
**Impact:** Runs with a weak opener now cost one polish call they previously skipped; the report line reads "repeated or vague opener(s)".

## 2026-10-09 — One vocabulary dictionary; bullet skills computed, not tagged
**What:** The five vocabulary packs became one always-on `library_seeds/dictionary.json` (120 terms, 230 spellings, 18 verb families; the ambiguous `mrr` and `10k` aliases dropped) plus app-wide user additions/hides in `data/libraries/vocabulary.json`; per-profile pack selection and overrides were migrated in (`libraries.migrate_legacy`) and retired. Bullet tags stopped being a required hand-maintained field: `Bullet.tags` is now optional "Extra skills", stored as typed, and match tags are computed per run (`content/bullet_tags.py`) as Extra skills ∪ detected-in-text (dictionary + the resume's own Skills/tech/coursework) ∪ inferred (`pipeline/tag_infer.py`, extract-purpose model, cached per text in `inferred_tags.json`, refreshed in the background after every save and filled at run start).
**Why:** Tags did three jobs at once (JD matching key, fabrication whitelist, Skills evidence) and consumers found them confusing; packs silently rewrote stored tags on the next save, which is why approvals needed the 409 acknowledgement rule. Canonicalising at read time removes that hazard, so the 409 rule is retired.
**Impact:** Inferred skills are matching-only — never the whitelist, `<permitted_skills>` or the Skills pool — so a model's guess can raise a bullet's rank but never license a claim. Detected skills already appear in the text; a rewrite that expands an abbreviation the user did not list (DCF → discounted cash flow) is now rejected by the guard unless it is an Extra skill. Imports no longer seed bullet tags or emit the `"untagged"` sentinel; `suggest-tags`, `suggest-tags-ai`, `propose_bullet_tags`, `suggest_open_tags` and `tag_suggest.py` are gone. The skills status endpoint must read the cache under the Tailor routing (`skill_refresh.pinned_tailor`) — the key folds in the backend fingerprint, and an unpinned read found nothing.

## 2026-10-11 — One extraction read by default; skill cache v2

- `EXTRACT_CONSENSUS_RUNS` 3 → 1. Trial on live postings (gemma4:cloud): one read vs
  three-vote consensus, keyword Jaccard 0.857 vs 0.875, must-haves 0.868 vs 0.886, top-15
  ranking 0.858 vs 0.889, seniority identical (100%). Two votes behave as a union — use 1
  or ≥3. Voting code is unchanged and still selectable (`extract_runs`, `--extract-runs`).
- `tag_infer` cache keyed without guidance (`config.fingerprint(..., include_guidance=False)`):
  the prompt never reads it, and keying on it split one cache between the Apply screen and
  the tailor run, each pruning the other's entries, so most runs re-inferred. File format
  v2 keeps one table per model (3 most recent), prunes only removed bullets, migrates v1
  entries with no model call, and serialises concurrent `ensure` per file + model. The
  server warms the active profile at startup.

## Posting-phrase repeat cap (2026-10-14)

Gemini runs mirrored multi-word posting phrases ("data engineering projects") into bullet
after bullet; the rewrite prompt already said "say each thing once", but only the opener
rule was enforced in code. `bullet_checks.phrase_collisions` now caps bullets sharing one
multi-word `Keyword.phrase` at `config.phrase_repeat_cap(pages)` (2 on one page, +1 per
extra page). Single-word phrases are exempt (a tool name recurring is the real stack).
Keepers are chosen as: unrepairable (context / verb-colliding) first, then bullets whose
master source already states the phrase, then selection order — only a bullet that
*added* the phrase is ever asked to drop it. The repair rides the existing polish call
(`<bullets_to_rephrase>`, `_REPAIR_PROMPT_VERSION` 8), gated by `repair_verbs`, and is
accepted only if every phrase is gone, the opener is unchanged, and it is guard-clean,
number-preserving, no longer, and not widowed. Silent by design: telemetry
`phrase_repeats` / `phrase_repaired`, never a run warning. Alongside, `jd._PROMPT_VERSION`
5 forbids duty clauses and generic work nouns as phrases; completed jobs keep their saved
`requirements.json`, only new runs re-extract.

## Hybrid dictionary extraction rejected (2026-10-14)

Tested a dictionary-first JD extractor (`scripts/evals/hybrid_extract.py`: leave-one-out
dictionary of vocabulary terms + resume skills + other postings' phrases, verbatim scan,
then one `jd._SYSTEM` labelling call with `<dictionary_candidates>`) against `jd.extract`
on gemini-3.8-flash: 80 saved tech postings, 25 fetched finance postings against a real
finance-consulting resume, 15 other non-tech postings, plus a 30-case current-vs-current
control (`python scripts\eval_models.py extract --name extract-e`). FAIL on 3 of 4 rules:
tech must-have coverage -6.2 pts (control drift 2.2), non-tech -1.4 pts (finance 0.346 ->
0.332), and the gpt-5-mini judge preferred current (hybrid lost 28% of pairs vs 23%
current-vs-itself). Only gain: self-consistency F1 0.842 vs 0.810. Same latency and
tokens. A dictionary does not help outside tech either; do not re-propose without a new
argument. Cross-model agreement was not run (could not change the verdict).

## Match-tag annotation is per run (2026-10-16; supersedes "runs are one at a time")

`bullet_tags` kept the run's resume terms and inferred skills in a module global while
jobs ran concurrently (`max_concurrent_jobs`, default 2): a second job's
`tag_infer.prepare_run` cleared and replaced the first job's annotation mid-selection, so
rankings, gaps and JD canonicalisation could silently use the other job's resume. The
annotation now lives on `config.RunContext` (`set_annotation` / `active_annotation`),
like routing and styles. Inside a run, an unannotated context reads an empty annotation,
never the process fallback (the fallback is whatever an earlier caller installed). Outside
a run (CLI, eval batch setup) the module fallback still applies. Non-job readers pass the
cached inference explicitly (`skill_refresh.cached_inference`; regenerated expansion calls
`tag_infer.annotate_cached` under the run's pins). `_table()` returns its local table so a
concurrent rebuild of `_TABLE` cannot hand back another run's phrase table. Test:
`test_parallel_runs_compute_what_serial_runs_compute` fails on the old global.

## Narrow guard equivalences from the retry probe (2026-10-16)

A retry probe (gemini-3.8-flash, 40 postings) recorded every factual-retry batch: 14
distinct batches, 21 rejected bullets, 25 offenders, and 7 of the 14 batches held only
false positives. Each equivalence below was added for an observed false positive, with
paired negatives (`tests/pipeline/test_guard_normalisation.py`) that must still fail and
existing rejections (versions, ranges, dates, fractions, `24/7`) that must survive:

- **Figure-led hyphen compounds** (`fabrication.split_figure_compounds`): "16K-token" reads
  as "16K token" in `numbers_dropped` and the rebound windows only (the term check is
  untouched). A changed unit is then a rebinding ("16K users" -> `rebound:16k users`).
  A version or range (`GPT-4-turbo`, `2-3`) stays whole.
- **Identifier compounds** ("E2B-sandboxed"): satisfied by the identifier plus a word sharing
  the first five letters of the joined word, so "o3" alone does not restate "o3-mini".
- **Slash lists**: a rewrite's slash compound splits only when a piece is purely alphabetic
  ("React 19/TypeScript" states 19); a source list of identifiers ("A30/L40S") is
  satisfied when every piece appears. All-numeric compounds stay whole on both sides.
- **Number words**: a rewrite's "four" states a source "4"; a source's "three" licenses
  "3". "zero" and "one" do not license a numeral ("one of the first" is not "#1").
- **Ampersand initialisms**: "W&B" passes when its letters begin consecutive source words,
  "&"/"and" skipped ("Weights & Biases", "profit and loss").
- **Rebound windows**: a closed modifier list (core, key, fundamental, ...) binds without
  using a window slot; a closed list of outcome verbs (reach/achieve/attain/hit forms)
  directly before a percentage is skipped like "by". No suffix rule: "staffing" and
  "testing" are subjects.

Deliberately unchanged: "SQL" on a text-to-SQL bullet, "18 Python and computer science
topics". Replay against the whole pre-change package in a worktree
(`scripts/evals/guard_replay.py`): 6 of 14 batches eliminated; 14 violations removed, 6
relabelled (a real drop of "16K-token" now reads `missing_number:16K`; "85 reached" now
reads "85 benchmark" for a draft that invented an evaluation benchmark), 5 retained, all
real drops or the deliberate cases above.

## Blank replies, estimated fit, cache keys and corrupt caches (2026-10-16)

- **Blank model text never replaces text.** A blank first draft counts as missing (source
  text stands, no retry); a blank factual retry falls back to source; `_keep_opener`
  discards a blank polish candidate (the pull-back path accepted "" as shorter); a blank
  merge keeps the members. Expansion already ignored blanks.
- **Estimated page counts always warn** (`resume_quality.ESTIMATED_WARNING`), even at full
  fill, so Fill asks for acknowledgement. No extra measurement retry: `convert.py`
  already retries its known transient failure.
- **Cache keys cover every prompt-visible input**: expansion adds each bullet's tags,
  skills the per-tag bullet counts, cover letters the education/skills/entry-header
  blocks (`resume` is a required key input), facets the formatted project, coursework and
  skill blocks (names, link setting, `MAX_PROJECT_TECH`, coursework budget).
- **A corrupt cache file is a miss** (`infra/atomic.read_cached`): logged, never deleted;
  the stage recomputes and replaces it through `atomic.write_text`. Before, a torn score
  cache raised, and the run fell back to keyword-only ranking.

## Coverage funnel: "in your resume" vs "on this page" (2026-10-16)

- The old must-have figure counted keywords the *master resume* supports, so a run that
  dropped every matching bullet still showed full coverage. `pipeline/coverage.py` now
  derives, per must-have keyword: resume evidence (`stated` = Extra skills, detected text
  or the Skills/tech/coursework pools; `inferred` = `tag_infer` only, matching-only and
  never counted as substantiated) and page evidence (`expressed` = named in the rendered
  text from `render.visible_text`; `tag_only` = an on-page bullet is tagged for it but
  never names it; `inferred_only`; `not_selected`).
- The denominator is every `must_have` keyword (soft included), so `in_resume` equals the
  existing `coverage_matched`; soft skills are expected to land as "backed, never named".
- `unsupported_additions` lists dictionary skills a final bullet names that its source
  neither states nor tags. Worded "potentially unsupported": the guard already accepted
  them (synonyms, licensed variants), so this is a review aid, not a violation.
- Old runs carry no page figure; the history and report show only the master number.

## Coverage funnel: headers count, hidden bullets don't, edits refresh it (2026-10-16)

Supersedes part of the funnel entry above. `render.visible_text` now includes job titles,
project names, degree lines and skill-group labels (a reader and an ATS see them), and
`render.page_bullet_ids` limits page evidence to bullets in enabled sections, so a bullet
in a disabled section never reads "Backed on this page". A bullet edit (`rerender`)
recomputes the page side with `coverage.refresh` (the resume side is kept: the master
resume is not in the run folder and an edit cannot change it), saves `coverage.json`, and
`run_lookup` overlays it on the run report and history row, as it does `quality.json`.

## Experiments E1/E2: cosmetic polish skipped on gemini-3.8-flash; the clause did not ship (2026-10-16)

Pre-registered, baseline commit cac1af4, Vertex gemini-3.8-flash at production effort,
judge gemini-4-argon in both orders (`scripts/eval_experiments.py`; results under
`output/eval/polish-clause/`). Pocock two looks, one-sided 0.0304 per look.

- **E1, polish on frozen drafts (look 1, 40/40 cases complete): "none" PASSES.** Net judge
  preference for no polish +0.425 [+0.275, +0.575] (17 wins, 0 losses, 23 ties); guard
  offenders and over-length bullets unchanged. "low" was CONTINUE (-0.175 [-0.350, 0.000])
  and, by the fixed sequence, untested further. Read sample: the medium polish mostly
  swapped a repeated "Built/Developed/Engineered" for a weaker "Coded/Programmed/Created",
  and the judge preferred the originals. Medium polish cost ~79 s and ~9k reasoning
  tokens per resume.
- **E2, "Do not add specifics the bullet never states (audience, frequency, setting,
  error types, scope), even plausible ones" (look 2, 80/80 complete): FAIL.** Judge net
  +0.175 [0.000, +0.350] (bar > 0); supported must-haves lost 0.25 per resume
  [0.15, 0.35] (bar <= 0.10); cost +5.7% [-3.7%, +15.9%] (bar <= +10%). Not shipped.
- **End to end (20 cases, CLI fit loop, process-isolated workers), baseline vs no polish:
  SHIP.** 20/20 in both arms, 0 failed or estimated, 0 over target; fill 0.930 -> 0.932;
  widows 0.15 -> 0; dropped 0 -> 0; fit rounds 1.45 -> 1.75; judge net +0.30; cost
  -40.7%; mean runtime 192 s -> 129 s.
- **Shipped:** `rewrite.cosmetic_polish_enabled()` is false only for gemini-3.8-flash
  (`_SKIP_COSMETIC_POLISH`); every other model keeps the polish. With it skipped, the
  leftover-verb warning counts exact repeats and vague openers only (the near-synonym
  family rule is what the polish was over-correcting) and says no repair ran.

## Correction: the no-polish saving, measured fairly (2026-10-16, supersedes the figures above and in `e86caea`)

The end-to-end "cost -40.7%, runtime 192 s -> 129 s" mixed cache conditions: the
baseline arm ran first and paid for extraction, scoring, facets and skills (20 calls
each, 80 in all) that the no-polish arm then read from cache. Only rewrite calls are
comparable: rewrite cost $1.415 -> $1.076 over 20 cases, **-24.0% end to end**; time in
those requests 152 s -> 116 s per run. The frozen-draft figure (~40% of rewrite cost,
E1) is a different measurement: identical drafts, polish only, no fit loop. The skip is
unchanged; only the claimed saving is. The e2e cost gate now excludes cached stages.

## Cosmetic polish off for every model (2026-10-16, supersedes the gemini-only skip)

Rule set in advance: "remove unless it wins". Polish stays for a model family only if,
on the same frozen drafts, the one-sided 95% upper bound on net judge preference for the
unpolished drafts is below 0 (gemini-4-argon, both orders; `scripts/evals/survey.py`).

| Model | Cases | Unpolished wins | Polished wins | Ties | Net for none [bounds] |
|---|---|---|---|---|---|
| gemini-3.8-flash (E1) | 40 | 17 | 0 | 23 | +0.425 [+0.275, +0.575] |
| gemma4:31b (Ollama Cloud, the default model) | 40 | 26 | 2 | 12 | +0.600 [+0.450, +0.750] |
| claude-haiku-5-5 | 20 | 4 | 0 | 16 | +0.200 [+0.050, +0.350] |
| nemotron-3-super (survey, indicative) | 4 | 1 | 0 | 3 | +0.25 |

No model's polish won, so `rewrite._KEEP_COSMETIC_POLISH` (family prefixes) ships empty
and `cosmetic_polish_enabled()` is false everywhere; the polish code stays for evals and
for a family that later measures better. A blind read of Haiku's 16 changed cases found
the same pattern as Gemini's: strong, specific openers swapped for weaker ones (Built ->
Wrote/Coded/Created, Architected -> Produced/Structured, Designed -> Authored) and
occasional dropped articles or words. Polish cost per resume: Haiku 15 s / $0.0185
(about a third of its rewrite cost), Nemotron 68 s, bonsai-27b 133-161 s, gemma-4-12b
187 s, Gemini ~79 s; and on Nemotron one runaway polish reply failed a whole run.

## Cosmetic polish removed; top-up drafts see the page's openers (2026-10-16)

Supersedes the keep-list above: `rewrite.cosmetic_polish`, `cosmetic_polish_enabled` and
`_KEEP_COSMETIC_POLISH` are gone, and `rewrite_bullets` makes no opener or phrase-repeat
follow-up call (it also lost its no-op `repair_widows` and `target_pages` parameters).
The shared repair engine `followups._polish` stays: the fit loop's measured widow repair
(`fit_shrink`) and merged-bullet pull-back (`bullet_merge`) run on it, and its verb and
phrase-repeat branches are still tested and driven by the eval harness
(`scripts/evals/stages.cosmetic_polish` replays the removed pass on frozen drafts).

What replaces the repair for repetition: the draft prompt's existing rule ("no two may
open with the same verb..."), plus, for bullets the fit loop's top-up adds later, an
`<openers_already_used>` block listing the verbs the page's other bullets open with
(`rewrite._used_openers`), at no extra call. `--no-verb-repair` / `no_verb_repair` now
switch that block off. The run report keeps counting exact repeats and vague openers
(no near-synonym family rule) and says to vary them by hand. First drafts' prompts are
byte-identical to before; only top-up prompts change, and the rewrite is uncached.

## Length repairs keep numbers and drop the near-synonym rule; the openers hint is a preference (2026-10-16)

Correction to the note above: `followups._polish` also shortens ordinary bullets, not
only merged ones. On overflow, `bullet_merge.pull_back` cuts near-widow bullets, and the
measured pass in `fit_shrink` fixes widows and over-long bullets. A review of the kept
engine found three gaps, all fixed:

- **Pull-back could drop a number.** The `ceilings` path checked the guard and the
  length but never `numbers_dropped`, so "…handling 120 requests per second with
  retries…" -> "Built a service with retries." counted as a repair. The prompt already
  asks to keep every number. Now a `ceilings` bullet's numbers are checked against its
  current text, on the first reply and on the fabrication retry alike
  (`test_pull_back_never_drops_a_number`).
- **`_keep_opener` still used the retired near-synonym rule** (`verb_collisions`
  defaults to `families=True`), so a shortened "Built…" became "Documented…" only
  because other bullets opened with "Designed" and "Engineered". It now counts exact
  repeats and vague verbs only, like the run report.
- **The `<openers_already_used>` block forbade any first word**, "Python" included. It
  now lists known resume verbs only (`config.verb_family`) and asks for a different
  opener only when an equally accurate one exists ("accuracy comes first"). Top-up
  prompts only; first drafts are unchanged.
