# apply/ — the application funnel

Discover → screen → tailor → packet → fill. Full detail: `docs/REFERENCE.md` §3; decision
log: `docs/notes/apply-funnel.md` (grep it, never Read it whole). Live fills run in the
packaged desktop app, not this checkout (see the auto-memory note on the live fill runtime).

This file is mirrored byte-for-byte by `AGENTS.md` beside it: edit both together with the
same text (`tests/tooling/test_agent_docs.py` enforces it).

## Rules specific to this package

- **LLM calls only in `answer.py`, `model_resolver.py`, `hybrid_resolver.py`** — form-field
  labels/options and resume text in, plain text/JSON out. Everything else here is
  deterministic (`screen`, `eligibility`, `language_gate`, `skill_gaps`, `followup_due`, `report_html`, `mail_signals`, `tracker`, `salary`, `field_matcher` are pure, no LLM; `mail_imap` reads the
  mailbox over the network, read-only, no LLM).
- **Every click goes through `clicks.py`**; every automatic submit passes `submit_guard.py`.
- **Prepare uses Light task model routing; Fill runs under
  `config.pinned(ApplySettings.model_spec)`**, mirrored from the app-wide Heavy task model.
  Apply operations capture both roles at start; later settings edits affect new operations.
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
| `funnel/` — orchestration + state | `daily` (nightly run; + `daily_progress`, `daily_rows`, `daily_row_run`, `daily_batch`, `daily_retry`), `scheduler`, `operations` (Find/Prepare/Fill coordinator; several Prepare/Fill batches side by side; `fill_hosts` keeps one fill per Workday site), `op_slots` (fair slot pools shared by a kind's running batches; the process-wide Workday busy set), `come_back` (a stuck fill waits at the back of its batch and comes back once answered or on its timer), `preparation`, `cover_on_demand` (cover letters by `cover_letter_mode`: per field at Fill, written in the background while the step goes on, or all at Prepare), `answer_harvest` (answers typed on the page into questions the fill left → Answer book), `tab_close` (when a finished application's tab may close: strong evidence, untouched, a countdown with Keep open), `tab_events` (every tab closed, kept or found gone: logged and kept on the row), `fill_files` (read-only copies of the files one fill uploads), `packet` (+ `packet_models`, `packet_profile_fields`, `packet_fields`), `store` (+ `store_models`, `store_migrations`, `store_views`, `store_stats` (the Apply page's progress banner)), `attempts` (a read-only copy of what was sent, made in `store.set_status`), `outcomes` (events after sending; derived hiring stage), `review`, `attention`, `screen`, `eligibility`, `language_gate` (spoken languages a posting requires vs the profile's), `skill_gaps` (must-haves pursued postings asked for that the resume lacks), `sent_copy` (what was sent, read back for interview prep and follow-ups), `followup_due` (when a follow-up, thank-you or "no reply" mark is due), `report_html` (the offline HTML report of the funnel), `mail_signals` (a job email read for what happened and which application; no LLM), `mail_inbox` (email updates from Claude Desktop or the mailbox check, waiting for the student to accept; confident rejections closed automatically when switched on, with undo), `mail_imap` (the student's mailbox over IMAP, read-only: EXAMINE and `BODY.PEEK` only), `mail_sync` (the mailbox check: settings, schedule, what it reads since), `tracker` (the Tracker board: Done rows in columns by hiring stage; a move as events, with undo) |
| `discovery/` — finding postings | `sources` (README fetch + format detection; + `source_rows`, `source_headings`, `source_pipe_table`, `source_company_table`, `source_watchlists`, `source_status`), `source_catalog` (+ `catalog/sources.json`), `boards` (+ `watchlists/`), `job_apis`, `search_presets` (position x level x industry keyword-search presets), `ats_api`, `fetch_jd` (+ `fetch_browser`: the CDP read; never loads LinkedIn or Indeed), `identity`, `posting_location` (work type + country policy over a row's location; applied in `daily_batch.by_location`) |
| `answers/` — question answering | `questions` (one decision layer; + `question_options`: GPA-range, term, standing and year options), `answer` (LLM), `answer_facts` (safe profile facts for the Ask-the-AI panel), `answer_memory` (+ `answer_book`: the unified Answer book — page, custom and AI answers, learned types), `salary`, `phone`, `profile`, `notice` (notice-period units), `reference_data` (countries/states/self-ID option lists), `model_resolver` (LLM), `model_fallback` (Fill's Heavy -> Light route when Heavy is at its limit), `hybrid_resolver` (LLM; + `resolver_types`, `resolver_basis` (checks the basis each model answer cites), `page_blockers`, `widget_actions`) |
| `driver/` — the browser over CDP | `browser`, `browser_launch` (starts the chosen browser on demand), `cdp_relay` (the extension's relay: each task in a tab of its own), `controls`, `clicks`, `scanner` (+ `dom_scan.js`), `watchdog` (cuts a fill stuck past its deadline) |
| `forms/` — generic form filling | `fill` (CDP fill entrypoint + `_FillRun.run`, + `fill_diagnostics` for `fill.json`; its steps are layered classes over `fill_state._FillState`: `fill_entry`, `fill_wizard`, `fill_answers`, `fill_ats_steps`, `fill_finish`; module helpers in `fill_buttons`, `fill_page`, `fill_widgets`, `fill_outcomes`), `engine` (verified engine), `wizards`, `field_catalog`, `field_matcher` (+ `school_aliases.json`), `field_types`, `form_routes`, `form_guards`, `attachments`, `upload_replace` (a Continue fill swaps the app's own outdated upload), `submit_guard`, `filler.js`, `filler_readiness.js` |
| `ats/` — per-ATS flows | `workday_flow` (navigation; widgets in `workday_page`, `workday_dropdowns`, `workday_choices`, `workday_prompts`, `workday_skills`), `workday_auth`, `workday_repeaters` (+ `workday_rows`, `workday_dates`), `smartrecruiters_flow` (+ `smartrecruiters_page`, `smartrecruiters_location`, `smartrecruiters_entries`), `adapters`, `ats_hints`, `ats_fingerprint` (the platform a landed page belongs to) |

## Tests

`tests/apply/forms/test_fill.py`, `test_engine.py` (verified engine, fakes at `browser`/`scanner`/`controls`/`adapters`), `test_workday_*.py`, `test_smartrecruiters_flow.py`,
`test_apply_*.py`, `test_filler_dom.py` (runs `filler.js`), `tests/browser/` (real
browser, opt-in). Browser objects are faked at `browser` / `controls` seams.

## Resume quality review

`pipeline/resume_quality.py` persists final page fill, missing whole selected sections and the exported PDF's text read-back (`document/pdf_text_check.py`) to each run. `funnel/resume_review.py` binds acknowledgement to those measurements and both resume artifacts. Prepare may retain a usable flagged resume; Fill requires acknowledgement, and automatic submission checks it again. Unknown legacy quality requires Prepare again. Individual omitted entries and intentional exclusions do not require review. Additive acknowledgement fields live in the application JSON payload.
