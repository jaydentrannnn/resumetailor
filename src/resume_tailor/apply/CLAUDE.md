# apply/ — the application funnel

Discover → screen → tailor → packet → fill. Full detail: `docs/REFERENCE.md` §3; decision
log: `docs/notes/apply-funnel.md` (grep it, never Read it whole). Live fills run in the
packaged desktop app, not this checkout (see the auto-memory note on the live fill runtime).

## Rules specific to this package

- **LLM calls only in `answer.py`, `model_resolver.py`, `hybrid_resolver.py`** — form-field
  labels/options and resume text in, plain text/JSON out. Everything else here is
  deterministic (`screen`, `eligibility`, `salary`, `field_matcher` are pure, no LLM).
- **Every click goes through `clicks.py`**; every automatic submit passes `submit_guard.py`.
- **Prepare uses the Tailor settings' model routing; Fill runs under
  `config.pinned(ApplySettings.model_spec)`** (the Apply page's "Autofill model").
- **Fill failures self-heal in code** (retry/recover) rather than producing a review item.
- **Dedupe is by ATS requisition** (`identity.canonical_key`); rows live in the workspace's
  `app.db` (`store.py`, via `storage/db.py`).
- **The extension/backend never fetch, click or crawl LinkedIn/Indeed** — capture only.
- A new form failure is reproduced as a captured page in `tests/fixtures/forms/` first.

## Module map

Six subpackages; module names are unique across them, so `grep -r "def name"` still finds
anything. Data files live beside the module that loads them (`resources.files` on the
subpackage).

| Subpackage | Modules |
|---|---|
| `funnel/` — orchestration + state | `daily` (nightly run), `scheduler`, `operations` (Find/Prepare/Fill coordinator), `preparation`, `packet`, `store`, `review`, `attention`, `screen`, `eligibility` |
| `discovery/` — finding postings | `sources` (README tables), `source_catalog` (+ `catalog/sources.json`), `boards` (+ `watchlists/`), `job_apis`, `ats_api`, `fetch_jd`, `identity` |
| `answers/` — question answering | `questions` (one decision layer), `answer` (LLM), `answer_memory`, `salary`, `phone`, `profile`, `model_resolver` (LLM), `hybrid_resolver` (LLM) |
| `driver/` — the browser over CDP | `browser`, `cdp_relay`, `controls`, `clicks`, `scanner` (+ `dom_scan.js`) |
| `forms/` — generic form filling | `fill` (CDP fill entrypoint + `_FillRun.run`; its steps are layered classes over `fill_state._FillState`: `fill_entry`, `fill_wizard`, `fill_answers`, `fill_ats_steps`, `fill_finish`; module helpers in `fill_buttons`, `fill_page`, `fill_widgets`, `fill_outcomes`), `engine` (verified engine), `wizards`, `field_catalog`, `field_matcher` (+ `school_aliases.json`), `field_types`, `form_routes`, `form_guards`, `attachments`, `submit_guard`, `filler.js`, `filler_readiness.js` |
| `ats/` — per-ATS flows | `workday_flow` (navigation; widgets in `workday_page`, `workday_dropdowns`, `workday_choices`, `workday_prompts`, `workday_skills`), `workday_auth`, `workday_repeaters`, `smartrecruiters_flow`, `adapters`, `ats_hints` |

## Tests

`tests/apply/forms/test_fill.py`, `test_workday_*.py`, `test_smartrecruiters_flow.py`,
`test_apply_*.py`, `test_filler_dom.py` (runs `filler.js`), `tests/browser/` (real
browser, opt-in). Browser objects are faked at `browser` / `controls` seams.
