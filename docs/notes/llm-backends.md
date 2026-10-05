# LLM backends — implementation notes

Covers: model profiles (ollama/lmstudio/gemini/claude), default models, token ceilings, timeouts, routing, cache-key origin.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

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

## 2026-07-27 ? Default Ollama model ? deepseek-v4-flash:cloud

**What:** Changed `config.OLLAMA_MODEL` default from `minimax-m3:cloud` to `deepseek-v4-flash:cloud`, and updated matching examples in `tailor.py`, `.env.example`, and `CLAUDE.md`.

**Why:** Owner requested the new default for the `ollama` / `hybrid` profiles.

**Impact:** `--model ollama` and `hybrid` extract/score now use `deepseek-v4-flash:cloud` unless `OLLAMA_MODEL` overrides it. Restart Docker / re-resolve config to pick up the change.

## 2026-07-27 ? Default Ollama model ? gemma4:cloud

**What:** Changed `config.OLLAMA_MODEL` default from `deepseek-v4-flash:cloud` to `gemma4:cloud`, and updated matching examples in `tailor.py`, `.env.example`, and `CLAUDE.md`.

**Why:** Owner requested the new default for the `ollama` / `hybrid` profiles.

**Impact:** `--model ollama` and `hybrid` extract/score now use `gemma4:cloud` unless `OLLAMA_MODEL` overrides it. Restart Docker / re-resolve config to pick up the change.

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
  helper in `tests/web/test_web.py`: the two new routing tests assert on work the queue's
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
- **Impact:** `tests/infra/test_llm.py`'s `client` fixture now clears `llm._LEARNED_CEILING`
  between cases and accepts `max_token_cap=` — necessary because the dict is module-global
  by design (a measurement, not run configuration, so it deliberately isn't threaded
  through `config._ACTIVE`), and without the clear a call-count assertion in one test could
  fail for a reason that has nothing to do with what that test checks.
  `test_truncation_is_reported_rather_than_retried` was renamed
  `..._when_already_at_the_cap` and kept (not deleted) — with no `max_token_cap` supplied,
  the cap collapses to the starting request and the hard failure still happens exactly as
  before, which is worth a test on its own.

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

## 2026-09-26 - `ollama-cloud` profile: switch between the daemon and Ollama Cloud in the UI

- **What:** New `ollama-cloud` entry in `config.MODEL_PROFILES`: every stage is
  `ollama:{OLLAMA_MODEL}@{OLLAMA_CLOUD_BASE_URL}` (default `https://ollama.com/v1`). It
  shows up as an "Ollama Cloud" radio in Settings → Models (the list is server-driven) and
  as an "Ollama Cloud" Autofill provider on the Apply page (`ApplySettings.model_provider`
  and `ApplyOperationRequest.model_provider`; `model_spec` turns it into the `@cloud` spec).
  Before this, reaching the direct API meant editing `OLLAMA_BASE_URL` and restarting —
  that route still works.
- **Key rule:** `config.requires_key(origin, base_url)` is the one rule shared by
  `credential_gaps` (setup pill, job-start 400) and `llm.client_for`/`async_client_for`:
  Gemini always, Ollama only when `config.is_ollama_cloud(base_url)`. Matched on the exact
  host of `OLLAMA_CLOUD_BASE_URL`, **not** "any non-local URL": a self-hosted Ollama on a
  LAN hostname (`gpu-box:11434`) is remote by `is_local_url` yet keyless, and must not
  start failing. The missing key is reported before the setup probe — ollama.com may
  answer `/models` without auth, which would have shown a green pill until the first 401.
  `credential_gaps` resolves each stage's address through `_default_base`, the same helper
  `_backend` now uses, so the address checked is the address called; this also catches the
  older `OLLAMA_BASE_URL=https://ollama.com/v1` route without a key.
- **Key order:** for Ollama Cloud, `api_key_env_for` returns `OLLAMA_API_KEY` before
  `LLM_API_KEY` (the latter may belong to another custom server). Local Ollama keeps the
  historical `LLM_API_KEY`-first order.
- **Why `fingerprint()` did not change:** the daemon forwards a `:cloud` tag to the same
  hosted model the direct API serves under the same tag, so their answers are
  interchangeable and a cache entry is valid for both. Folding the base URL in would have
  reset every cache (and split localhost vs `host.docker.internal`) for no correctness gain.
- **UI copy:** the "Ollama" card no longer claims "your resume never leaves it" — untrue for
  the default `:cloud` tag. The connection-test note for Ollama Cloud says it counts toward
  the Ollama plan rather than "a fraction of a cent".

## 2026-10-05 — measured pipeline token usage and timing

**What:** Every CLI/web run records versioned telemetry under its workspace output/telemetry directory; the usage_report module groups measured physical requests, cache events, and timings by routing, implementation version and extraction cache state.
**Why:** Retries and cached/reasoning token subsets cannot be inferred accurately from stage estimates; concurrent stage durations cannot be summed into total run time. Usage absent from a provider response stays unknown.
**Impact:** Metadata only is recorded, with atomic best-effort persistence on success/failure/cancellation. Skills copy/download/autofill signals measure observed consumption; the seven-day review window excludes incomplete observations and does not claim to observe manual reading. JD voting and skills defaults stay unchanged pending normal-run evidence and paired JD quality review.
