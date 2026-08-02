# ResumeTailor — Build Plan & Progress

Self-contained record of what is built, why it works the way it does, and what is still
undecided. Written so a session with no prior context can pick the work up. `CLAUDE.md`
holds the invariants and gotchas you need *before touching code*; this file holds the
history behind them — every phase below, plus the live failures that shaped selection,
page fitting, and the fabrication guard.

All build phases are complete. What remains is in **Open items**, and is mostly decisions
for the owner rather than missing code.

**Last updated:** 2026-08-02 — facets stage extended to reword SKILLS-section items toward
JD-anchored synonyms, under the same rename-guard pattern as project tech tags.

---

## Status at a glance

| Phase | State | Notes |
|---|---|---|
| 0 — Scaffold & environment | **Done** | venv, deps, package installed editable, CLAUDE.md, `.claude/settings.json` |
| 1 — Template generation | **Done** | `scripts/build_template.py`; verified 1-page, text-identical render |
| 2 — Master data | **Done** | 39 bullets, 30 with metrics, 102 tags, 6 roles, 8 projects |
| 3 — JD extraction | **Done** | `jd.py`; prompt reworked after the first live run (see below) |
| 4 — Select & rewrite | **Done** | `rewrite.py`; fabrication guard hardened against five live false positives |
| 5 — Render & fit loop | **Done** | `render.py`, calibration, `fit.py` |
| 6 — CLI & report | **Done** | `tailor.py`, `report.py` |
| 7 — Per-section ranking | **Done** | experience and projects ranked separately, capped at 3 and 2 |
| 8 — Semantic-aware ranking | **Done** | closed-vocabulary canonicalisation, LLM score table, `kind` on keywords |
| 9 — Pluggable model backends | **Done** | `llm.py`; `--model claude\|ollama\|hybrid`; per-stage effort; backend in cache keys |
| 10 — Widow elimination | **Done** | length band + `_polish` (widows); `UNDERFLOW_THRESHOLD` 0.85 → 0.92; template re-exported |
| 11 — Bullet merging | **Done** | `merge.propose` + `rewrite._merge_bullets`; overflow-gated; redundancy gate |
| 12 — Verb variety + merge anti-repetition | **Done** | `_polish` verb half; UI merge / `--no-verb-repair`; master openers diversified |

**The pipeline runs end to end against the live API.** A search/retrieval intern posting
produces a 1-page resume (90% full) at 100% must-have keyword coverage in 2 iterations,
showing 3 experience entries and 2 projects, with the template's formatting, hyperlinks,
and tab-aligned dates intact.

**187 tests pass** (`pytest`). They cover selection scoring, the fabrication guard, four
template-rendering regressions, the fit loop's selection/shorten/underflow logic, the run
report, and the CLI's exit codes (`rewrite_bullets`, `render`, and `jd.extract`
monkeypatched). No test exercises a live API call.

---

## What exists

```
src/resume_tailor/
  config.py    paths, backend routing (profiles/specs/effort), page-fit constants,
               TAG_ALIASES, scoring weights
  data.py      Pydantic schema + loader/validator for master_resume.json
  llm.py       provider boundary: client_for(stage) → Anthropic or any OpenAI-compatible
               endpoint (Ollama local/Cloud, vLLM, Groq, OpenRouter, GLM, Kimi)
  jd.py        JD text → JobRequirements (LLM, cached to output/)
  rewrite.py   score/select_entries/select_within_entries (pure) + rewrite_bullets (LLM)
               + check_fabrication (pure)
  render.py    build_context, render, to_pdf, page_count, line_count, measure_detail
  fit.py       choose_entries → select bullets → rewrite → render → measure loop;
               budget estimate + FitError
  report.py    end-of-run summary: coverage, rewrites per section, fit, warnings
tailor.py      CLI entry point (repo root)
scripts/
  build_template.py   original_export.docx → main_template.docx
  render_dummy.py     smoke test: render full master resume, report page count
  calibrate.py        derives CHARS_PER_LINE / LINES_PER_PAGE from real PDF renders
tests/
  test_rewrite.py     scoring, selection, fabrication guard
  test_render.py      four template regressions + spacing normalisation
  test_fit.py         budget estimation + fit loop logic (rewrite/render monkeypatched)
  test_report.py      coverage, per-section rewrite counts, dropped entries, warnings
  test_tailor_cli.py  flag wiring, exit codes, error presentation, backend selection
  test_jd.py          prompt contents, cache keys, schema back-compat
  test_llm.py         spec parsing, JSON recovery, the unconstrained-backend failure modes
```

---

## Using it

```powershell
.venv\Scripts\activate
notepad data\jd\acme-ml-intern.txt                          # paste the posting, plain text
python tailor.py --jd data\jd\acme-ml-intern.txt --out output\acme.docx
```

`data\jd\` is gitignored. **`output\` is not** — despite a `# Generated output` heading in
`.gitignore`, no pattern follows it, so rendered resumes (which carry phone and email) are
stageable. Verified with `git check-ignore`. Raised in `CLAUDE.md`; the owner decides.

Naming the output per posting matters: the
default `--out` is always `output\tailored.docx`, so runs overwrite each other otherwise.

Extractions are cached by JD-text hash to `output\*.requirements.json` and reused across
fit-loop retries, so a re-run of the same posting costs one API call instead of two. Pass
`--no-cache` after changing a prompt or `TAG_ALIASES`.

Reading the report:

- **Low coverage** — check the "Not supported by the master resume" line first. A keyword
  genuinely in the candidate's background just needs a `TAG_ALIASES` entry; the alias table
  is meant to be extended freely, since an unmatched alias costs a missed bullet, never a
  crash.
- **A wanted entry under `Dropped entirely`** — raise `--experience` / `--projects`.
- **A fabrication error** — inspect the named source bullet before assuming the model
  misbehaved. Historically it has always been the guard's tokenisation or a tag missing a
  technology the bullet's own text mentions.

---

## Build history

### Phase 5b — Calibration — **Done**

`scripts/calibrate.py` measures `CHARS_PER_LINE` and `LINES_PER_PAGE` against the real
template: it binary-searches a single synthetic bullet's wrap point (via `pypdf` layout-
mode PDF text extraction, which preserves visual line breaks) for `CHARS_PER_LINE`, then
binary-searches how many one-line bullets fit on page 1 for `LINES_PER_PAGE`. It re-verifies
both known-good anchors (39-bullet superset → 3 pages; 13-bullet current-resume subset → 1
page) before writing the constants into `config.py`.

Measured values: `CHARS_PER_LINE = 101` (placeholder had guessed 105), `LINES_PER_PAGE = 52`
(placeholder had guessed 46; it read 51 until the resume was re-exported with uniform
single line spacing, which recovered a line). Re-run `python scripts/calibrate.py` after any change to the
template, fonts, or margins — these numbers are specific to `main_template.docx`.

### Phase 5c — `fit.py`, the shorten-and-retry loop — **Done**

`fit.fit(resume, requirements, target_pages=..., template=..., out=...)`:

- Sizes the initial selection cheaply via `fit.estimate_lines` (a character/line budget
  model over `CHARS_PER_LINE`/`LINES_PER_PAGE` that mirrors `render.build_context`'s own
  entry-dropping rule), then calls `rewrite.select_within_entries`/`rewrite_bullets` and
  does one real render + `render.measure_detail()` for ground truth.
- On overflow (measured pages > target), re-runs `rewrite_bullets` on the *same* selection
  at the next `config.SHORTEN_SCHEDULE` value (15 → 25 → 35), up to `MAX_FIT_ATTEMPTS` (3).
  Exhausting that raises `fit.FitError` naming the largest overflowing sections and the
  estimated line excess — **never silently truncates**.
- On underflow (measured fill below `UNDERFLOW_THRESHOLD`, 0.85), grows the selection and
  restarts the inner rewrite loop, rather than accepting a half-empty page. Growth is sized
  from the measured shortfall (not one bullet per round trip) and bounded by
  `MAX_GROW_ATTEMPTS`; unlike overflow, exhausting it is **not** fatal — the fullest version
  reached is returned with a warning, since a sparse resume is still valid output.
- `render.to_pdf`/`measure*` gained a `keep_active` flag so Word stays open across retries
  within one `fit()` call and is released only on the call's last conversion; on a
  `RuntimeError` from Word/COM, `fit()` falls back to the budget estimate (with a warning
  in `FitResult.warnings`) and still returns the `.docx` it already rendered.

### Phase 6 — CLI and report — **Done**

```
python tailor.py --jd jd.txt [--out output/tailored.docx] [--pages 1]
                 [--experience 3] [--projects 2] [--template ...] [--no-cache]
```

Prints must-have keyword coverage as `n/m`, must-haves the master resume cannot support at
all, bullets kept/rewritten per entry, entries dropped entirely, iterations used, final page
count, and the output path. Exit 0 on a fitting resume, 1 on any failure. `report.py` is
pure formatting over a `FitResult`, so the summary is testable without argparse or stdout.

### First live end-to-end run — **Done**

The pipeline ran end to end against the real API. Four things needed fixing, all found this
way and all now covered by regression tests:

1. **`jd.verify_verbatim()` came back empty** — the verbatim guarantee held on the first
   try, so no fix was needed there.
2. **Extraction produced unusable `canonical` values.** The model returned whole
   requirement sentences ("Hands-on experience with vector databases and semantic search")
   as single keywords, whose canonical forms can never match a bullet tag. Coverage read
   **2/12 (17%)** while the resume genuinely matched. The prompt now demands *one entry per
   atomic skill*, a short taxonomy-style `canonical` (no verbs, no "and"/parentheses), and
   skips degree/visa/location requirements. Coverage went to **13/16**, then **100%** once
   `TAG_ALIASES` learned the retrieval vocabulary (`retrieval-augmented generation` → `rag`,
   `hybrid search` → `hybrid retrieval`, `rerankers` → `reranking`, …).
3. **The fabrication guard produced a run of false positives**, each blocking a run on a
   rewrite that invented nothing. See the guard section below — this is the subtle part of
   the codebase now.
4. **Underflow was judged on the estimate while overflow used the real render**, so a page
   measured at 82% full shipped without the loop ever trying to fill it. `render.line_count`
   now reports real laid-out lines (the same measurement `calibrate.py` used to derive
   `LINES_PER_PAGE`, so the two are comparable), and both decisions use it.

Rewrites were **not** bland at `EFFORT="medium"`, which is now actually wired (below).

### Phase 7 — Per-section ranking and entry caps — **Done**

The first live runs ranked all 39 bullets in one pool, which let a stack of relevant side
projects outscore the candidate's **current employer** and drop it from the resume
entirely. Fixed by making selection two-level:

- `rewrite.select_entries` ranks experience and projects **independently** against
  `config.MAX_EXPERIENCE_ENTRIES` (3) and `MAX_PROJECT_ENTRIES` (2), overridable per run
  with `--experience` / `--projects`. `score_entry` sums a whole entry's bullet scores: an
  entry earns a capped slot by offering several usable lines, not one strong bullet. The
  sort is stable over document order, which is reverse-chronological, so ties break toward
  the more recent entry.
- `fit.choose_entries` runs that once, before any rewriting. Which entries appear is a
  decision about the resume's *shape*; the fit loop may only vary how many bullets they get.
- `rewrite.select_within_entries` guarantees every chosen entry keeps at least its best
  bullet, because `render.build_context` omits an entry whose bullets were all dropped —
  without the floor the loop could silently delete a job it had just decided to keep. The
  fit loop's search floor is therefore one bullet per entry, not zero.

Result on the search/retrieval posting: Age of Learning (the current internship) is back,
alongside VNPT and UC Irvine, with AetherMind and ZotAssistant as the two projects — 1 page,
90% full, 100% keyword coverage.

### The fabrication guard, after contact with reality

`check_fabrication` is the tool's correctness property and the easiest thing to get subtly
wrong. Every fix below makes it *more accurate*, never more permissive about invented
tools or numbers — that distinction is the whole point, and `CLAUDE.md` forbids relaxing
the check to make a run pass.

Live false positives and their resolutions:

| Rejected | Why it was wrong | Fix |
|---|---|---|
| `Python/FastAPI` | `_TOKEN` treats `/` as *internal*, so the compound arrived as one token absent from a vocabulary holding each half separately | A compound is permitted when every part is permitted — it claims exactly what its parts claim |
| `GPUs` | The bullet's tags carry `gpu`; only the plural differed | Trailing `s` matched in both directions |
| `LLM-powered` | `LLM` is a tag; `powered` is grammatical glue asserting nothing | Same compound rule, applied to all separators |
| `Next.js/React` | Both halves are whole vocabulary entries, but the splitter shattered `Next.js` into `Next`+`js` first | Split coarsest-separator-first (`/` before `-`/`.`), re-checking each part whole |
| `MRR` | Source says `Recall@k/MRR`; `@` is *not* an internal separator, so the source tokenised as `Recall` + `k/MRR` and bare `MRR` was never in the vocabulary | `_vocabulary` now contributes source compounds' parts too — the guard decomposes both sides or neither |
| `CS` | The bullet is tagged `computer science fundamentals`; the model abbreviated it | An all-caps token matching the initials of consecutive source words is permitted (`_initialisms`) |

Two invariants keep that from opening a hole, both pinned by tests:

- **Only letter-bearing parts enter the vocabulary.** Splitting `96.3` into `96` and `3`
  would invent numeric vocabulary the source never asserted, and a fabricated metric is
  exactly what this guard exists to catch.
- **Numbers are single tokens with no separator**, so compound splitting never reaches
  them. A fabricated `99%`, or a version bump from a source naming `GPT-4.1` (which
  tokenises whole, leaving `GPT` untraceable alone), still fails.

The initialism rule is the one deliberate loosening: an invented acronym could in principle
match some run of source words by coincidence, costing a missed catch. Rejecting every
abbreviation instead blocks faithful rewrites outright, and an invented *tool* is nearly
always spelled out rather than acronymised. `GRPO` against an unrelated bullet is still
caught, and that case is tested.

### Phase 8 — Semantic-aware ranking — **Done**

A Mistral "AI Data Solutions Intern" posting rendered **one bullet** under Age of Learning,
the current internship, while `aol_b2`/`aol_b3` (data analysis, stakeholder communication)
scored **0.0** — on a posting whose stated core is *"Analyze data, workflows, and user
feedback"* and *"present recommendations to cross-functional stakeholders."*

Root cause: **7 of 10 keywords matched no tag at all** (coverage 2/7). `jd.extract` was
canonicalising in a vacuum — inventing taxonomy tags with no knowledge of the resume's 102 —
so it emitted `communication skills` against a resume tagged `communication`, and
`analytical skills` against `data analysis`. Phase 6 closed the same gap by hand for
retrieval vocabulary via `TAG_ALIASES`; a different-domain posting simply re-opened it,
which is what made a general fix necessary rather than more aliases.

Four changes:

1. **Closed-vocabulary canonicalisation.** `extract()` takes `known_tags` and puts the
   resume's tag vocabulary in the prompt, telling the model to reuse an existing tag when
   one genuinely means the same thing and to coin a new one *only* when nothing fits — a
   forced match would destroy the signal that the candidate lacks a skill. Passed as plain
   strings, not a `MasterResume`: `jd.py` imports only `config`, and the JD half of the
   pipeline has no business knowing the resume's shape.
2. **`Keyword.kind` (`technical` | `soft`), scored at `config.SOFT_SKILL_WEIGHT = 1.5`.**
   Once soft skills actually match, they are worth a full must-have's 3.0 — and soft tags
   are broad, sitting on the volunteer and support entries. Measured: with weights untouched,
   Valley Christian (office assistant) went 0.0 → 7.0 purely on communication/teamwork.
   Defaults to `technical`, which is both the conservative reading and what keeps
   pre-existing caches and every `Keyword(...)` in the test suite valid.
3. **LLM relevance table (`rewrite.score_table`), the third API call.** Scores all 39 bullets
   0-10 against the posting, **including `domain_notes`** — which until now was extracted,
   paid for, and never used for ranking. Added to the keyword score, scaled by
   `config.SEMANTIC_WEIGHT = 0.5`; at `0.0` scoring is byte-identical to keyword-only, which
   is what makes it A/B-testable. Values are clamped 0-10 on the way in, since this is the
   only unbounded number in the ranking path.
4. **Cache keys cover their inputs.** `_slug` now hashes the JD *plus* the tag vocabulary
   *plus* `_PROMPT_VERSION`, so a prompt edit or a re-tagged resume invalidates
   automatically instead of relying on someone remembering `--no-cache`.

**Measured on the live posting** (`--no-semantic` vs full, both 1 page, 1 iteration):

| | Before | Vocab fix | + semantic |
|---|---|---|---|
| Must-have coverage | 2/7 (29%) | **6/7 (86%)** | 6/7 |
| Age of Learning bullets | 1 | 2 | **3** |
| Age of Learning entry score | 1.0 | — | 12.0 |
| Valley Christian | 0.0 | held out | held out |
| Unmatched canonicals | 7, silent | 1 (`spreadsheets`), reported | 1 |

The semantic layer's clearest win is `aol_b3` — cross-functional collaboration, scored
**8.0**, the single best-matched bullet on the resume for this posting and worth exactly
0.0 under tag matching.

**A hypothesis that did not survive contact.** The motivating example for semantic ranking
was ZotAssistant: a *university academic advising* chatbot against a team doing *STEM
academic content* partnerships — resonance no tag can encode. The model did not weight it
that way, scoring those bullets 5-6. Semantic ranking moved ZotAssistant from 5th to 4th
(8.0 → 16.5) but not into the top 2. Domain resonance is a weaker signal than expected;
the vocabulary fix did the real work.

**A sixth fabrication-guard false positive, found the same way.** `aol_b2` reaching the
resume for the first time exposed it: `_TOKEN` did not treat `,` as internal, so `1,000`
tokenised as `1` + `000`, and a faithful rewrite of "over 1,000" was rejected over a phantom
`000+`. This was a *hole*, not just noise — both fragments entered the vocabulary as whole
tokens, so a source containing `1,000` licensed a bare `000` or `1` in any rewrite, against
the "numbers are checked whole" invariant. Adding `,` to `_TOKEN` and `_SPLIT_PATTERNS`
strictly strengthens the guard: `1,000` now passes, `000`, `1`, and a fabricated `2,500` are
all caught. Tested.

Not relaxed: the guard still rejects `1,000+` against a source saying "over 1,000". The
model restated a figure against an explicit "preserve every number exactly as written"
instruction, so that is a correct catch, not a false positive. It recurred during Phase 9
verification, confirming it is live and non-deterministic rather than a one-off.

### Phase 9 — Pluggable model backends — **Done**

Driven by cost: ~$0.48/run × ~100 applications ≈ $50–65. `llm.py` now routes each stage to
a backend, `--model` selects one, and the default path is unchanged.

**The first measurement reframed the work.** The prompts are tiny — the largest call sends
~2,800 input tokens (all 39 bullets are 1,940) and returns ~1,250. At Sonnet rates that is
~$0.03 against ~$0.16 billed. **The missing ~80% is reasoning tokens**, drawn from
`MAX_TOKENS` and billed as output. So effort became a per-stage knob (`low`/`low`/`medium`)
and is the cheaper half of the change; backend routing is the other half.

**Ollama Cloud has no constrained decoding, which invalidated the original design.** Probed
against `nemotron-3-super:cloud`:

| Request | Result |
|---|---|
| `response_format: {json_schema, strict}` | HTTP 200, **markdown prose** — accepted, unenforced |
| Native `/api/chat` with `format: <schema>` | **markdown prose** — Ollama's own param, also unenforced |
| `response_format: {json_object}` alone | valid JSON, **invented shape** |
| **schema in system prompt + `json_object`** | **exact schema match, first attempt** |

The planned fallback ladder escalated on HTTP 4xx. Non-compliance here is a **200**, so that
design would have sailed past every fallback into a hard failure. `llm.py` therefore puts the
schema in the prompt and escalates on *parse failure*. The speculative `json_schema` attempt
was dropped from the default path entirely — on this backend it always fails, and free-tier
quota makes a guaranteed-useless round trip a real cost.

**Measured on the Mistral posting, all three stages, 1 page / 1 iteration each:**

| | Claude (effort=low) | Claude (effort=medium) | Ollama Nemotron |
|---|---|---|---|
| Keywords extracted | 11 | 11 | 15 |
| **Non-atomic phrases** | 6 | 5 | **1** |
| Unmatched canonicals | 3 | — | 8 |
| Must-have coverage | 5/8 (62%) | — | 5/10 (50%) |
| Score spread | 1–5, 5 distinct, median 3 | 1–7, 7 distinct | **2–10, 9 distinct, median 6** |
| Fabrication failures | 0 | 1 (the `1,000+` case) | 0 |

Two results worth keeping, both contrary to expectation:

- **Nemotron extracted *more* atomically than Claude** (1 violation vs 5–6) and produced a
  **wider, better-calibrated relevance spread**. The prediction that a non-frontier model
  would compress scores into 6–8 was wrong; Claude at `low` effort compressed harder (1–5).
- **Nemotron coined more canonicals outside the vocabulary** (8 vs 3), pulling generic filler
  the prompt says to skip ("emerging technologies", "problem solving", "attention to detail").
  This is where it is genuinely weaker, and it costs must-have coverage.

**Claude at `low` vs `medium` effort is near-identical for extraction** (11 keywords, 5–6
non-atomic either way), which is the evidence for the lowered defaults.

**A pre-existing prompt weakness, surfaced but not fixed.** Both backends violate `_SYSTEM`'s
ATOMIC rule on this posting, emitting whole requirement sentences as one keyword
("Strong organizational skills with exceptional attention to detail"). That is a `jd._SYSTEM`
problem, not a backend problem, and fixing it means bumping `_PROMPT_VERSION`. Out of scope
for Phase 9; the highest-value next change to extraction.

---

## Decisions made (and why)

| Decision | Rationale |
|---|---|
| Own `.docx` + `docxtpl`, not a template library | The entire point: bring your own design and get it back unchanged. |
| Template is **generated** by a script, not hand-tagged | Tags must sit inside specific runs; the resume changed once mid-development, which would have invalidated hand-tagging. |
| `master_resume.json` is a **superset** | Retains roles dropped from the current CV so a differently-flavoured posting can surface them. Chosen over mirroring the current resume. |
| Selection deterministic, rewriting LLM | Makes fit-loop retries cheap and predictable. |
| Experience and projects ranked **separately**, with per-section entry caps | Pooling them ranked side projects above the current employer and dropped it from the resume. Section shape is a decision the reader expects to be stable, not an outcome of keyword scoring. |
| Entry choice fixed before the fit loop; only bullets flex | Prevents the loop from silently deleting a job it had just decided was relevant. Every chosen entry keeps at least its best bullet. |
| Fabrication guard in **code**, not prompt | "No invented experience" is a correctness property, not a preference. |
| JD extraction canonicalises against the resume's **own tag vocabulary** | Canonicalising in a vacuum produced tags that could never match (`communication skills` vs `communication`), costing 7 of 10 keywords silently. `TAG_ALIASES` fixes this per-domain by hand and does not generalise. |
| Semantic relevance is a **score table**, computed once, never inside the fit loop | `_initial_selection_size` binary-searches over the bullet count and the loop re-selects on every grow attempt — an API call there costs a dozen round trips per run. A table that shifted between iterations would also let a grow step *swap* bullets rather than add them, decoupling the estimate from the render. |
| Semantic score **added** to keyword score, not replacing it | The two answer different questions — "did they literally use this tool" vs "is this relevant at all". Keeping both means `SEMANTIC_WEIGHT = 0.0` is an exact control, so an improvement can be attributed rather than guessed at. |
| Soft-skill must-haves discounted to `SOFT_SKILL_WEIGHT` | Soft tags are broad and sit on the volunteer/support entries; at full must-have weight an office-assistant role scored 7.0 on communication/teamwork alone. |
| Budget-first page fitting, render as verification | Most runs should fit without paying for a Word render. The budget sizes the *initial* selection; overflow and underflow are both decided on the real render, because the estimate proved optimistic enough to ship an 82%-full page. |
| Name/contact/EDUCATION left literal in template | They don't vary by posting; tagging the contact line risks its hyperlink for no gain. |
| Bullet spacing normalised per section | Per-entry spacing cannot survive a loop; normalising to the tightest variant prevents silent page inflation. |

### Open items

- **`--from PATH` on `build_template.py` is implemented** (copies are not automatic: pass
  `--from` or use the Template tab). Profile-based imports cover renamed headings /
  separators for single-column paragraph resumes; tables and multi-column layouts remain
  unsupported.
- Two projects (`proj_zotassistant`, `proj_fuzzy_street`) have `link: "Github"` but no
  `url`, so the label renders as plain text rather than a hyperlink. Add the URLs or clear
  the labels.
- **`EFFORT` and `MAX_TOKENS` are coupled.** Reasoning tokens come out of `max_tokens`, and
  these are non-streaming calls, which the SDK caps at 21,333 (`3600 * max_tokens / 128_000
  > 600` is refused outright). `MAX_TOKENS = 21_000` leaves `"medium"` working with room to
  spare; raising `EFFORT` beyond that means **switching to streaming**, not raising the
  number. At the old 16k, `"medium"` spent the whole allowance thinking and returned
  `stop_reason='max_tokens'`.
- Contact email in master data is `jaydentran@mro.com.vn`, taken from the resume; the
  account email is `vutt4@uci.edu`. Confirm which is intended.
- One bullet (`uci_b2`) has a trailing period the source resume lacks — deliberate
  punctuation consistency, revert if exact fidelity matters more.
- **Repo has no commits yet** (branch `master`, everything untracked), and `.gitignore`
  gained `templates/` and `data/` mid-development. Those two lines reverse this file's
  earlier "`master_resume.json` is committed deliberately" position and mean a fresh clone
  contains neither the content source nor the baseline export — it would not run at all.
  `data/master_resume.json` does hold PII (phone, email), so excluding it is defensible;
  the point is that the two records disagree and **the owner has not yet decided**. Resolve
  it before the first commit: either drop those lines, or keep them and say so here.

---

## Verification

Full check after any change:

```powershell
python scripts\build_template.py
python -m resume_tailor.data --validate     # expect: 39 bullets, 102 tags
python scripts\render_dummy.py              # expect: 3 pages (full superset)
pytest                                       # expect: 147 passed
```

Live check (costs three API calls; needs `ANTHROPIC_API_KEY` and Word):

```powershell
python tailor.py --jd path\to\jd.txt        # expect: exit 0, 1 page, no fabrication error
```

A/B check on ranking, when a posting ranks surprisingly. The two runs differ only in whether
the semantic table is consulted, so any change in the report is attributable to it:

```powershell
python tailor.py --jd data\jd\mistral.txt --no-cache --no-semantic --out output\ab_keyword_only.docx
python tailor.py --jd data\jd\mistral.txt --no-cache --out output\ab_semantic.docx
```

The per-bullet scores and the model's one-line reasons are cached in
`output/<hash>.scores.json` — read that before concluding a ranking is wrong.

Fidelity check (strongest template test): render only the 13 bullets that appear in the
current resume — `aol_b1..3, vnpt_b1..2, uci_b1..2, aeth_b1..3, t2s_b1..3` — and diff
paragraph text against `templates/original_export.docx`. Expect **1 page** and only two
differences, both intentional: the longer superset skills line, and `uci_b2`'s trailing
period.

---

## Phase 10 — Widow elimination — **Done**

Two problems were reported together: inconsistent spacing under the section rules, and
bullets whose last line held a single word. The first was fixed in the source document by
the owner and is recorded here only because it changed the calibration; the second is this
phase.

### The section rules (owner's fix, not a code change)

The original export was internally inconsistent: `PROJECTS` and `SKILLS` were followed by a
literal empty paragraph, `EDUCATION` and `WORK EXPERIENCES` by nothing at all. Measured on
the rendered PDF, the gap from a heading baseline to the first content baseline was 14.8pt,
14.8pt, 23.0pt, 23.0pt — against a body line pitch of 12.8pt. The re-export gives all four
sections the same 2pt spacer paragraph, and normalises every paragraph to single spacing
(project bullets had carried a 1.15 override).

Residual spread after the re-export, same measurement: **17.9 / 17.9 / 21.0 / 19.9pt** — a
3pt spread where it used to be 8pt. Not perfectly uniform; the remaining difference is in
the export, not in `build_template.py`.

Consequence for this repo: `scripts/calibrate.py` re-run, `LINES_PER_PAGE` 51 → **52**. The
uniform single spacing is what recovered the line.

### The widows

**Diagnosed by measurement, and the cause is arithmetic, not taste.** `fit.py` sets
`char_budget = 2 * CHARS_PER_LINE = 202` and `_SYSTEM` stated it as a ceiling. Every widow
in every render in `output/` was a bullet at **204-207 characters** — an overshoot of two to
five:

| Render | Pages | Widowed bullets | Their lengths |
|---|---|---|---|
| `ab_claude` | 1 | 2 of 11 | 204, 207 |
| `ab_claude_med` | 2 | 4 of 11 | 204, 205, 206, 207 |
| `tailored` | 1 | **0** | all 180-196 |
| `ab_semantic` | 1 | **0** | all 182-199 |

The clean runs were clean for exactly one reason: every bullet landed under 202. Going two
characters over costs a whole line; landing twenty-five short costs nothing, and the prompt
communicated only the upper bound.

**Three layers, in order of how much they carry:**

1. **A target band, not a ceiling.** `_format_bullets` emits `target="172-197" max="197"`
   (`_length_band`), and `_SYSTEM` explains the asymmetry: *"Length is a cliff, not a limit
   … Err short, never long."* This is what actually did the work — on the verification run
   the repair pass never fired.
2. **`rewrite.widowed()`** flags any bullet spanning more than one line whose last line is
   under `WIDOW_MIN_FILL` (30%) full, and returns an exact ceiling one full line below where
   it ends, less `WIDOW_SAFETY`.
3. **`_tighten_widows`** re-sends only those bullets, once. Non-regressive by construction:
   a reply replaces the original only if it is both shorter and no longer widowed, so a
   longer, still-widowed, unrecognised, or missing reply changes nothing. `check_fabrication`
   runs on repaired text — shortening under pressure is precisely when a model compresses a
   claim into something the source never said.

`--no-widow-repair` is the control half of the A/B, mirroring `--no-semantic`.

### Reclaiming the space

Removing widows makes a page genuinely shorter, and `UNDERFLOW_THRESHOLD = 0.85` would not
have noticed — that value was calibrated against pages that still contained widows, so some
of the "full" lines it counted held one word. Raised to **0.92**, which reuses the existing
grow machinery rather than adding a path.

This is the one fit constant with a running cost, so it was measured rather than assumed.
Same posting, same everything else:

| Threshold | Bullets | Lines | Iterations |
|---|---|---|---|
| 0.92 | 13 of 15 | 49 / 52 | 3 |
| 0.88 | 12 of 15 | 47 / 52 | 2 |

One extra rewrite call buys one extra bullet. Kept at 0.92; 0.88 is the documented fallback
for bulk applying on a metered backend.

### Verified

`python tailor.py --jd data/jd/mistral.txt` → **1 page, 0 widowed lines, 13 of 15 bullets,
49 of 52 lines.** Confirmed against the rendered PDF's real layout (group layout lines by
the bullet glyph, flag any group whose final line holds ≤ 3 words), not against the
character estimate — the same check reported 3 widows on `ab_claude.pdf` and 5 on
`ab_claude_med.pdf`.

### Known limits

- **The detector predicts wrapping from an average.** `CHARS_PER_LINE` is a mean, so an
  unusually wide bullet can widow at 195 and be missed. It catches the systematic 2-to-5
  character overshoot, which was every case measured; it is not a layout engine.
- **Shortening is the only repair.** A widow can also be killed by lengthening the bullet to
  fill its last line, which preserves more content. Not done: the ask was to stop wasting
  space, and growing text toward a boundary risks the fabrication guard for no page gain.

---

## Phase 11 — Bullet merging (opt-in) — **Done (unit-tested), live runs pending**

**What:** Add the ability to merge redundant bullets within the same job/project entry into
fewer rewritten bullets.

**How:** A deterministic proposal step (`merge.propose`) suggests merge groups, and
`rewrite._merge_bullets` performs one additional LLM rewrite only when `--merge` / web
`settings.merge` is enabled and the proposal passes acceptance.

**Safety checks (non-negotiable):**
- Merge candidates are accepted only when they are non-regressive in `line_span` terms.
- Fabrication is checked against the union vocabulary of all merged members
  (multi-source guard).
- Every number-bearing token from every merged member must survive into the candidate
  text (`numbers_dropped`).
- The merged bullet must not be widowed (widow repair remains a later pass).
- The merged text must not restate significant tokens or stack same-family verbs
  (`redundancy_offenders`).

**Gating:** `fit.fit` proposes merges only when `merge_bullets` is on *and* `attempt >= 1`
(a measured overflow has already happened). Eager first-draft merges combined the most
similar adjacent pair for no page reason and read repetitively.

**Status:** `pytest` covers proposal heuristics, merge acceptance behavior, multi-source
guard invariants, redundancy rejection, id-collapsing into the renderer, and the report
string. Live API / rendered PDF A/B runs for the merge knob are not executed in this
environment yet.

---

## Phase 12 — Verb variety and merge anti-repetition — **Done**

**What:** Stop resumes from reading as "Designed... Engineered... Architected..." and stop
merges from concatenating two similar bullets into one repetitive line. Expose the merge
toggle in the web UI.

**How:**
- `_SYSTEM` and `_MERGE_INSTRUCTION` ask the model not to stack near-synonym openers or
  restate shared tools/metrics.
- `config.VERB_FAMILIES` + `rewrite.verb_collisions` detect exact duplicate openers and
  family over-concentration (`MAX_SAME_FAMILY_OPENERS = 2`).
- `rewrite._tighten_widows` generalised to `_polish`: one follow-up call carrying widows
  and/or verb collisions. Widow fabrication remains a hard failure; a bad verb swap is
  discarded.
- CLI `--no-verb-repair`; web `merge` + `no_verb_repair` toggles; report fields for
  `verbs_diversified` / `verb_collisions_remaining`.
- Master resume openers diversified (Designed/Built/Reduced collisions).

**Prompt versions:** `_SYSTEM` / merge / polish instructions are not cached, so no version
bump was required (only `_SCORE_SYSTEM` is versioned). Editing bullet text in
`master_resume.json` invalidates score caches by design.

---

## Phase 13 — Application-form experience expansion — **Done (unit-tested)**

**What:** After a successful tailor run, generate expanded work-experience descriptions for
the separate "Experience" fields of online applications (title, company, dates, location,
description), shown as a copy-paste tile on the Tailor page.

**How:**
- New purpose `"expand"` in `config.PURPOSES`. Follows the profile (`claude` / `ollama`);
  `hybrid` routes expand to Ollama. Override with `--expand-model` / `settings.expand_model`.
- New module `expand.py`: deterministic entry selection via `rewrite.select_entries`,
  force-including every experience entry that contributed bullets to the tailored resume;
  one batched LLM call returning bullets only; hard facts joined from `MasterResume`.
- Fabrication guard runs per bullet against the entry's full source vocabulary; offenders
  are **dropped with a warning**, never raise — this artifact must not fail a run whose
  `.docx` already succeeded. `numbers_dropped` and `verb_collisions` warn the same way.
- Character budget `EXPAND_CHAR_LIMIT` (2000) advertised as a target band; overflow trims
  from the end.
- CLI prints the expansion and writes `<out>.expansion.md`. Web stores
  `Job.expansion` on `JobStatusResponse`, writes `output/jobs/<id>/expansion.{json,md}`,
  and serves `GET /api/jobs/{id}/expansion.md`. SPA tile: `ExperienceCard.tsx`.
- `--no-expand` / `settings.no_expand` skips the stage.

**Prompt version:** `_EXPAND_PROMPT_VERSION = 1`, folded into the cache key with
`config.fingerprint("expand")`.

**Status:** `pytest` covers selection force-include, hard-fact join, fabrication drop,
number warnings, cache invalidation across backends, hybrid routing, CLI stubs, and the
web expansion endpoint. Live API quality under Ollama is not measured in this environment.

## Phase 14 — Skills-section wording synonyms — **Done (unit-tested)**

**What:** `facets.select_facets` may now reword individual SKILLS-section items toward the
posting's own wording (`"Postgres"` -> `"PostgreSQL"`, `"RAG pipelines"` ->
`"retrieval-augmented generation pipelines"`), mirroring the existing project-tech-tag
rename. Scope is rename-only — group count, item count, and item order are unchanged;
skill groups still render in full every run, only an item's spelling may change.

**Why a new predicate instead of reusing `labels_are_equivalent` as-is:** project tech tags
are single words, so `labels_are_equivalent`'s three "may claim more" branches — token-set
containment, alphanumeric-prefix containment, sub-phrase acronym — never mattered in
practice. Skill items are phrases, and each branch independently lets a rename *narrow* to
part of what the item claims. Measured against real `master_resume.json` items before
writing the guard:

| old | new | branch that (wrongly) accepts it |
|---|---|---|
| `hybrid retrieval & reranking` | `retrieval` | token-set containment |
| `retrieval eval (Recall@k, MRR, LLM-as-judge)` | `retrieval` | alphanumeric prefix |
| `hybrid retrieval & reranking` | `HR` | sub-span acronym |
| `Scikit-learn/XGBoost` | `scikit-learn` | alphanumeric prefix |

A single `allow_narrowing` flag on `labels_are_equivalent` was considered and rejected — it
can only close one branch at a time, and closing all three by branching inside the shared
function would also change project-tag acceptance in ways not asked for. Instead
`facets.rename_preserves_claim(old, new)` is a separate predicate applied *in addition to*
`labels_are_equivalent`: the existing function answers "does not claim more," the new one
answers "does not claim less." A skill rename is applied only when
`rename_is_jd_anchored AND labels_are_equivalent AND rename_preserves_claim` all hold.

**Acronym-in-phrase renames went into the shared function, not a skills-only one.**
`"RAG pipelines" -> "retrieval-augmented generation pipelines"` needs per-token acronym
alignment (`facets._aligns`, greedy word-by-word, expanding 2-5-word initial runs) that
`labels_are_equivalent`'s existing acronym branch doesn't provide — that branch only
matches when the *entire* label is the acronym, not one word inside a longer phrase.
Deliberately added as an `_aligns` clause on `labels_are_equivalent` itself (owner's call,
asked directly) rather than kept skills-only, so project tech tags gained the same
capability. Verified additive: `SQL -> Snowflake` and `SQL -> MySQL` — the two existing
rejection tests — still reject, because `_aligns` requires full word coverage on both sides
and neither pair achieves it.

**Line budget is a second, independent guard.** `_resolve_skill_group` accepts a
guard-clean rename only if it does not increase `config.line_span` of the group's rendered
line (`config.skill_group_line`, shared with `fit._fixed_overhead_lines` so the two cannot
drift — before this, `": "` was hard-coded separately in `fit.py`). This is load-bearing,
not theoretical: measured slack on the real resume was 28 characters on the `AI/ML` group
against its two-line budget (202 chars), the tightest of the three groups. Renames are
applied greedily and re-measured against the *accumulated* item list per group, so several
individually-safe renames cannot jointly overflow.

**Known accepted limitation:** `"RAG pipelines" -> "retrieval-augmented generation"`
(dropping "pipelines") correctly rejects via `rename_preserves_claim`, but a rename that
*adds* an acronym expansion inside an otherwise-unrelated longer phrase can still fail to
align if the surrounding words don't match anything — this is intentional conservatism, not
a known bug: the guard is designed to reject when in doubt.

**Prompt version:** `_PROMPT_VERSION` bumped 1 -> 2 (schema and `_SYSTEM` both changed),
invalidating every previously cached `.facets.json`. `_cache_path` also now folds in every
skill group's items and `config.CHARS_PER_LINE`, since the prompt advertises a per-group
character budget computed from it.

**Status:** `pytest` covers all four narrowing rejections above, JD-anchored acceptance,
acronym-expansion acceptance, the line-budget rejection (sized from `config.CHARS_PER_LINE`
so it survives recalibration), rename-count/order preservation, duplicate-item rejection,
unmatched-key warning, the `--no-facets` identity path, cache-key coverage, and the
extended fake-client test asserting skill groups reach the prompt and `skill_renames`
round-trips through `FacetResult`. Live API behavior (whether models reliably propose
skill renames worth having) is not measured in this environment.
