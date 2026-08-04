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

## 2026-08-01 ? Flexible single-column template import

- **Decision:** Added analyze ? confirm ? install for single-column paragraph DOCX
  resumes. Mapping lives in `templates/template_profile.json`. Build logic moved to
  `src/resume_tailor/template_build.py`; `scripts/build_template.py` is a thin CLI.
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

## 2026-08-01 ? Optional calibrate-after-install from the Template tab

- **Decision:** Multipart `calibrate=true` on `POST /api/template` runs
  `resume_tailor.calibrate.run()` after a successful install, then
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
  (`templates/library/.../VU TUONG HUAN TRAN Resume.docx`): project dates lost their
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
  `tests/test_template_build.py` / `tests/test_template_analyze.py`; full suite 272 passed.
- **Spec delta:** None — bug fix within the documented profile-mode contract
  (CLAUDE.md "Template generation").

## 2026-08-02 - Ollama model tag selectable from the UI, and Ollama Cloud without the daemon

- **What:** Two related changes aimed at handing this project to someone who does not
  want to install Ollama. (1) Documented that Ollama Cloud has a direct HTTPS endpoint
  (`https://ollama.com/v1`, OpenAI-compatible) reachable with only an `OLLAMA_API_KEY` —
  no `ollama serve`, no `ollama signin`, no local install. This needed **zero** code
  changes: `_OpenAICompatClient` already POSTs to `{OLLAMA_BASE_URL}/chat/completions`
  and already sends a bearer header when a key exists, so it is purely `.env`
  (`OLLAMA_BASE_URL=https://ollama.com/v1` + `OLLAMA_API_KEY=` + a tag with the local
  `:cloud` suffix dropped). Added to `README.md` and `.env.example`. (2) Wired
  `OLLAMA_MODEL` to the web UI's model selection: new `JobSettings.ollama_model`, new
  `config.ollama_stages(profile)`, and an "Ollama model" field in the Run page's Models
  fieldset that appears only for Ollama-routed profiles.
- **Why:** The two halves are the same complaint. Before this, which Ollama tag a run
  used was fixed at import time (`OLLAMA_MODEL` → `MODEL_PROFILES`), so the UI could pick
  the *profile* but not the *tag* — changing model meant editing `.env` and restarting the
  server, which is not something you hand a friend. The env var was also completely
  invisible in the UI, so there was no way to confirm which model a run would actually use.
- **Decision — stages, not a rewritten profile dict.** `ollama_stages` returns *which
  purposes* route to Ollama and `web/jobs.py` expands that into per-stage
  `resolve(overrides=...)` entries, rather than substituting the tag into
  `MODEL_PROFILES[profile]`. This is what keeps `hybrid` intact: its `rewrite` stage is
  Anthropic and must not be repointed at an Ollama tag. Reusing the existing `overrides`
  channel also means `_bind_bare_override` already handles binding a bare tag to the right
  provider, so no new parsing was needed.
- **Decision — order matters in the override dict.** The blanket Ollama tag is applied
  *first*, then `rewrite_model` / `expand_model` overwrite whichever stages they name.
  Reversed, the broad tag would silently clobber the narrower explicit choice. Pinned by
  `test_explicit_stage_override_beats_the_blanket_ollama_tag`.
- **Decision — the server tells the client which profiles are Ollama-routed.** Added
  `ConfigResponse.ollama_profiles` (plus `ollama_model` / `ollama_base_url` for the
  placeholder and help line) instead of hardcoding `["ollama", "hybrid"]` in the SPA, so
  `MODEL_PROFILES` can change without the UI going stale. The SPA keeps a name-check
  fallback only for the window while `/api/config` is still in flight.
- **Impact:** `ollama_model` is part of `JobSettings`, so it persists per profile via the
  existing `WorkspaceSettings` envelope with no migration — an absent field defaults to
  `None`, which reproduces today's behavior exactly. Also extracted a `_drain(c, job_id)`
  helper in `tests/test_web.py`: the two new routing tests assert on work the queue's
  *background thread* does, which without a wait is a race that passes on a fast machine.
  Folded the one pre-existing copy of that poll loop into it.
- **Not done:** `LMSTUDIO_MODEL` has the identical problem and the identical fix shape
  (the README currently works around it by telling users to set the rewrite/expand model
  ids by hand). Left out to keep this change surgical; `ollama_stages` would become
  `local_stages(profile, provider)` if it is picked up.
- **Spec delta:** None. `--model ollama:<tag>` from the CLI was always able to do this;
  the UI just had no equivalent.

## 2026-08-02 - Ollama becomes the default profile; `gemma4:cloud` stays the default tag

- **What:** Flipped the default backend from `claude` to `ollama` in both front doors —
  `tailor.py --model` (`default="ollama"`) and `JobSettings.model` / the SPA's
  `DEFAULT_SETTINGS.model`. `OLLAMA_MODEL` was already `gemma4:cloud` and is unchanged;
  the new UI field overrides it only when a value is actually entered (blank → `None` →
  no override reaches `config.resolve`).
- **Why:** Owner's call, and it matches what the tool is for: a fresh clone now runs with
  no Anthropic key at all, which is the difference between "install this" and "install
  this, then go buy API credit" for someone being handed the project.
- **Decision — the library fallback did NOT flip.** `config.resolve()`'s
  `profile or "claude"` and `backend_for`'s resolve-if-unresolved still say Claude. Those
  exist for importable functions (`jd.extract`, `rewrite.score_table`) that scripts and
  tests call without going through a CLI; flipping them would silently reroute callers
  that never picked a backend, which is a different (and worse) change than flipping a
  documented default. Both front doors pass their profile explicitly, so the two never
  disagree in practice — but this is deliberate asymmetry, not an oversight. Documented
  in CLAUDE.md so it does not get "fixed" later.
- **Decision — the SPA seeds from `DEFAULT_SETTINGS.model` rather than a second literal.**
  `runState.tsx` previously hardcoded `"claude"` three times in the fresh-profile seeding
  branch; it now reads `DEFAULT_SETTINGS.model`, so the default lives in exactly one place
  on the frontend and cannot drift from the constant right above it.
- **Correction to the previous entry:** it claimed direct Ollama Cloud calls need the
  local `:cloud` suffix dropped (`gemma4`, not `gemma4:cloud`). That came from Ollama's
  docs describing a `-cloud` *size* suffix (`gpt-oss:120b-cloud` → `gpt-oss:120b`) and I
  over-generalised it to this project's `gemma4:cloud`, where `cloud` is the tag itself.
  Per the owner, who is running it: the tag is `gemma4:cloud` either way. `README.md` and
  `.env.example` corrected — switching to the direct endpoint changes `OLLAMA_BASE_URL`
  and adds `OLLAMA_API_KEY`, and touches the model tag not at all.
- **Impact:** Two tests pinned the old default and were updated rather than deleted —
  `test_default_model_is_claude_for_every_stage` became
  `test_default_model_is_ollama_for_every_stage`, with a new
  `test_claude_profile_still_routes_every_stage_to_anthropic` keeping the old assertion
  alive under its explicit flag. Added
  `test_blank_ollama_model_leaves_the_env_default_in_place`, which is the case users
  actually depend on: a settings blob with no tag must resolve to `gemma4:cloud`, not send
  an empty model. Existing saved `settings.json` files are untouched — a profile that
  already stored `"model": "claude"` keeps it; only never-seeded profiles get the new
  default.

## 2026-08-02 - Gemini support: `Backend.origin` survives the openai remap

- **What:** Added a `gemini` provider/profile alongside `ollama`/`lmstudio`/`hybrid`, all
  through the existing `_OpenAICompatClient` path (`GEMINI_BASE_URL` defaults to Google's
  OpenAI-compatible endpoint, `GEMINI_MODEL` defaults to `gemini-3.5-flash`). The one real
  addition is a fifth field on the `Backend` `NamedTuple`, `origin: str = ""`, set in
  `config._backend` to the *pre-remap* provider word before `ollama`/`lmstudio`/`gemini`
  all collapse to `provider == "openai"`. Everything that needs to tell the three apart
  now reads `origin` instead: `config.api_key_for` (Gemini genuinely needs a key; the
  others don't), `config.structured_mode_for` (Gemini's shim enforces `json_schema`;
  Ollama Cloud silently ignores it — this was already the reason `LLM_STRUCTURED_MODE`
  defaulted to `"prompt"`, now made per-origin instead of global), `config.fingerprint`
  (see below), and the new `config.max_token_cap_for` (see the next entry).
- **Why:** The alternative — keep `provider == "gemini"` distinct and teach
  `llm.client_for` a set of "OpenAI-shaped" providers instead of one literal `"openai"` —
  is arguably cleaner in isolation, but buys nothing the `origin` field doesn't, while
  forcing every existing ollama/lmstudio backend's `fingerprint()` output to change
  (a bigger cache invalidation than the one taken below) and ~15 test assertions across
  `test_llm.py`/`test_expand.py`/`test_tailor_cli.py` to be rewritten for backends that
  didn't change behaviour. `origin` is additive with a default, so nothing that already
  worked had to change.
- **Decision — the missing-key check lives in `llm.client_for`, raises `LLMError`.** Not
  `RuntimeError`, and not folded into `api_key_for`. `tailor.py` catches bare
  `RuntimeError` for the score and facets stages and *degrades with a warning* — a missing
  Gemini key raised that way would silently fall back to keyword-only ranking and report
  success. `LLMError` hard-fails at the same call sites, which is the correct behaviour
  for "the run cannot proceed at all," and the check has to live in `llm.py` because
  that's where `LLMError` is defined.
- **Decision — the web preflight (`config.credential_gaps`) is pure and profile-shaped,
  not resolve-and-check.** It never calls `config.resolve()` and never touches the
  process-global `_ACTIVE` dict, deliberately: `POST /api/jobs` runs on a request thread
  while a different job may be mid-run on the worker thread, and `_ACTIVE` is the same
  process-wide state `set_active_workspace` warns about mutating outside the
  busy-then-lock ordering. A request-thread call that resolved would silently reroute the
  running job's backend out from under it. `create_job` in `web/app.py` calls it and
  returns 400 synchronously on a gap, so a missing key is caught before the job queue ever
  sees it — previously this only surfaced as an async `job.status == "failed"` once the
  worker got around to it.
- **Impact:** `Backend.label()` also changed, from `f"{provider}:{model}"` to
  `f"{origin or provider}:{model}"`, so the run report says `gemini:gemini-3.5-flash`
  (and, as a side effect, `ollama:gemma4:cloud` instead of the previously-misleading
  `openai:gemma4:cloud`). Verified no test pinned the old `label()` output before changing
  it. `config.ollama_stages(profile)` is now a one-line wrapper over the new
  `config.provider_stages(profile, provider)`, kept for the existing callers
  (`web/jobs.py`, `web/app.py`, `test_llm.py`) rather than renaming them all at once.

## 2026-08-02 - Adaptive token ceiling: escalate on truncation instead of failing outright

- **What:** `config.MAX_TOKENS` (32,000) is now only the *starting* request on the
  OpenAI-compatible path, not a hard ceiling. `llm._OpenAICompatClient.request` restructures
  around a loop: a response that truncates (`finish == "length"` and the JSON doesn't
  parse) doubles `max_tokens` and retries, up to `config.max_token_cap_for(purpose)` — a
  per-origin table (`PROVIDER_MAX_TOKENS`, Gemini at 65,536, Anthropic mirroring the
  existing 21,333 SDK limit for consistency even though that path never uses it) or a flat
  `LLM_MAX_TOKENS` env override that pins both the start and the cap. Bounded by
  `MAX_TOKEN_ESCALATIONS = 2` independent of the cap itself. A working ceiling is memoised
  in a module-level `llm._LEARNED_CEILING` dict keyed `(base_url, model)`, so later calls
  to the same model in one run start there instead of re-discovering it.
- **Why:** Gemini counts its internal thinking against the same output budget as the
  answer, so a fixed 32k ceiling could truncate outright on a stage that reasons for a
  while, with no recovery — previously an immediate hard `LLMError`. The alternative
  (raise `MAX_TOKENS` generously for everyone) either wastes the request on providers that
  don't need it or still isn't enough for a sufficiently verbose model; escalating on
  actual truncation adapts to what the model needed rather than guessing.
- **Decision — this cannot make a working run more expensive.** The escalation branch is
  only reachable from what was already a hard failure before this feature existed: a run
  that succeeds today issues the identical requests at the identical `max_tokens` it always
  did. This is the property that makes it safe to ship as the default rather than opt-in,
  and it is pinned by a test (`test_a_truncated_response_that_parses_is_not_escalated`)
  that a `finish == "length"` response which nonetheless *parses* successfully is returned
  as-is, not escalated — escalating that case would double the cost of a call that already
  worked.
- **Decision — the 400/422 `response_format` fallback became a graded ladder, not
  incidental to the ceiling work but exposed by thinking about Gemini's schema mode at the
  same time.** Previously a rejection dropped `response_format` entirely in one step. Once
  `structured_mode_for` defaults Gemini to `"schema"`, a rejection of the strict
  `_strictify`'d schema (every output model here is nested — `$defs`/`$ref` — a known gap
  area for OpenAI-compat shims) would have landed with *no* format constraint at all,
  strictly worse than the `"prompt"` default it started from. `llm._response_format_ladder`
  now walks `json_schema → json_object → none` in schema mode; `"prompt"` mode's ladder is
  `[json_object, none]`, identical to the old one-step behaviour, so
  `test_a_400_on_response_format_retries_without_it` needed no change.
- **Known blind spot, logged rather than fixed:** a `finish == "length"` response that
  parses successfully is not escalated (see above) even though it may represent a
  shorter-than-ideal answer (e.g. a truncated `bullets` list that still satisfies the
  schema). Not treated as a bug — the pipeline's own guards (fabrication guard, id
  reconciliation in `rewrite._retry_fabrications`, the fit loop) are where a short-but-valid
  result would actually surface, and escalating every truncated-but-valid response would
  break the cost-safety property above for a case that's usually fine.
- **Non-goal, explicitly:** the Anthropic path is untouched. `llm.client_for` returns the
  raw `anthropic.Anthropic` SDK client for that provider — it never enters
  `_OpenAICompatClient`, so none of this applies. Its ceiling is a client-side SDK refusal
  above 21,333 tokens for non-streaming requests; raising it means converting the call
  sites to streaming, a separate project, not a constant to tune here.
- **Impact:** `tests/test_llm.py`'s `client` fixture now clears `llm._LEARNED_CEILING`
  between cases and accepts `max_token_cap=` — necessary because the dict is module-global
  by design (a measurement, not run configuration, so it deliberately isn't threaded
  through `config._ACTIVE`), and without the clear a call-count assertion in one test could
  fail for a reason that has nothing to do with what that test checks.
  `test_truncation_is_reported_rather_than_retried` was renamed
  `..._when_already_at_the_cap` and kept (not deleted) — with no `max_token_cap` supplied,
  the cap collapses to the starting request and the hard failure still happens exactly as
  before, which is worth a test on its own.

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
    `python -m resume_tailor.data --validate` does not — so a bare `--validate` with no
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
- **Impact / tests added:** `tests/test_facets.py` (rename-guard + `_aligns` regressions,
  9 new), `tests/test_jd.py` (consensus voting + alias-fingerprint slug sensitivity, 9
  new), `tests/test_report.py` / `test_report_data.py` (`diagnose_gaps`, the facets-trap
  regression, 7 new), `tests/test_config.py` (new file — `canonical_tag` and
  `tag_alias_fingerprint` had no unit test before this), `tests/test_data.py` (new file —
  `data.py` had no test file before this), `tests/test_tailor_cli.py` /
  `tests/test_web.py` gained an autouse stub routing `extract_consensus` back to `extract`
  so existing wiring tests don't multiply their call counts or touch the real on-disk
  cache. Full suite: 377 collected, 361 passing, 16 pre-existing failures untouched
  (verified identical on `main` before this work — `test_facets`/`test_fit`/`test_merge`/
  `test_render`/`test_rewrite`, unrelated to anything here).

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
- **No other file changes needed.** `tests/test_fit.py`'s two assertions
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
- **Impact / tests added:** `tests/test_rewrite.py` gained an explicit equivalence test
  pinning that `experience_share=None, max_per_entry=None` reproduces the original
  floors+select algorithm bullet-for-bullet (not just matching size), plus tests for
  section-share reallocation, floor preservation at the `0.0`/`1.0` extremes, per-entry
  capping with spillover, cross-section spillover when one side can't fill its budget, and
  `selectable_total` itself. `tests/test_fit.py` gained a regression test proving growth
  stops at `growth_ceiling` (`iterations == 1`) instead of burning `MAX_GROW_ATTEMPTS` when
  a per-entry cap saturates the selection immediately — this is the bug fix in (2) above,
  pinned so it can't regress silently. `tests/test_tailor_cli.py`'s two `capture()` stubs
  that spell out `fit()`'s full keyword signature needed both new kwargs added (else a
  `TypeError`), plus two new flag-plumbing tests mirroring
  `test_fill_target_flag_reaches_the_fit_loop`. `tests/test_web.py`'s `fake_fit` stub and
  `seen_fit` assertion gained both keys, plus a settings round-trip test. Full suite after
  this change: the same 16 pre-existing failures as a clean `main` checkout, verified
  byte-identical by diffing the failing-test list before/after — none of them are
  connected to this work. Frontend `npm run lint` (no new warnings), `npm run test`
  (10/10), and `npm run build` all clean.
