# Implementation Notes

Running record of decisions made while building the web UI and container, especially the
ones that are not in the plan or that reinterpret it. See `docs/PLAN.md` for the history
of the CLI pipeline itself.

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

## 2026-07-26 ? Workspace cleanup

**What:** Cleared `output/` (~30 MB of tailored docs, calibration temps, score caches),
Python `__pycache__` / `.pytest_cache`, and `frontend/dist`. Added the missing `output/`
rule under the existing `.gitignore` heading so regenerated resumes are not stageable.

**Why:** `output/` held full resumes (PII) and was only commented as ignored, not actually
ignored. Kept `data/`, `templates/`, `.venv`, `frontend/node_modules`, and
`docker/soffice.Dockerfile` (still used by `scripts/compare_pdf_backends.py`).

**Impact:** Next `docker compose up --build` or `npm run build` recreates the SPA; next
tailor run recreates job artifacts under `output/jobs/`.

## 2026-07-26 ? UNDERFLOW_THRESHOLD lowered to 0.86

**What:** `config.UNDERFLOW_THRESHOLD` changed from 0.92 to 0.86.

**Why:** Live runs often started at ~10 bullets (~86% page fill after the first rewrite)
and triggered a grow round because 86% < 92%. Lowering the threshold accepts that fill on
the first measure and skips an extra rewrite pass.

**Tradeoff:** Slightly more whitespace at the bottom of a one-pager; raise back toward
0.92 if tighter packing matters more than API cost.

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

**Follow-up:** No regression test yet; `tests/test_render.py` skips when the template is
unbuilt, so a bolding assertion there would only run on a machine that has `templates/`.

## 2026-07-26 ? Default Ollama model changed

**What:** Changed `config.OLLAMA_MODEL` from `nemotron-3-super:cloud` to
`minimax-m3:cloud`, and updated the matching examples in `tailor.py`, `.env.example`, and
`CLAUDE.md`.

**Why:** The requested default backend for the `ollama` profile is now `minimax-m3:cloud`,
so the code and user-facing configuration examples need to point at the same model.

**Impact:** Runs using `--model ollama` or the `hybrid` profile now default extract/score
to `minimax-m3:cloud` unless `OLLAMA_MODEL` or a per-run model override is set.
## 2026-07-26 ? Raised MAX_TOKENS to 32,000 with per-backend clamping

**Decision:** Set `MAX_TOKENS = 32_000` in `config.py` and added `ANTHROPIC_NONSTREAMING_MAX_TOKENS = 21_333` plus a new `max_tokens_for(purpose)` accessor. All four `client.messages.parse` call sites in `jd.py` and `rewrite.py` now call `config.max_tokens_for()` instead of `config.MAX_TOKENS` directly.

**Why:** 32 k gives OpenAI-compatible and Ollama backends a larger reasoning budget. The Anthropic SDK refuses non-streaming requests above 21,333 tokens client-side (`3600 * max_tokens / 128_000 > 600`), so the higher value can't be sent as-is to Claude without breaking every run.

**Tradeoff:** Claude calls silently receive 21,333 even when MAX_TOKENS is higher. The comment on MAX_TOKENS and the new function docstring explain this, so it is visible without reading the SDK source.

**Spec delta:** User asked for `32_000`; Claude paths are capped at `21_333` to remain within the SDK's non-streaming limit.

**Follow-up:** Switching to streaming on the Anthropic path would allow the full 32 k budget there too ? see `llm.py` comment on ANTHROPIC_NONSTREAMING_MAX_TOKENS.

## 2026-07-26 ? Bullet merging feature (opt-in)

**What:** Implemented an optional `--merge` pass that merges redundant bullet points within the same entry. The fit loop calls `merge.propose` (pure heuristic), and `rewrite` applies accepted merges via `rewrite._merge_bullets`.

**Why:** This is a non-truncation space lever: merged output is accepted only if it is non-regressive in line-span, passes a multi-source fabrication guard, preserves every number-bearing token, and does not create a new widow (widow repair remains a later step).

**Impact:** Accepted merges delete absorbed bullet ids from the `bullets: dict[id -> text]` currency so the existing renderer automatically places the merged line where the survivor bullet appears in the master resume.

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

## 2026-07-27 ? Bullet marker size and experience header bold split

**What:** `scripts/build_template.py` now (1) normalizes every lvl0 bullet definition in `numbering.xml` to `Noto Sans Symbols`, (2) retargets experience/project bullet prototypes to the education list id, (3) picks experience headers with separate company/location runs, and (4) inserts a plain run in `tag_header` when fields would otherwise merge into a bold run.

**Why:** Google Docs exported six nearly duplicate list defs; `pick_bullet_prototype` chose spacing-tight bullets whose markers drew in Lora (large dots) while education kept Noto (small dots). Experience headers used `min(header_run_count)`, collapsing `{{ job.location }}` into the bold company run.

**Impact:** Re-run `python scripts/build_template.py` after any resume re-export. Education spacing already matched experience at the paragraph-property level once numIds unified ? no education-only spacing rewrite was needed. Regression tests in `tests/test_render.py` cover Noto markers, shared numId, and bold company / plain location.

## 2026-07-27 ? Default Ollama model ? deepseek-v4-flash:cloud

**What:** Changed `config.OLLAMA_MODEL` default from `minimax-m3:cloud` to `deepseek-v4-flash:cloud`, and updated matching examples in `tailor.py`, `.env.example`, and `CLAUDE.md`.

**Why:** Owner requested the new default for the `ollama` / `hybrid` profiles.

**Impact:** `--model ollama` and `hybrid` extract/score now use `deepseek-v4-flash:cloud` unless `OLLAMA_MODEL` overrides it. Restart Docker / re-resolve config to pick up the change.

## 2026-07-27 ? Default Ollama model ? gemma4:cloud

**What:** Changed `config.OLLAMA_MODEL` default from `deepseek-v4-flash:cloud` to `gemma4:cloud`, and updated matching examples in `tailor.py`, `.env.example`, and `CLAUDE.md`.

**Why:** Owner requested the new default for the `ollama` / `hybrid` profiles.

**Impact:** `--model ollama` and `hybrid` extract/score now use `gemma4:cloud` unless `OLLAMA_MODEL` overrides it. Restart Docker / re-resolve config to pick up the change.

## 2026-07-27 ? Force single line spacing in template build

**What:** `scripts/build_template.py` now runs `normalize_single_spacing` after tagging: every body paragraph gets `w:line=240`; non-list paragraphs use `lineRule=auto` (Word ?Single?), list paragraphs use `lineRule=exact` (240 twips = 12pt). Rebuilt `templates/main_template.docx`.

**Why:** Owner reported line spacing > 1. Export already had auto/240 on most content, but name/contact/spacers were unset, and LibreOffice PDFs showed ~15.7pt wrap pitch on bullets for 10pt text ? auto line boxes inflate when the bullet marker font is substituted (DejaVuSans when Noto is missing). Exact locks bullet line height.

**Tradeoff:** Exact 12pt on bullets is slightly tighter than Word?s font-metric ?Single?; may shift fit calibration. Re-run `scripts/calibrate.py` (and inside Docker for soffice) if page packing looks off.

**Follow-up:** Optional: install Noto Sans Symbols in the container so marker metrics match Word without relying on exact.

## 2026-07-27 ? Reduce repetition (merge gating + verb polish)

**What:** Merges now propose only after a measured overflow (`attempt >= 1`). Merge candidates that restate significant tokens or stack same-family verbs are rejected via `redundancy_offenders`. Opening-verb collisions are detected with `VERB_FAMILIES` / `verb_collisions` and repaired in the shared `_polish` follow-up (formerly `_tighten_widows`). Web UI exposes "Merge redundant bullets" and "Skip verb variety repair"; CLI adds `--no-verb-repair`. Master resume openers diversified away from 4? Designed / 2? Built / 2? Reduced.

**Why:** Eager merges picked the most similar adjacent pair and produced repetitive lines; the rewrite prompt only asked for "strong-verb-first" with no variety rule; the source data itself collided.

**Tradeoff:** A run with verb collisions but no widows costs one extra call (still within the five-call cap). Verb-swap fabrication discards the candidate instead of failing the run ? cosmetic polish must not abort a valid draft. Score caches invalidate after master-resume text edits.

**Spec delta:** Extends Phase 11 merge behavior and Phase 10 widow repair into a combined polish pass; overflow gating was not in the original merge ask.

## 2026-07-27 ? Stop forcing soft-skill keywords into bullets

**What:** Four edits in `src/resume_tailor/rewrite.py`. (1) `_SYSTEM`'s mirroring rule now narrows to "only where the posting names something the bullet already does" and states that an unclaimable keyword is meant to go unused. (2) Two new `_SYSTEM` rules: soft skills are demonstrated, never named (with the two live offenders quoted as counter-examples), and bullets must read as plain description rather than assembled vocabulary. (3) `_format_keywords` labels `kind == "soft"` keywords `[soft ? demonstrate, never name]` instead of `[REQUIRED]`. (4) The shorten instruction and `_REPAIR_INSTRUCTION` now preserve "required *technical* keywords" rather than all REQUIRED keywords.

**Why:** A Mistral posting produced "Applied problem-solving skills to a 45% accuracy bottleneck", "Utilized verbal communication skills to facilitate three weekly labs", "Demonstrated attention to detail by...", and "Exercised organizational skills to mentor...". Not a model defect: `_SYSTEM` opened by asking for mirrored JD language, and `_format_keywords` handed the model soft-skill phrases marked `REQUIRED` with no `kind` distinction ? `Keyword.kind` existed but was consumed only by ranking (`_keyword_weight` / `SOFT_SKILL_WEIGHT`), never by the rewrite prompt. The fabrication guard passed these correctly; the phrases trace to the bullets' own tags, so this was never a fabrication failure.

**Tradeoff:** Literal soft-skill keyword coverage drops, which may matter for naive ATS substring matching ? the judgement is that a hiring reader discounts asserted soft skills more than a keyword scanner rewards them. Soft skills still carry their `SOFT_SKILL_WEIGHT` in ranking, so they keep influencing *which* bullets are selected; only the verbatim phrasing is withheld.

**Impact:** No cache-version bump needed ? rewrite output is not cached, and `jd._PROMPT_VERSION` / `rewrite._SCORE_PROMPT_VERSION` are untouched, so existing `output/*.requirements.json` and `*.scores.json` stay valid and the change takes effect on the next run. Full suite passes (187); no test asserted on the old prompt strings.

**Follow-up:** Effectiveness depends on `jd.extract` classifying these as `kind="soft"`. `kind` defaults to `"technical"`, so any soft skill it mislabels bypasses edit (3) and relies on the `_SYSTEM` rule alone. Worth checking `output/*.requirements.json` for "problem-solving skills" and "attention to detail" on the next run.

## 2026-07-27 ? Export filename = name + position

**What:** Downloads and CLI default output now use `<contact.name> Resume - <JD title>.docx` via `report.export_filename`. Web job dirs still store `tailored.docx` internally; only the `Content-Disposition` filename (and CLI `--out` default) changed.

**Why:** Owner wants application-ready names like `Vu Tuong Huan Tran Resume - Software Engineer Intern`.

**Impact:** Characters illegal on Windows (`<>:"/\|?*`) are replaced with spaces in the stem. Restart the API / Docker container to pick up the download-name change.

## 2026-07-27 ? Application-form experience expansion

**What:** Added a fourth LLM stage (`expand`) that produces expanded work-experience descriptions for online application paste fields. New module `expand.py`; hard facts (title, company, dates, location) are copied from `MasterResume` in code ? the model returns bullets only. Fabrication failures drop the bullet with a warning instead of raising. Web UI shows an `ExperienceCard` tile; CLI writes `<out>.expansion.md`.

**Why:** Application forms have a separate experience section that is not page-constrained like the one-pager. Expanding beyond resume bullets there is useful, but inventing tools/metrics is still unacceptable.

**Tradeoff:** Multi-source vocabulary (all bullets in an entry) lets the model attach a tool from bullet A to a claim in bullet B ? same relaxation `_merge_bullets` already accepts. Expansion is non-fatal so a dead backend cannot fail a successful `.docx` run. `hybrid` routes expand to Ollama (guard-protected, advisory); use `--expand-model` to override.

**Spec delta:** New purpose in `config.PURPOSES`; clean run is now four calls. Profile still followed (user chose not to hard-wire expand to Ollama under `claude`).

**Follow-up:** Live quality check under `--model ollama` / `hybrid` against a real posting; rebuild frontend (`npm run build`) or run Vite dev for the new tile in Docker.

## 2026-07-27 ? Tailor UI: full-width accordion, shared model list, tab persistence

**What:** (1) Application experience tile moved below the two-column grid at full container width; entries are an accordion (first open). (2) Rewrite/Expand model fields share one `localStorage`-backed list (`resumeTailor.modelSpecs`) via `useSyncExternalStore`. (3) `RunProvider` / `EditorProvider` sit above the router so JD text, settings, SSE, and editor drafts survive tab switches; JD + settings also survive reload.

**Why:** Narrow stacked entries made the page long; free-text model fields forced retyping; React Router unmounted pages and killed mid-run EventSource.

**Tradeoff:** Editor draft is memory-only across reloads (avoids shadowing disk). Persisted settings merge over `DEFAULT_SETTINGS` so older blobs missing newer fields stay valid.

**Impact:** Rebuild SPA (`npm run build` or `docker compose up --build`) to pick up the UI.

## 2026-07-31 ? LM Studio model profile

- **Decision:** Added `lmstudio` as a named `MODEL_PROFILES` entry (all four stages), with
  provider alias remapping to the existing `_OpenAICompatClient` via `LMSTUDIO_BASE_URL`
  (default `http://localhost:1234/v1`) and `LMSTUDIO_MODEL` (default `local-model`).
- **Why:** Owner wanted a UI option beside Claude / Ollama; the SPA already lists
  `sorted(MODEL_PROFILES)` from `/api/config`, so a profile is enough for the dropdown.
- **Tradeoff:** `hybrid` still uses Ollama for cheap stages, not LM Studio. Override rewrite
  with a Claude spec if quality suffers. `LMSTUDIO_MODEL` must match LM Studio?s exact
  loaded id ? the placeholder default will 404 until set in `.env`.
- **Spec delta:** New provider token `lmstudio` in `PROVIDERS`; Docker compose sets
  `LMSTUDIO_BASE_URL` to `host.docker.internal:1234` by default.
- **Follow-up:** Set `LMSTUDIO_MODEL` to the id shown in LM Studio, start its local server,
  pick **lmstudio** in the UI (rebuild SPA if the fallback list mattered before API load).

## 2026-07-31 ? Reachability error mentioned Ollama even for other URLs

- **Decision:** `_OpenAICompatClient._post` error text now names the resolved `base_url`
  and explains `:11434` = Ollama vs `:1234` = LM Studio, plus override/hybrid caveats.
- **Why:** Selecting `lmstudio` still hit `:11434` when Rewrite/Expand overrides or an
  `ollama`/`hybrid` profile were active; the old message always said ?If this is Ollama?,
  which hid that mismatch.
- **Impact:** No routing change ? clear Rewrite/Expand to ?Use profile default? and set
  Model profile to `lmstudio` for all four stages on LM Studio.

## 2026-07-31 ? Bare rewrite/expand overrides inherit lmstudio/ollama profile backend

- **Decision:** `resolve()` rebinds bare model ids (no `provider:` prefix) onto the
  profile stage?s `ollama`/`lmstudio` provider via `_bind_bare_override`.
- **Why:** UI showed profile `lmstudio` with Rewrite/Expand = `google/gemma-4-12b`;
  `parse_spec` inferred Ollama for bare names, so those stages hit `:11434` while
  extract/score used LM Studio.
- **Tradeoff:** On `hybrid`/`claude`, bare non-Claude overrides still default to Ollama
  (unchanged). Explicit `ollama:?` / `lmstudio:?` / `claude-?` still win.
- **Impact:** Rebuild/restart the API container to pick up the fix; no UI change required.

## 2026-07-31 ? LLM_TIMEOUT default 300 ? 900

- **Decision:** Raised default `LLM_TIMEOUT` to 900s and set the same default in
  `docker-compose.yml` (`LLM_TIMEOUT: ${LLM_TIMEOUT:-900}`).
- **Why:** LM Studio rewrite of ~14 bullets in one batched call was hitting the old
  5-minute httpx ceiling (`timed out` to `host.docker.internal:1234`).
- **Tradeoff:** A wedged local server holds the job worker longer before failing.
- **Impact:** Recreate the compose app to pick up the env default (or set `LLM_TIMEOUT`
  in `.env`).

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

## 2026-08-02 ? Stored tag vocabulary + chip editors

- **Decision:** `MasterResume.tag_vocabulary` is the shared tag option list (seeded from
  the 102 in-use tags). Editor uses `ChipListField` tiles for tags, skills, coursework,
  and project tech. Removing a vocab option confirms and strips it from every bullet.
- **Why:** Comma-parsed strings made add/remove awkward; a derived-only vocab could not
  express "remove an unused option."
- **Tradeoff:** Vocabulary can drift from tags in use if the user adds options they
  never assign; canonicalisation on save keeps aliases consistent.

## 2026-08-02 ? Settings regrouped + fill_target

- **Decision:** Run settings split into Output / Models / Rewriting quality / Advanced
  (collapsed). Added `fill_target` (0.80?0.95) through CLI `--fill-target`, web
  `JobSettings`, and `fit.fit(fill_target=?)`, defaulting to `UNDERFLOW_THRESHOLD`.
- **Why:** Flat checkbox list was hard to scan; fill target is the one fit constant with
  a documented running cost worth exposing.
- **Tradeoff:** Did not expose `SEMANTIC_WEIGHT` or calibration constants ? those are
  correctness levers, not preferences.

## 2026-08-01 ? Root README

- **Decision:** Added project-root `README.md` covering local venv install, CLI/web usage, Docker Compose, and Ollama / LM Studio profiles.
- **Why:** No root readme existed; `frontend/README.md` is only the Vite template stub. Setup and alternate-backend usage lived in `CLAUDE.md` / `.env.example`.
- **Tradeoff:** Kept it short and command-focused ? deferred architecture / fabrication-guard detail to `CLAUDE.md` and `docs/PLAN.md`.
- **Spec delta:** User asked for install, Docker, and Ollama/LM Studio guides only.

## 2026-08-01 ? Template tab (view + upload/rebuild)

- **Decision:** Third UI tab at `/template` with `GET/POST /api/template` and `GET /api/template/preview.pdf`. Upload replaces `templates/original_export.docx`, shells out to `scripts/build_template.py`, and regenerates a filled PDF preview under `output/template/`.
- **Why:** Matches the documented re-export workflow (copy baseline -> rebuild) without hand-editing the tagged template. Subprocess keeps `build_template.py` the sole producer of `main_template.docx` (CLAUDE.md hard rule) with no 770-line refactor.
- **Tradeoff:** Build failures surface stdout/stderr as a string log rather than structured section-missing errors. Fit constants stay module-level; after a template swap the UI flags `calibration.stale` and tells you to run `calibrate.py` + restart ? auto-calibrate from the web process is out of scope.
- **Spec delta:** Writes to `original_export.docx`. CLAUDE.md hard rule updated to allow
  the documented re-export path (CLI copy or the Template tab); hand-edits remain forbidden.
- **Follow-up:** Optionally extract build logic into `src/resume_tailor/template_build.py`
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
