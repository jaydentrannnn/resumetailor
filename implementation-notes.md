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
  active (default/Jayden) workspace via Word COM landed `chars_per_line=101,
  lines_per_page=55` — matching that workspace's existing LibreOffice measurement
  (101/55) exactly. `--workspace nina` landed `121/58` against her `soffice.json`'s
  `122/58` — a 1-char difference consistent with normal Word/LibreOffice glyph-metric
  variance, not a fluke. Both self-consistency checks passed; both runs'
  `verify_known_anchors` warned (expected — it checks Jayden-specific bullet ids and a
  39-bullet/3-page anchor against resumes that have since changed shape, nina's
  obviously so; this is the pre-existing soft-warning behavior, not a regression).
- **`tests/test_calibrate.py` added** (23 tests, no Word/LibreOffice): pins the
  collapsed-search guard, the plausibility band, `_static_heading_texts`'s three modes,
  and reproduces the custom-heading-text bug end to end against a stubbed renderer —
  proving both that the old (removed) hardcoded filter would have collapsed on it and
  that the fix converges correctly. Also pins that `run()` never calls
  `write_calibration` when the boundary check raises.

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
- **New `src/resume_tailor/template_verify.py`**, two checks:
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
- **`tests/test_template_verify.py` added** (13 tests): known-good builds (fixed mode
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
  `python scripts/build_template.py` (default/Jayden workspace, fixed mode) and
  `python scripts/build_template.py --workspace nina` (generic mode) both rebuild and
  verify clean with the mechanical tag-hoisting in place — confirms the refactor
  changed nothing about what either real template produces.
- **Full suite**: 608 passed, 1 deselected (the Phase 2 `owner`-marked test).
  Frontend (`tsc -b`, `oxlint`, `vitest`) unaffected — no frontend files touched.

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
before this entry was written, not after. `tests/test_template_analyze.py` gained 11
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
- **Tests**: 6 new backend tests in `tests/test_web.py` (field candidates present,
  remap changes section kind, unknown-sha 400, both preview endpoints via the
  established `render`/`to_pdf` monkeypatch seam, install clears the upload cache).
  Frontend: `tsc -b`, `oxlint`, `vitest run`, and `vite build` all clean — no new
  warnings beyond the pre-existing "only-export-components" fast-refresh warning every
  other state-context file in the codebase already carries. Full backend suite: 623
  passed, 1 deselected.

## 2026-08-05 - DOCX importer: an upload becomes content, not just layout

**What:** A Template-tab upload was, until now, a layout donor whose content was
discarded — a new user uploaded their resume and then retyped every bullet by hand into
the editor. New `src/resume_tailor/resume_import.py` (Phase 6) turns
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
- **Tests**: `tests/test_resume_import.py` (new, 13 tests) — full-fixture round trip
  through real JSON serialization (not just in-memory construction), entry-id collision
  safety across different section kinds sharing one flat namespace (matching `data.
  MasterResume._fill_entry_ids`'s own suffixing), the multi-experience-section fixture
  importing every section rather than just the first, and a dedicated regression test
  for each of the three bugs found above. `tests/test_render.py` gained 4 tests for
  `parse_month`/`parse_range`. `tests/test_propose.py` gained 6 tests for
  `propose_bullet_tags` (prompt contents, dropping an out-of-vocabulary tag, an
  explicit empty-list answer counting as "no tags" rather than being ignored, an
  out-of-range bullet index not crashing, LLM failure propagating normally). 4 new
  `tests/test_web.py` tests for the API route (draft returned with nothing written to
  disk — content and mtime both asserted unchanged, non-docx rejected, the suggest-tags
  pass filling in untagged bullets via a stubbed `propose.propose_bullet_tags`, and a
  stubbed failure there degrading to a warning instead of a 500).
- **Verified against a live server**: analyzed and imported a hand-built synthetic
  .docx via real HTTP against a running `uvicorn` instance (no test doubles),
  confirming `warnings`/`untagged_bullet_count`/`resume.contact`/`resume.sections`
  all arrive in the shape the frontend expects. Full backend suite: 649 passed, 1
  deselected. Frontend: `tsc -b`, `oxlint`, `vitest run`, `vite build` all clean.

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
  - **Real cost, not just a rename**: ~10 `tests/test_web.py` tests had quietly come
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
  deselected — 18 new tests in `tests/test_calibrate.py`, all against
  `check_render_anchors`/`measure_anchors`/`write_calibration`/`_load_previous_anchors`
  directly, no Word/LibreOffice required.

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
  Pinned directly in `tests/test_resume_import.py`. The user reconciles the duplicate by
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

## 2026-08-07 - The import wizard's "suggest tags" pass silently billed Anthropic regardless of the Ollama default

**What:** Checking "Suggest tags for untagged bullets" during import crashed with an
Anthropic 400 (`credit balance too low`), even though the project's documented default
backend is Ollama. Root cause: `config._ACTIVE` (what `backend_for` reads) is only ever
populated by `web/jobs.py`'s tailoring-job runner — the sole `config.resolve()` call site
under `src/`. Any LLM call reached from a route that is *not* a job (this one; also
`generate_library_proposals`) falls through to `backend_for`'s hard-coded
`resolve("claude")` fallback on a freshly started server, regardless of `JobSettings.model`'s
own `"ollama"` default. Separately, the route's own promise that a failed tag pass "must
never fail the import itself" was broken: the catch was `except (LLMError, RuntimeError)`,
but `anthropic.BadRequestError` is neither, so the SDK error escaped as an unhandled 500.

**Fix:** Added `config.pinned(profile)` — a `contextvars.ContextVar` overlay that
`backend_for` checks ahead of `_ACTIVE` and its claude default. A `ContextVar` rather than
a save/restore swap of `_ACTIVE` itself, specifically because a plain swap would still race
against a concurrently running tailoring job (FastAPI runs a sync route in a threadpool
with a *copied* context, so a `ContextVar` set inside one request is invisible elsewhere by
construction — no lock needed). `resolve()` was split at its `_ACTIVE.clear()` line into a
new `_backends_for(...)` (pure spec resolution) so `pinned()` reuses the exact same logic
without duplicating it. The import route now wraps its `propose.propose_bullet_tags` call
in `with config.pinned(config.ONE_OFF_PROFILE):` (`ONE_OFF_PROFILE` defaults to `"ollama"`,
overridable via env). Both non-job routes' exception handling was broadened from
`(LLMError, RuntimeError)` to bare `Exception`, since both already return a `warning=...`
response rather than raising and are meant to survive any backend failure.

**Scope (explicit user decision):** only this one call is pinned. `backend_for`'s global
`resolve("claude")` fallback is untouched — it still guards importable library functions
(`jd.extract`, `rewrite.score_table`) called by scripts/tests that never went through the
CLI, and changing it would silently reroute those callers. `generate_library_proposals`
keeps inheriting `_ACTIVE`/the claude fallback for its *routing*; only its error handling
changed. Making non-job routes follow the Run tab's saved Model setting was considered and
rejected as bigger than this fix warranted.

**Verified:** 7 new tests (`test_config.py`: `pinned()` overrides every purpose-keyed
accessor, never mutates `_ACTIVE`, restores cleanly, raises on a bad profile with no
residue; `test_web.py`: the import route's LLM call is observed running under
`origin="ollama"` even with `resolve("claude")` active, and a non-`RuntimeError` exception
in both non-job routes comes back as a warning, not a 500). Full suite: 712 passed (was
705), 1 deselected. Also verified live and unmocked against this machine's real `.env`
(which points `OLLAMA_BASE_URL` at Ollama Cloud with a working key): the pinned call
actually reached `gemma4:cloud` and tagged the bullet, never touching Anthropic; and with
`OLLAMA_BASE_URL` pointed at a closed port, the import still returned 200 with the
deterministic draft and a `"Tag suggestion pass failed: …"` warning instead of a 500.
