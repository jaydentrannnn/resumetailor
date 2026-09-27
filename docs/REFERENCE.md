# ResumeTailor — subsystem reference

Detail relocated from `CLAUDE.md`, which stays a distilled core (invariant, hard rules,
commands, testing seams, gotcha index). Start there; come here for the full subsystem
picture. Like the decision log (`docs/notes/`), cross-check any number against the code — this
file describes the code as of its last update (2026-09-21).

Sections: CLI flags (§1), workspaces (§2), apply automation (§3), vocabulary libraries
(§4), template generation (§5), fit-loop tuning (§6), backend routing (§7), expanded
gotchas (§8), sections-as-lists (§9), hard rules in full (§10), testing conventions in
full (§11).

---

## 1. CLI flags (`tailor.py`)

| Flag | Effect |
|---|---|
| `--jd` | Job description path (any path; `data/jd/*.txt` by convention, gitignored) |
| `--out`, `--pages`, `--template` | Output path, page target, template override |
| `--experience`, `--projects` | Entry caps per section |
| `--no-cache` | Force re-extraction |
| `--no-semantic` | Tag-overlap-only ranking (`SEMANTIC_WEIGHT = 0.0`) — the control for an A/B on a surprising ranking |
| `--no-widow-repair` / `--no-verb-repair` | Disable the corresponding `_polish` repair |
| `--merge` | Opt-in: propose merges only after a measured page overflow |
| `--no-expand` | Skip application-form experience expansion |
| `--no-skills` | Skip tailored skills-list stage |
| `--no-facets` | Skip project-tech/coursework selection |
| `--fill-target` | Overrides `UNDERFLOW_THRESHOLD` for one run |
| `--initial-bullet-share` | Caps the *first* draft's bullet count, default 1.0 — pair with a lower `--fill-target` to actually end sparser (at the default threshold it mostly buys extra rewrite rounds for the same final page) |
| `--experience-bullet-share` | Fraction of selected bullets given to experience vs projects; unweighted default is one flat pool ranked by relevance |
| `--max-bullets-per-entry` | Per-entry ceiling; default uncapped — a capped entry's forfeited slot spills to the next-best bullet elsewhere |
| `--no-gpa`, `--no-coursework` | Include/exclude controls (`include.py`) |
| `--contact-fields email,phone,linkedin` | Which contact fields render |
| `--exclude <id>` | Repeatable; matches any entry id in any experience/project section — one flat namespace |

Include/exclude is applied once, after scoring and before facets. An excluded entry still
appears in the application-form expansion output; only the tailored `.docx` omits it.

**The CLI is entirely flag-driven, on purpose** — every behavior above traces to an
explicit `--flag`, so a scripted/looped bulk-apply run behaves the same regardless of what
a profile's web UI saved. `model_name`, `rewrite_style`, `expand_style`, `cover_style` are
the sole exceptions: `tailor.py` picks those four up from the active profile's saved
`settings.json` (in `main`, right after `workspace.bootstrap`), so a preference set once in
the web UI doesn't need retyping as a flag on every run. No other saved setting (`pages`,
`experience`, `include`, `fill_target`, …) is read from `settings.json` here — those always
come from argparse defaults.

`tailor.py`, `build_template.py`, and `calibrate.py` all take `--workspace <id>` to run
against a non-active profile for that invocation only; it never writes the registry.
Pre-profiles (no `data/workspaces/`), the legacy paths are `templates\original_export.docx`
and no `--workspace` flag.

### Model selection

```powershell
python tailor.py --jd jd.txt                     # ollama (default — no Anthropic key needed)
python tailor.py --jd jd.txt --model claude      # all stages on Claude
python tailor.py --jd jd.txt --model gemini      # all stages on Gemini (needs GEMINI_API_KEY)
python tailor.py --jd jd.txt --model hybrid      # rank/expand/facets/skills on Ollama, rewrite on Claude
python tailor.py --jd jd.txt --model ollama --rewrite-model claude-sonnet-5
python tailor.py --jd jd.txt --expand-model ollama   # override expand only
python tailor.py --jd jd.txt --skills-model ollama   # override skills selection only
python tailor.py --jd jd.txt --effort medium     # per-stage default is low/low/medium/medium/low
```

`--model` takes a profile (`config.MODEL_PROFILES`: `claude`, `ollama`, `ollama-cloud`,
`lmstudio`, `gemini`, `hybrid`; `ollama-cloud` is `ollama` pinned to
`OLLAMA_CLOUD_BASE_URL` and needs `OLLAMA_API_KEY`) or a spec `provider:model[@base_url]` — splits on the **first** colon
only, so `ollama:gemma4:cloud` keeps the second colon in the model name. `ollama` and
`lmstudio` are both the OpenAI-compatible provider pointed at different base URLs
(`OLLAMA_BASE_URL` / `LMSTUDIO_BASE_URL`) — the same path reaches local Ollama, Ollama
Cloud, vLLM, Groq, OpenRouter, LM Studio, GLM, Kimi. `gemini` is the same shape but
genuinely requires a credential (`GEMINI_API_KEY`/`GOOGLE_API_KEY`/`LLM_API_KEY`); the web
layer's `config.credential_gaps` rejects a job synchronously at `POST /api/jobs` if it's
missing. `Backend.origin` (`config.py`) is what lets credentials, structured-output mode,
and the token-cap table still distinguish ollama/lmstudio/gemini even though they share
`provider == "openai"`.

To regenerate the template from a **new** export, replace the baseline first —
`build_template.py` reads only `config.BASELINE_TEMPLATE_PATH` and will otherwise silently
rebuild from the stale copy:

```powershell
copy "data\YOUR RESUME.docx" templates\workspaces\<id>\original_export.docx
python scripts\build_template.py --workspace <id>
```

After any template change, re-run `python scripts/calibrate.py` and restart the server.

---

## 2. Profiles (workspaces)

The web UI can hold more than one **profile** — a full master resume + template +
calibration + settings, switched together via the header dropdown. Internally called a
**workspace** (`profile` was already taken by `TemplateProfile` and `config.MODEL_PROFILES`).
UI label stays "Profile"; code (`workspace.py`, `config.set_active_workspace`,
`/api/workspaces`) says `workspace`.

Each workspace is a directory tree replicated under the existing storage roots:

```
data/workspaces/index.json                 registry: {active_id, entries:[...]}
data/workspaces/<id>/master_resume.json
data/workspaces/<id>/settings.json
data/workspaces/<id>/libraries.json        vocabulary-library selection — see §4
data/workspaces/<id>/calibration/<backend>.json
templates/workspaces/<id>/{original_export.docx, main_template.docx, template_profile.json}
templates/workspaces/<id>/library/ , backups/
output/workspaces/<id>/{cache/, jobs/<job_id>/, template/}
```

Ids are slugs derived from the label, not opaque — browsed by hand. **Rename never moves
the directory**; the id is fixed at creation. Template library cap is 20 entries, per
workspace.

**`config.py` rebinds, it doesn't parametrise.** `set_active_workspace()` reassigns
fourteen module globals (`DATA_DIR`, `MASTER_RESUME_PATH`, `APPLICATIONS_PATH`,
`APPLICANT_PROFILE_PATH`, `APPLICATIONS_OUTPUT_DIR`, …) then calls `reload_calibration()` —
safe because every path reference goes through `config.X` and resolves on next read. **Not**
safe to call concurrently with a running job, daily apply funnel, or template-tab operation;
every mutating workspace route holds `get_queue().busy()` then `template_ops.LOCK`, in that
order (and 409s while `apply.daily.daily_busy()`).

Tailoring jobs now run concurrently up to `JobSettings.max_concurrent_jobs` (default 2,
range 1–4). Each job carries a `RunContext` with its workspace paths, backend routing,
calibration, vocabulary, and style; worker threads in JD voting and daily processing
copy that context explicitly. `get_queue().busy()` remains true while any job is queued
or running, so workspace mutations still wait. `convert.convert()` serializes both Word
and LibreOffice PDF conversion with a process-wide lock: Word COM needs exclusive use,
and LibreOffice's shared profile is also not safe for overlapping conversions.

`workspace.bootstrap()` resolves and activates a workspace on every process start.
`tailor.py`/`build_template.py`/`calibrate.py` each take a `--workspace <id>` override that
applies to that invocation only and never writes the registry. First boot with no registry
**migrates** the legacy single-slot layout into a `default` workspace by copying, never
moving. `workspace.ensure_master_resume()` writes a placeholder when a workspace has no
master resume — create-if-absent only, called from `create()`/`activate()`/`bootstrap()`.

**Single process is a hard requirement** — `config._ACTIVE` plus the path globals are
process-wide; don't add `--workers` to the Dockerfile CMD or the dev command.

### Desktop app (Tauri + bundled server)

`desktop/` holds the Tauri v2 shell; `desktop/sidecar/resumetailor.spec` freezes the server
(`python -m resume_tailor.desktop_main`) with PyInstaller. Contract: the server prints
`READY <port> <token>` once listening; the shell opens `http://127.0.0.1:<port>/?t=<token>`.
Storage defaults to the per-user app-data folder (`desktop_main.app_data_dir`); any
`RESUME_TAILOR_*_DIR` already set wins. `--exit-with-stdin` stops the server when its parent
goes away. Build locally: `npm run build` in `frontend/`, then `pyinstaller
desktop/sidecar/resumetailor.spec --noconfirm --distpath desktop/sidecar/dist`, then in
`desktop/`: `npx @tauri-apps/cli@2 icon app-icon.svg` and `npx @tauri-apps/cli@2 build`.
Installers: `.github/workflows/release.yml` on a `v*` tag (draft release, not
code-signed; updater bundles signed with `TAURI_SIGNING_PRIVATE_KEY`, plus `latest.json`
from `scripts/release_manifest.py`). **In-app updates** (`desktop/src-tauri/src/update.rs`,
`desktop_update.py`, `web/routes/update.py`): the SPA has no Tauri IPC, so the server
relays over the sidecar's pipes: `SHELL check|download|apply` on its stdout, `UPDATE
<json>` events on its stdin (`--app-version` gives it the installed version). `apply` is
sent only when the job queue and Apply operations are idle, after a zip of data +
templates to `OUTPUT_ROOT/backups/`. The feed is `releases/latest/download/latest.json`
(drafts are invisible, so publishing ships); `RESUMETAILOR_UPDATE_ENDPOINT` overrides it
for testing (the plugin still rejects plain `http://` unless the build sets
`plugins.updater.dangerousInsecureTransportProtocol`). Details:
`docs/notes/web-ui-and-mcp.md` "Desktop packaging". Owner walkthrough (build, install,
update, move data): `docs/GUIDE.md`.

---

## 3. Application automation

`src/resume_tailor/apply/` owns the daily discover → screen → tailor → packet → fill
funnel. Prepare tailors and screens with the **Tailor tab's** model settings (profile,
model name, effort, per-stage overrides): `daily._job_settings` leaves them untouched, and
the screening `jd.extract_consensus` call is pinned to the same `web.jobs.model_routing` with
the same `extract_runs`, so the tailor job's own extraction is a cache hit.
`ApplySettings.model_provider`/`model_name` (default `ollama`/`nemotron-3-super:cloud`, the
Apply page's "Autofill model") covers only Fill's LLM calls — prepared long answers and
hybrid/model resolver assistance — which run under `config.pinned(settings.model_spec)`.

Form filling injects `filler.js` into the user's host browser (Edge recommended — see
README; Chrome refuses remote debugging while another Chrome window is already running,
which Edge sidesteps as a separate process) over CDP (`CHROME_CDP_URL`, default
`http://host.docker.internal:9222` — name kept for backward compatibility, value is
browser-agnostic) — no Chromium in the Docker image.

**Browser extension (P4-X).** The unpacked MV3 extension pairs through Settings → Browser:
the app issues one six-digit, 120-second code at a time, which the extension exchanges
for a token. The token is sent as `X-RT-Extension` only to the dedicated
`/api/extension/*` lane; the normal app session still protects pairing management.
Revocation invalidates that browser token. The extension reads a job page only when the
user invokes capture, then the server stores and deduplicates its JD for later Prepare.
Opening the popup sends the URL for lookup but not the JD. LinkedIn, Indeed, Handshake,
and Workday are assist-only; extension Prepare/Fill always use `auto_submit=false`.
The extension can automatically start Fill after successful preparation. CDP remains
the default Fill mode. The X3 relay passed a synthetic end-to-end Greenhouse Fill,
file upload, cross-origin frame evaluation, wait, and tab-detach failure checks in
Edge. With `BROWSER_MODE=extension`, the local relay CDP URL, and an explicitly attached
tab, Fill can drive that tab through `chrome.debugger`; closing it or opening DevTools
marks Fill failed. The relay is local-only and requires manual startup and attachment.
Cross-origin iCIMS iframe text needs selection capture or opening
the iframe in its own tab.

Discovery is multi-source (`ApplySettings.sources`): SimplifyJobs Summer2027-Internships,
New-Grad-Positions, and speedyapply 2027-SWE-College-Jobs (pipe tables). Dedupe is by **ATS
requisition** (`identity.canonical_key`); same-company same-role across locations share a
`group_key` and reuse one tailor run. Application rows (the `applications` table of the
workspace's `app.db`) are keyed by canonical key, with `source_refs` listing every sighting.
A company watchlist (`kind="ats_board"`, `apply/boards.py`) reads public Greenhouse, Lever,
Ashby and SmartRecruiters boards directly. It keeps titles matching `include` and none of
`exclude`, in `locations`, and applies its own `max_age_days` (default 7), or the funnel-wide
limit when that is longer (a Find's one-off `max_age_days` replaces the funnel-wide limit
for that search only). Its rows use the
ATS's own job URL, so they merge with Simplify sightings of the same job. A wrong board name
is one run error, not a failed source. `POST /api/apply/boards/resolve` checks a board
before the settings add it. `apply/watchlists/*.json` are suggestions, checked the same way.
A keyword search (`kind="job_search"`, `apply/job_apis.py`) queries Adzuna or USAJobs by
`query`/`location` (`country` for Adzuna) across any industry, then applies the same
`include`/`exclude`/`locations` filters (`sources.matches_filters`) and its own
`max_age_days` (default 14). Paging stops at `MAX_PAGES` with a polite delay between pages.
Keys (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `USAJOBS_API_KEY`, `USAJOBS_EMAIL`) are
`config.SAVABLE_CREDENTIALS`, never `settings.json`; a missing key is one run error for that
source, and error text is redacted because Adzuna carries its keys in the query string.

The Apply tables sort by **Posted** (`store.posted_date`): the source's own publication date
when it states one (`SourceRow.posted_at`: Greenhouse `first_published`, Lever `createdAt`,
Ashby `publishedAt`, SmartRecruiters `releasedDate`, Workday `postedOn`, Adzuna `created`,
USAJobs `PublicationStartDate`), else the date found minus the age the source reported,
else (extension captures, `age_unknown`) the date found, shown as `~date`. The age filter
still reads `updated_at`, so a repost stays fresh; existing rows need no migration.

Eligibility (`eligibility.py`) hard-rejects graduate-degree-only postings (master's/PhD
without a bachelor's alternative), senior titles, and high year floors — before
`jd.extract_consensus`. Ambiguous signals become `eligibility_flags`, never silent drops.
A manager word in an intern or junior title ("Product Manager Intern", "Associate Product
Manager") is not seniority; only unambiguous words (Senior, Director, VP, …) reject those.
Business program titles ("Summer Analyst", rotational or development programs) count as
early career, so a years floor in their JD is a flag, not a reject. A bare "Analyst" or
"Associate" does not count as early career.
The work-restriction block patterns (`screen.check_blocks`: citizenship, security clearance,
user extras) run in the same no-LLM stage (`daily.prefilter_screen`) and record a named
reason (`citizenship_required` / `clearance_required`) plus the matching JD sentence in
`ScreenResult.evidence`. After extraction, `screen()` rejects on seniority only — an
intern/new-grad/entry title overrides the model's label (`seniority_mismatch` flag).
`screen.screen_label` turns any stored reason (legacy regex-source strings included) into
the 2–3 word `screen_label` the Status column shows. Every screened-out row with saved JD
text offers "Re-check eligibility", which re-runs `prefilter_screen` with the stored
seniority, so rule fixes reach old rows without a model call.
`ats_api.py` tries Greenhouse/Lever/SmartRecruiters/Ashby JSON first (`method="api"`); README
fetches use ETag caching under `applications/readme_cache/`.

Per-workspace state:

- `data/workspaces/<id>/app.db` — SQLite: funnel records (`applications`), master-resume
  version history (`resume_versions`). A pre-SQLite `applications.json` is imported once
  and renamed `applications.json.migrated` (original also copied to `backup-pre-sqlite-*/`)
- `data/workspaces/<id>/applicant_profile.json` — form answers (work auth, address, EEO)
- `output/workspaces/<id>/applications/` — JD text, fill screenshots, nightly logs,
  `url_resolve_cache.json`, `readme_cache/`

The SPA starts persistent `find`, `prepare`, and `fill` operations through
`apply/operations.py`; operation state and a bounded event history live in
`output/.../applications/operations.json`, so progress survives page refreshes. Fill verifies
required fields and each intended attachment before submission. Auto-submit additionally
requires `auto_submit_enabled`, ATS membership in `auto_submit_ats`, and remaining room under
`auto_submit_max_per_run`. Workday is never auto-submitted (`fill.decide_submit_action`
returns `awaiting_review` for it whatever the settings). Right before the click,
`apply/submit_guard.check` can still hold the form for review with a plain note. It holds when
the header's "Pause all automation" switch is on (`<DATA_ROOT>/automation.json`, shared by every
profile). It holds when the rolling 24-hour caps are reached (`auto_submit_max_per_day`
default 25, `auto_submit_max_per_company_per_day` default 2), counted from `auto_submit`
status notes. It also holds a possible duplicate: the row was already submitted, or a row in
the same group or with the same company and role was submitted in the last 30 days.
`submit_guard.pace` spaces automatic submits 20–90 s apart, one at a time. The nightly batch
fills up to `ApplySettings.max_parallel_fills` (default 2, range 1–4) applications at once,
each in its own tab over its own CDP connection (Playwright sync objects are thread-bound);
file uploads share `browser.UPLOAD_LOCK`, submits still pass through `pace`, the batch holds
`operations.batch_browser_owner()` so a user operation cannot share the browser, and extension
mode (one relayed tab) always runs one at a time. Each submit writes
`submit-<UTC stamp>/{before,after}.{json,png}` next to `fill.json`, shown on the detail page's
Timeline. `fill.confirmation_markers` adds per-ATS confirmation selectors, phrases and URL
fragments. The pause switch also holds the operation worker between applications, stops the
nightly batch submit, and makes the scheduler wait. The Apply page sends
`blocker_mode="continue"` for Fill selected; older API callers may still request pause.
Fill results persist a CDP tab target ID for same-tab Continue and Review actions, and
Workday verification returns a handoff instead of waiting in the worker. Applicant-profile API
responses redact the stored Workday password, and a blank password on update preserves the
existing secret.

Selected Apply table Fill actions use the same `max_parallel_fills` limit, except extension
mode and "Pause on blocker" use one worker. Selected Prepare actions use the Tailor page's
`max_concurrent_jobs` limit, while rows from the same posting group prepare in order.
The operation records each active row in `in_flight`; legacy current-item fields continue
to show the most recently active row. Pause holds new work until resumed, and automatic
submits reserve a run-limit slot before a fill starts.

**Workday (legacy engine).** `apply/workday_flow.py` recognises each Workday screen from its
visible `data-automation-id` markers (`classify` is pure; captured screens live in
`tests/fixtures/workday/screens.json`) and waits for screen changes instead of sleeping:
posting (`adventureButton`, or `continueButton` for a saved draft) → Start dialog (only
`applyManually` is ever clicked) → Create Account / Sign In → apply steps (progress bar).
`workday_auth.handle_workday_auth` treats an existing session (`utilityButtonAccountTasksMenu`)
as signed in, waits for an auth form to be fully painted (`wait_for_auth_form_ready`: inputs,
submit, and the `click_filter` overlay — which paints last and alone carries the click
handler — stable on the submit) before filling, clicks auth submits through that overlay, and
re-clicks once only when the first click sent no request and changed nothing (a click that
reached Workday is never repeated: a second wrong-password attempt counts toward lockout).
Staying on the form with no error is `no_response`, not a rejected password; never fills the
`beecatcher` honeypot, ticks the Create Account terms box (`createAccountCheckbox`, account
creation only — a box that will not report checked is `terms_needed`), and hands over (never
guesses) when an account exists under an unknown password; each outcome has readable text in
`AUTH_HANDOFF`. Sign In comes first whenever an account could hold the password (a site the
vault has used, `created`/`signed_in`, or the applicant's profile password) and gets exactly one
attempt. A rejection on a site the tool never used falls through to Create Account, because
Workday says "wrong email or password" for a missing account too. There, "already exists"
hands over as `account_exists_other_password` without a second attempt. With no profile
password, a new site creates straight away with a generated password. A rejection ends the
submit wait as soon as the form shows its error. A successful sign-in marks the site
`signed_in`. `classify` calls a progress-bar shell `apply_form` only once a footer or a
`formField-*` shows; below ~800px the bar has no step names, and a bare shell is the
Create Account step still loading. Per step, `fill.py` waits for the step to render stably, then fills Workday
listbox dropdowns (`select_listbox`, Country first since it re-renders the form), Yes/No
radios (previous-employer answered from the resume's own employers), empty prompts whose
label maps to a profile fact ("How Did You Hear About Us?", `fill_prompts`), the Skills
prompt (`fill_skills`: the packet's tailored `skills` typed one search at a time; an option
naming the skill exactly or by its abbreviation — `field_matcher.match_skill_option`, RAG →
"Retrieval-Augmented Generation (RAG)" — is committed and verified by a new chip; the rest go
to ONE `hybrid_resolver.choose_skill_options` call with the options each search showed, and
a pick outside those options is dropped; unmatched skills are one review line), the
phone-code prompt, and on My Experience (only the sections the tenant actually shows) the `workExperience-N--*` / `education-N--*` rows
(`workday_repeaters.py`: exact or partial-agreeing row reuse, split MM/YYYY dates via their
display divs, existing answers never replaced; the school control is `schoolName` or a
`school` prompt, and each row field is attempted on its own so one failure names only that
field), plus `language-N--*` rows from the profile's Languages list (language, the
fluent checkbox, and each proficiency listbox by its label; levels match by rank via
`field_matcher.level_rank`, never upward). Self-identification answers match the form's long
wording (`field_matcher.eeo_pattern`: "No" → "No, I do not have a disability…", "I am not a
protected veteran"; "decline" is sent as a literal sentinel that picks the decline option and
is never typed); checkbox groups (the CC-305 disability form) go through
`workday_flow.fill_choice_checkboxes`, and the Self Identify step signs Name with the full
name and Date with today, leaving Employee ID blank (`fill_self_identify`). **Blank profile
facts are reported, never skipped silently**: a question whose label maps to a profile field
the profile leaves blank is recorded (filler.js leftover reason "Profile field is blank";
`workday_flow.fill_dropdowns`/`fill_radios` `blank=`; the engine's `unsupported_fact`) and
grouped by `packet.missing_profile` into `FillResult.missing_profile`. `packet.PROFILE_FIELDS`
is the one registry of profile-backed keys (label, Profile page section, `common`);
`GET/PUT /api/applicant-profile` return `gaps` (common blanks plus any a stored fill met,
most-met first) for the Profile page banner and the Applications notice. `packet.DEFAULTS`
fills harmless blanks only (phone device type → "Mobile"); legal and self-identification
answers never get one. **Eligibility questions come from the profile**:
`ats_hints.AUTHORIZED_TO_WORK` (authorized/permitted/eligible to work, "can you provide proof
of eligibility") and `ats_hints.OVER_18` (never "under 18") sit before the Country rule, so
"…work in the country where this job is located" is not the Country field; `field_catalog`
reuses them. A follow-up revealed by an answer is picked up by `fill_dropdowns`' rescan, or,
after a model answer, by `resolve_step_blockers`' reveal rounds (≤2, only the new controls).
`packet.authorization_mismatch` withholds "Authorized to work" when the posting's location
clearly names another country than the profile's authorization country. Required Workday application consent/accuracy boxes are ticked and verified
(`form_routes.accept_workday_sync`); optional marketing consent is untouched. Workday's
"Something went wrong ... Error Code: VPS|" page (`workday_flow.recover_site_error`) is
refreshed up to 3 times per occurrence, 6 per fill, wherever it appears (entering the form,
after sign-in, at each step, after Save and Continue) before handoff. **The Review step is never
advanced**: its footer Submit shares Next's `pageFooterNextButton` id, so the step loop stops
on `is_review_step` and `_find_advance_button` rejects any submit-worded button.

**Searchable choices.** `field_matcher.search_terms` orders prompt searches (a school also
by campus: "University of California - Irvine" → "Irvine"); `closest_option` accepts
exact/alias, else — for school/major/how_heard/degree only — the one option containing every
word of the answer (ties go to review). A Workday prompt whose Enter commits a single result
by itself is verified by its chip. "How did you hear" falls back to "Other"
(`fallback_values`), and a "please specify" field right after it gets `how_heard_detail`.
Degrees: `field_matcher.degree_of` reads "BS"/"B.S."/"BSc"/"Bachelor of Science (B.S)" as one
named degree and "Bachelor's Degree" as the bare level. The packet's `degree_name` (the one
named degree in the resume rows at the first entry's level) is tried before `degree_level`
(`choice_values`); it picks its own name or abbreviation, else the bare-level option, and a
bare level never picks a named degree. `filler.js` mirrors this for native selects.
Country is re-checked just before a step advances (a saved "Vietnam" re-labels the form);
the phone code must name the whole region (`_phone_option`), not merely contain it.

**Label reading (`filler.js`).** Beyond `for`/aria/Workday labels, a control's question is
the bare text of the ancestors holding only that control (Epic Games: placeholder "Enter",
no label element), minus widget, validation and live-region text. Field `name`s are read
with separators as spaces (`questions.first_name`); `educations[N].start_date.year|month`
are education dates; React Select inputs without `role=combobox` are dropdowns; a long
question never takes a short-field key (school, city, …). Workday's generic "Upload a file"
input reports its hint key and section heading, so it is attached as the resume.

**Salary and revealed fields.** Salary questions are answered deterministically (no LLM) by
`apply/salary.py`: `min(posted top, applicant top)` in the posting's unit, hourly ↔ yearly at
2,080 h. Posted pay comes from the listing's salary column, else the saved JD text; with none,
the applicant's top (hourly for intern/co-op titles, yearly otherwise) unless the question
names a unit. The range is `ApplicantProfile.salary_{hourly,yearly}_{min,max}`, seeded once
from the free-text `salary_expectation`; empty maximums leave salary for the applicant. The
fill runner adds `salary_expectation`/`salary_hourly`/`salary_yearly` (and `_number` forms
for number inputs) to the packet fields. `filler.js` reads a Workday question's label from a
multi-id `aria-labelledby` or its `formField-*` container, ticks a lone yes/no checkbox ("I have
a preferred name", `has_preferred_name`), and reports `revealed`, after which `fill.py` scans
the frame once more so the fields the tick revealed are filled.

**Applications page.** Rows in `store.REVIEW_STATUSES` (awaiting review/verification, fill
failed, submit unconfirmed) sit in a separate "Needs your review" table (`GET
/api/applications?group=review`, the working table uses `group=working`), each with
`review_summary` (the first field waiting on the applicant, or the kind of hand-off). Sorting is
over the whole filtered list before paging; ties fall back to newest-discovered then company,
and Status sorts in pipeline order. The page's 2s poll refreshes the tables while an operation
runs, while a visible row is `tailoring`/`filling`, and once whenever the latest operation or its
state changes (`lib/applyPoll.ts`). All three tables collapse (URL params `review_closed`,
`queue_closed`, `archive_open`). Continue/Reopen bulk actions sit on the review table, where
every stopped fill lands. `GET /api/applications/open-tabs` (`browser.open_target_ids`, one CDP
`/json/list` call, lock-free) is polled every ~4s and on focus: a row whose recorded tab is gone
shows "Tab closed" and Reopen instead of Continue, and a reopen with no live tab skips the
confirm. An unreachable browser means "unknown" and keeps Continue offered.

**Resolver scope.** `hybrid_resolver`'s scan treats only real popup triggers
(`[role=combobox]`, `[aria-haspopup=listbox]`) as dropdowns, one per `formField-*`, and never
anything inside an upload widget (`select-files`, `file-upload-*`, drop zones) or a multiselect
prompt's containers — it opens each candidate to read its options, and opening "Select files"
raised the OS file picker. A `filechooser` listener on the fill tab swallows any picker a stray
click still opens (uploads use `set_input_files`). Each wizard step has a `StepLedger` per
frame shared by every resolver pass on that step: controls already resolved or already put to
the model are not reopened or re-asked, and passes after a rejected advance retry only fields
the form marks invalid (when it marks any) — a stuck field is retried alone, not the page.

The replacement async observation/action engine is under the internal
`APPLY_FILL_ENGINE=verified` switch; the default remains `legacy` until its Greenhouse,
Workday, submission, and live acceptance gates are complete. `dom_scan.js` is packaged as
Apply data and observes fields without writing. Python owns matching and policy, while
`controls.py` performs frame-scoped writes and re-observation. Review refresh and explicit
one-field corrections share the Apply operation lock; a correction requires a fresh
snapshot and state hash. Prepare records the source employment count with expansion output
so an empty expansion is accepted only when no source employment existed at preparation.

Platforms (plan P4-A): `store.AtsKind` also names Taleo, SuccessFactors, Oracle Cloud,
Jobvite, BambooHR, LinkedIn, Indeed and Handshake; `fetch_jd.detect_ats` and
`identity.canonical_key` recognise their URLs (`fetch_jd.AtsName` must match `AtsKind`, and a
test checks it). LinkedIn, Indeed and Handshake are assist-only like Workday
(`fill.ASSIST_ONLY_ATS`): filled, never submitted automatically. Multi-step platforms get a
`wizards.WizardAdapter` whose pure `classify(snapshot)` names the screen. Each fill step
first hands over a sign-in, account creation, an emailed code or a closed posting (before
anything is typed), and a review page ends the loop like Workday's Review step. Workday
itself stays on `workday_flow`; `WorkdayWizard` only renames its states. `filler.js` and
`filler_readiness.js` search open shadow roots (`deepQueryAll`; label and radio-group
lookups use the control's own root). `python scripts/ats_stats.py` counts rows by
re-detected ATS and status, to choose the next adapter.

Nightly: enable `apply.enabled` in settings, or run `python scripts/apply_daily.py`. List
README section names with `python scripts/apply_daily.py --list-sections <url>`. SPA route
`/applications` (working and archived tables) and `/applications/:applicationId`
(saved overview, documents, application content, and form review). The list API accepts
`archive=active|archived|all`, case-insensitive `q` over company/role/location, status,
sort/direction, limit, and offset. Its default archive scope is `all` for existing clients.
`POST /api/applications/archive` accepts 1–500 IDs and a boolean `archived`, returning
successful IDs and per-record errors. Archive is manual and independent of status;
restoring a submitted record leaves it submitted. Archived rows remain readable and in CSV
but cannot be prepared, filled, retried, or corrected until restored. The registry edit
uses nonblocking Apply/daily worker gates plus the workspace lock and returns 409 if busy.
MCP tools:
`list_applications`, `get_application_packet`, `answer_application_question`,
`mark_application`.

For postings stuck in `needs_browser` (HTTP + CDP could not extract enough JD text), the
Claude Desktop skill in `docs/skills/apply-from-queue/` is the manual fallback — it opens
the posting, starts `tailor_application` with the copied JD text, then `mark_application`.
It never fills or submits ATS forms; the deterministic Playwright filler does that.

---

## 4. Vocabulary libraries

`config.TAG_ALIASES`/`VERB_FAMILIES` are composed at runtime from **packs**: shipped
`core-tech`/`finance-consulting` starter packs plus user-authored ones, selected per
workspace.

- **`library_seeds/`** holds shipped packs as packaged JSON (`core-tech.json`,
  `finance-consulting.json`), loaded via `importlib.resources` into `BUILTIN_PACKS`. Edits
  write a shadow file under `data/libraries/packs/` that `read_pack` prefers; `reset_pack`
  deletes the shadow to restore the starter. Shipped packs are not deletable.
- **`libraries.py`** is the engine: pack storage/validation (central store at
  `data/libraries/packs/`, shared across profiles, never rebound per-workspace),
  composition (`resolve_effective`: enabled packs merge in list order, a workspace's own
  overrides/`*_removed` win), and `apply_to_config()`, which rebinds
  `TAG_ALIASES`/`VERB_FAMILIES` to *new* dict objects — `config.verb_family`'s index cache
  invalidates by identity, not equality. A verb claimed by two packs' families is a
  diagnostic, not an error — two packs can legitimately disagree and have to compose.
- **Per-workspace state** (`enabled_packs`, `overrides`, pending `proposals`, `rejected`)
  lives in `data/workspaces/<id>/libraries.json`, a sibling of `settings.json` rather than a
  key inside it — `PUT /api/settings` rewrites that file wholesale.
- **`propose.py`** drafts new aliases/verb assignments from a run's own near-miss keyword
  gaps and unclassified opening verbs, then a deterministic code-side filter enforces every
  hard constraint (an alias target must already be a known tag, a verb family must already
  exist) — same "model selects, code enforces" split `facets.py` uses for renames.

---

## 5. Template generation

Four modules: `template_analyze.py` inspects an upload deterministically (no LLM, never
mutates) and proposes a mapping; `template_profile.py` is the Pydantic schema for that
mapping; `template_build.py` (via `scripts/build_template.py`) is the *only* code that tags
`main_template.docx`; `docx_text.py` reconciles `python-docx` character offsets with the
runs at those offsets (see §8). Calibration mirrors this split: `resume_tailor.calibrate`
holds the logic, `scripts/calibrate.py` is a thin CLI wrapper.

`template_build` clones one entry per section as a prototype, tags it, and deletes the
rest. Formatting is inherited from real XML rather than reconstructed: each tagged literal
or field is rebuilt as its own run, cloned from whichever source run covered that character
range in the upload.

**Two build modes**, chosen by the analyzer, recorded as `TemplateProfile.section_mode`:

- **`"fixed"`** (default, and the exact historical contract): one hard-coded
  `{%p for job in experience %}`-style loop per kind, anchored on that kind's own heading
  paragraph. A resume with exactly one heading per kind — the common case — always gets
  this, byte-for-byte identical to before section support existed. Adding a *second*
  same-kind resume section under a fixed-mode template still works, but both entries render
  under the one physical heading the template was built with; renaming/reordering a section
  has no visible effect until the template is rebuilt.
- **`"generic"`** — chosen automatically when detection finds something fixed mode cannot
  represent (two-plus headings of one kind, or any `list`-kind heading). Tags **one shared
  `{%p for section in sections %}` block**: a cloned, `{{ section.title }}`-tagged heading
  paragraph (`TemplateProfile.heading_prototype`, the formatting donor) followed by one
  `{%p if section.kind == '<kind>' %}` branch per enabled kind — independent blocks, not an
  `elif` ladder, so a kind with no prototype is just omitted with no ladder bookkeeping.
  Each branch has its own `{%p for <var> in section.entries %}` loop reusing the *exact*
  loop-variable names fixed mode uses (`job`/`proj`/`edu`/`group`/`bullet`/`detail`, plus
  new `item` for `list`). Which sections actually appear, in what order, under what title,
  is decided entirely by `MasterResume.sections` at *render* time — the template itself
  needs no rebuild to add, rename, or reorder a section. `TemplateProfile.sections:
  list[DetectedSection]` (what the analyzer found, in doc order) has **no effect on the
  build** — it exists purely for the wizard UI's confirmation display; only the five
  kind-level prototype mappings (`experience`, `projects`, `list_section`, `education`,
  `skills`) matter to `build_generic`.
- A resume section whose kind the active template has no prototype for is skipped at render
  time (`render.build_context`) and surfaced as a warning in `FitResult.warnings`
  (`fit.fit`) — loud skip, never synthesized layout.
- `template_build._tag_*_prototype` functions (one per kind) do pure tagging only — no loop
  insertion, no deletion — shared by both modes. Fixed mode's `build_*_profile` wrap them in
  a single hard-coded loop; `build_generic` wraps them in the shared block instead.

**Two layouts**, orthogonal to the two build modes, recorded as `TemplateProfile.layout`:

- **`"paragraph"`** (default) — content lives in body paragraphs, `doc.paragraphs`. Every
  template before `layout` existed is this.
- **`"table"`** — content lives inside one invisible layout table, used purely to
  right-align dates/locations without tab stops (a common Word/Google Docs export shape).
  Always implies `section_mode="generic"` — see the field's own docstring for why.
  `template_build.build_generic_table` is the row-level counterpart of `build_generic`: the
  shared block repeats table *rows* via `{%tr for/if %}` marker rows (see §8), not
  paragraphs, while bullet/detail/skills-group repetition inside one cell still uses
  ordinary `{%p for %}`. The whole system's paragraph-id space — `CharSpan.paragraph_id`,
  every bare `*_paragraph_id` field — is minted by exactly one function,
  `docx_text.iter_document_paragraphs(doc)` (a depth-first walk: body children in order,
  descending into a table as rows → physical cells → paragraphs), called identically by
  `template_analyze._load_paras` and `template_build._para_by_id`. An entry header's
  location/dates can live in a *different* paragraph than its company/school (the row's
  other cell) — `CharSpan` already carries its own `paragraph_id` per field, and
  `_tag_mapped_header` already resolves a field whose span isn't on the header's own
  paragraph, so this needed no schema change, only
  `template_analyze._entry_header_fields`/`_header_fields_across_cells` to detect it. A
  contact block spread across several paragraphs (name/address/email/phone in different
  cells) uses `ContactMapping.slots: list[ContactSlot]` instead of the ordinary
  single-paragraph joined line; empty `slots` (every non-table profile, and any
  single-paragraph contact block) is byte-identical to before this field existed.

**One upload path**: `POST /api/template/analyze` proposes a mapping; `POST /api/template`
(profile *required* — the hard-coded-headings legacy path was retired once
`templates/original_export.docx` was confirmed to analyze `ready: true` under the current
analyzer) writes `template_profile.json` and builds from character spans.
`template_analyze.validate_profile_against_doc` re-checks every mapped span before install
commits. Successful installs are snapshotted under `templates/workspaces/<id>/library/`
with a user label (max 20 saved entries). `template_build.build()`'s CLI/scripted path
errors clearly when no profile is found (on disk or passed in) rather than silently falling
back to anything.

After any template change, re-run `python scripts/calibrate.py` (or use calibrate-on-install
/ calibrate-on-activate in the UI).

### Analyzer correctness: structure, not just text

`template_analyze.py` corroborates every text-based heading/entry match against the
document's own structure — formatting, position, content — rather than trusting a keyword
substring alone:

- **`_fingerprint(paragraph)` + `_heading_classes(paras)`**: a formatting signature (style,
  bold, size, alignment, indent, spacing, has-tab, all-caps bucket) clustered across the
  document. A class needs ≥2 short, non-bulleted, content-introducing members — real
  section headings usually share one formatting signature; a single stray ALL-CAPS line
  does not repeat and never forms a class of its own. An unaliased text match is
  hard-gated on class membership when a class exists; a weak aliased match (the
  ≤0.6-confidence tiers, which have no case requirement at all) is downgraded and flagged
  (`heading_formatting_mismatch`, non-blocking) rather than excluded outright, since a real
  template occasionally styles one heading slightly differently.
- **Two position-based hard exclusions**, below 1.0 confidence, that fingerprint
  corroboration alone cannot catch (an entry header's formatting can coincidentally land in
  the same class as the real headings just as easily as a genuine heading styled
  differently can fail to): `p.has_tab` (a real section heading never itself carries a
  trailing tab-aligned date — a later entry's own header, e.g. an "OTHER ACTIVITIES" entry
  whose text happens to contain "Education", must not be read as a new section), and
  `_immediately_follows_entry_header` (a title line sitting right under its own entry's
  company/dates header, e.g. "Experience Designer", is that entry's title, never a new
  "experience" section).
- **`_split_entries`** is bootstrap (bullet-anchored) plus a fingerprint-corroborated
  re-split, unioned rather than replacing — a fingerprint-only re-split would incorrectly
  re-merge an entry that simply lacks the section's dominant format (e.g. a still-current
  role with no end date) into its predecessor.
- **`_reconcile_header_fields`** runs field detection on *every* entry in a section, not
  just one prototype, and keeps a field only when a majority of entries carry it —
  `FieldCandidate.confidence` is a real presence rate. A field absent from the majority is
  a blocking `experience_dates_not_detected` / `project_dates_not_detected`; present on
  some entries but not all is a non-blocking `..._dates_partial`.

### Wizard: confirm + preview

- **`field_candidates`** (per-field detected spans, not just section summaries) rides on
  `TemplateAnalyzeResponse` — the wizard shows a red row for any required field
  (`company`/`dates`, `name`/`date`, `school`/`dates`) nothing was found for.
- **`POST /api/template/analyze/remap`** re-runs analysis with specific headings' kinds
  forced by the user (paragraph id → kind, or `null` for "not a section"), bypassing every
  heuristic gate for just those paragraphs — `template_analyze._analyze_document`'s
  `overrides` parameter. Needs the original upload's bytes without re-uploading:
  `template_ops._cache_upload`/`_load_cached_upload` keys a short-lived cache by the
  upload's own sha256 under `output/.../template/uploads/`, cleared on install or after
  24h.
- **`POST /api/template/preview/source`** and **`POST /api/template/preview/draft`** give
  the wizard a real side-by-side: the uploaded document as-is, and what installing the
  current draft profile would actually produce (built in a temp directory, never touching
  the live template slot).

### DOCX → master_resume.json import

`resume_import.py` turns an uploaded document's own *content* (not just its layout) into a
`MasterResume` draft — `POST /api/master-resume/import` (multipart, optional
`suggest_tags` field) returns `{resume, warnings, untagged_bullet_count}` and writes
nothing; the editor loads the result as unsaved state via `editorState.loadDraft`.

- Deterministic, no LLM required: reuses `template_analyze`'s own paragraph-level helpers
  (`_split_entries`, `_header_fields_from_text`, `_skills_spans`) to parse *every* entry
  (not one prototype), and seeds tags by whole-word substring match against a known-tag
  vocabulary (`resume_import._seed_tags`). A bullet nothing matched gets the sentinel tag
  `"untagged"` (`Bullet.tags` requires ≥1 entry) and is counted, not silently guessed at.
- **Optional, explicitly opt-in LLM pass**: `propose.propose_bullet_tags(bullets,
  known_tags)` — same "model selects, code enforces" contract as `propose_vocabulary` (a
  tag outside `known_tags` is dropped). Never part of `resume_import`'s own call graph; a
  failure there becomes a warning in the response, never a failed import.
- `render.parse_month`/`render.parse_range` are the literal inverse of
  `format_month`/`format_range`, living next to them. `docx_text.hyperlink_target` resolves
  a `w:hyperlink`'s actual target URL (every other caller only ever needed the visible
  label text; this is the first that needs where a link actually points, to reconstruct
  `Project.url`).
- **`POST /api/master-resume/merge` (`resume_import.merge_into`) folds an imported draft
  into the existing master resume** — matched entries updated in place, unmatched ones
  added, everything else untouched; never a full replace, since the master resume is
  deliberately a superset. Matching is exact `_match_key` equality for every kind except
  **education**, which also matches a boundary-anchored school-name suffix (`_is_near_miss`
  — "University of X" vs. "University of X — Y School of Business"), since one export
  commonly names a school's college where another doesn't. A matched education entry merges
  field-by-field (`_merge_education_entry`, mirroring `_merge_contact`) rather than
  replacing wholesale, specifically so a curated `gpa`/`show_gpa` the incoming `.docx` has
  no way to express (GPA as free text, not the `| GPA: …` form `_GPA_RE` requires) survives
  a merge.

**Starter templates** (`default_templates.py`): three built-in designs (Classic, Compact,
Business) for students whose own file can't become a template, or who only have a PDF.
`default_templates.build(name)` is the only producer of their baseline `.docx`. It
generates them with python-docx at install time and never commits them, since `.docx`
files stay out of git. The build is byte-reproducible, so the hash is stable. Installing
one (`POST /api/template/defaults/{name}/install`, `template_ops.install_default`) goes
through the same analyze → `template_build` → verify → commit path as an upload. When the
library already holds those exact bytes, that entry is re-activated instead. Every design
carries every section kind, so the analyzer picks `section_mode="generic"`. Business lists
Education first; because the render order follows the master resume, the UI offers to move
the student's Education sections up. `scripts/build_default_templates.py --out DIR --pdf`
writes each bundle plus a filled sample PDF for checking a design change by eye.

---

## 6. Fit-loop tuning and measurement

- **`UNDERFLOW_THRESHOLD` sits at 0.93** (target density for one-pagers) — lower toward
  0.86 if grow/rewrite API cost matters more than page density. Raised from an original
  0.85 that had been calibrated against pages that still contained widows.
- **The character budget is a cliff, not a slope.** Every widowed bullet measured came back
  at 204–207 characters against a 202-character budget; every non-widowed run had bullets
  at 180–199. `_length_band` advertises a target *range* below the ceiling specifically so
  the model doesn't optimise right up to the edge. `rewrite.widowed()` then catches
  survivors and `_polish` re-cuts only those, accepted only if strictly shorter and no
  longer widowed.
- **PDF rendering** goes through `convert.py`, selected by `config.PDF_BACKEND` (`word` on
  Windows by default, `soffice` in Docker/Linux). Fit constants are per-backend *and*
  per-profile, under `<active profile>/calibration/<backend>.json`. LibreOffice's
  calibration is trustworthy specifically because the container vendors the exact same font
  files Word used for the baseline PDFs (`docker/fonts/`), not metric-compatible
  substitutes. `CHARS_PER_LINE` doesn't move between backends (glyph advances are the
  same); `LINES_PER_PAGE` does.
- **`calibrate.py`'s render-anchor check is a per-workspace recorded baseline, not fixed
  numbers.** `calibrate.run(verify_anchors=True)` measures how many pages the full master
  resume and a half-size subset render to, fingerprints the resume and template that
  produced those counts (`measure_anchors`), and compares against whatever was last
  recorded for *this* workspace+backend (stored under the calibration file's own `anchors`
  key). A resume edit or template rebuild changes a fingerprint and silently re-baselines;
  only a page count changing under an *unchanged* fingerprint is real drift, and that stays
  a warning (never blocks the write — `write_calibration` still runs) unless re-run with
  `--rebaseline`, the deliberate acknowledgement step. There is no single "expected page
  count" baked into the code — it was hardcoded to one person's resume once (39 bullets →
  3 pages) and broke for every other workspace.

---

## 7. Backend / model routing detail

- **The default profile is `ollama`, not `claude`.** Both `tailor.py --model` and
  `JobSettings.model` default to `ollama` (`config.OLLAMA_MODEL`, `gemma4:cloud`), so a
  fresh install runs with no Anthropic key. `config.resolve()`'s own fallback and
  `backend_for`'s resolve-if-unresolved still default to `"claude"` — they guard importable
  library functions called by scripts/tests that never went through the CLI, and flipping
  them would silently reroute callers that never asked for a backend.
- **`config._ACTIVE` is only ever populated by `web/jobs.py`'s tailoring-job runner** — it
  is the sole `config.resolve()` call site under `src/`. A web route reached outside a job
  (the import wizard's "suggest tags" pass, vocabulary-proposal generation) that calls an
  LLM stage therefore hits `backend_for`'s `"claude"` fallback on a freshly started server,
  regardless of the saved Model setting. A route that must not do that — and must not call
  `resolve()` either, since that would repoint a job's remaining stages mid-run — wraps its
  call in `config.pinned(config.ONE_OFF_PROFILE)` (a `ContextVar` overlay `backend_for`
  checks first, invisible to other requests/threads). Only the import route's
  tag-suggestion pass is pinned today; `generate_library_proposals` still inherits
  `_ACTIVE`/the claude fallback.
- Every call uses `client.messages.parse()` with a Pydantic model — schema-validated, never
  prose parsing. On the Anthropic path, non-streaming calls cap reasoning+output at 21,333
  tokens (SDK limit), so effort and `MAX_TOKENS` are coupled there. **On the
  OpenAI-compatible path** (Ollama/LM Studio/Gemini), `MAX_TOKENS` is only the *starting*
  request — `llm._OpenAICompatClient.request` escalates a truncated response up to
  `config.max_token_cap_for(purpose)` before raising, and memoises the ceiling that worked
  per `(base_url, model)` in `llm._LEARNED_CEILING` so a multi-call run doesn't rediscover
  it every call. This exists because Gemini counts thinking tokens against the same budget
  as the answer.
- **Non-frontier backends may accept a JSON schema and ignore it** — measured against
  `nemotron-3-super:cloud`, `response_format: json_schema` returned HTTP 200 carrying
  markdown prose. `llm.py` puts the schema in the system prompt and escalates on **parse
  failure, not status code**. `config.structured_mode_for(purpose)` answers `"prompt"` for
  Ollama/LM Studio and `"schema"` for Gemini by default; `config.LLM_STRUCTURED_MODE`
  overrides globally. A rejection walks a ladder (`json_schema` → `json_object` → none in
  schema mode) rather than dropping straight to no constraint.

## 8. Expanded gotchas

Full versions of the one-line gotchas indexed in `CLAUDE.md`. Each of these produced a
file that was **well-formed XML and passed a naive parse check**, yet was broken.

- **Never name a context key `items`.** Jinja resolves attributes before keys, so
  `{{ group.items }}` returns the dict method and injects bogus XML. The skills key is
  `entries` for this reason.
- **`tpl.render(context, autoescape=True)` is required, not optional** — without it a
  literal `&` ("Tools & Languages") is swallowed as a malformed entity, and RichText
  hyperlinks render empty.
- **`{%p %}` for control flow, `{{r }}` for RichText.** A plain `{% for %}` splits the loop
  mid-paragraph and nests `<w:p>` inside `<w:p>`; a plain `{{ }}` around a hyperlink nests
  its run inside `<w:t>`, so the link silently disappears on read-back.
- **Tabs are `<w:tab/>` elements**, which `python-docx` renders as `"\t"`. Rewriting that
  text without removing the element yields two tabs.
- **A numbering level's `rPr` does not render the bullet glyph** — Google Docs writes
  direct formatting on every bullet paragraph's own mark (`w:pPr/w:rPr`), which takes
  precedence over the abstract numbering level in `numbering.xml`.
  `shrink_bullet_marker` scales the paragraph mark's own `w:sz` instead of fighting that
  precedence.
- **`python-docx`'s `Paragraph.text` includes hyperlink visible text; `Paragraph.runs`
  excludes hyperlink-nested runs.** Measuring a span against one and editing via the other
  mis-slices everything after the first hyperlink — this is exactly how a project's date
  once lost its tab stop. `docx_text.py` exists to keep every span/offset agreement
  consistent; strip hyperlinks *after* resolving offsets, never before.
- **A hyperlink can render in Word and still be dead in the PDF** — LibreOffice needs
  `w:rStyle w:val="InternetLink"` *and* a matching `styles.xml` definition to emit a PDF
  `Link` annotation; Word keeps the link clickable with neither.
  `render._ensure_pdf_hyperlink_styles` runs as a post-save zip patch to register the style
  and backfill the reference onto any hyperlink run missing it.
- **The template preview cache must key on both its inputs** — `template_ops
  .ensure_preview` renders `master_resume.json` *through* `main_template.docx`; its
  staleness check must compare both files' mtimes, or a resume edit alone serves a stale
  PDF. The SPA half of this bug: `refresh()` must bump `previewKey` (the `<iframe>`
  cache-buster) or a fixed cache still shows a stale frame.
- **A client-side route needs a `StaticFiles` fallback, not just `html=True`.**
  `_SPAStaticFiles` catches 404s and re-serves `index.html` so a hard refresh on `/editor`
  doesn't 404 — but must catch Starlette's `HTTPException` directly (FastAPI's is a
  subclass that doesn't cross-catch), and must exclude `/api/*` paths or a genuine backend
  404 would silently return HTML instead.
- **The fabrication guard fails on tokenisation, not dishonesty.** `_TOKEN` treats `/` `.`
  `-` `,` as internal (so `Python/FastAPI` and `1,000` arrive whole) but not `@` (so
  `Recall@k/MRR` splits). Before concluding the model embellished, check whether the term
  is simply spelled differently in the source — see `docs/PLAN.md`'s table.
- **A paragraph inserted mid-build shifts every later paragraph's index.**
  `_tag_education_prototype`'s degree/detail-share-one-paragraph fallback clones the degree
  paragraph in place (`addnext`) when there's no separate detail bullet — harmless under
  fixed mode because `build_from_profile` processes kinds bottom-up (descending
  `heading_paragraph_id`) specifically to avoid this, but `build_generic`'s per-kind loop
  needs the same descending-order processing or a kind physically below an
  education-with-single-line-entry section gets its prototype spans corrupted.
- **A rule/underscore paragraph reads as an entry header unless filtered.**
  `template_analyze._is_chrome` (blank, or `^[\s_\-–—=·.]+$`) must be checked in
  `_split_entries` — without it, a horizontal-rule paragraph under a heading is read as the
  first entry's header line, and whatever field maps to "the first header in the section"
  lands on the rule instead of the real content below it.
- **A section's body boundary must be found by paragraph identity, not by matching another
  heading's text.** `template_build._section_body_paragraphs` stops at the first paragraph
  *object* in a pre-resolved `other_headings` list, not at a walked paragraph whose text
  happens to equal another heading's text — an ordinary entry line that reads exactly
  "SKILLS" (a bolded label inside a bullet, say) is otherwise indistinguishable from the
  real heading and silently truncates the section early, building without error. The
  `other_headings` objects must be resolved once, before any section's body is touched
  (`_para_by_id` at each kind's own `heading_paragraph_id`) — headings themselves are never
  moved or deleted mid-build (only the space between them is), so the reference stays valid
  regardless of build order, but an index re-derived later would not.
- **A `{%p for %}` loop cannot repeat a table row — docxtpl consumes it instead.**
  Verified by reading `docxtpl.DocxTemplate.patch_xml`: its row-tag pass (which runs
  *before* the paragraph-tag pass) replaces the **entire** `<w:tr>` containing a
  `{%tr %}` tag with the bare Jinja text — the row disappears, it is not repeated. A
  row-level loop therefore needs its own disposable one-cell marker row per
  `for`/`if`/`endfor`/`endif` (`template_build._marker_row`), with the rows meant to
  actually repeat sitting between an open marker and a close marker — never a `{%tr %}` tag
  placed inside a content row, which would delete that row's own content along with the
  tag. The tagged intermediate template still opens fine in Word (every row is
  individually well-formed OOXML) and looks structurally plausible; it just silently
  renders nothing where the loop was.
- **`Table.rows[i].cells` expands over `gridSpan` — it is not the row's physical `<w:tc>`
  count.** A 3-span-plus-1 row reports as four `Cell` objects under python-docx's own API,
  two of them the same underlying `_tc` returned twice. Any code that needs "does this row
  have a second populated cell" (heading-vs-entry-header detection, table-layout
  classification) must count `row._tr.findall(qn("w:tc"))` directly —
  `docx_text.ParaLocation.row_cells`/`row_content_cells` do this so nothing else has to
  re-derive it.
- **A cell holding several stacked repeatable paragraphs (three bullets, three skill
  labels) needs everything *after* the chosen loop prototype stripped, not just wrapped.**
  `template_build._wrap_cell_loop` puts `{%p for/endfor %}` around one paragraph and
  removes every later paragraph in that same cell — otherwise, since the whole *row* gets
  cloned once as the loop's per-iteration template (`build_generic_table`), an untouched
  sibling bullet renders verbatim on every entry instead of being replaced by however many
  the loop actually produces. Never strips a paragraph *before* the wrapped one — that is
  fixed content (a school/degree line the education fallback's synthetic single-paragraph
  detail clone sits after), not a repeatable sibling.

---

---

## 9. Sections-as-lists detail

`data.MasterResume.sections: list[Section]` is a Pydantic discriminated union on `kind`:
`experience`, `project` (singular — the render context key and `EnabledSections` field
stay the legacy plural `"projects"`, bridged by `config.SECTION_KIND_ENABLED_KEY`), `list`
(a plain-bullet section with no entry header — certifications, awards), `education`,
`skills`. Any number of sections, any order, custom titles, multiple sections of the same
kind (e.g. "Work Experience" + "Leadership Experience" + "Other Activities" all being
`experience`-kind). A `model_validator(mode="before")` folds a legacy pre-`sections` file's
four top-level lists into four sections in fixed order (`education, experience, projects,
skills`), which is what keeps `all_bullets()`'s order — and therefore
`rewrite._score_cache_path`'s cache key — identical across the migration. Read-only
`@property` `experience`/`projects`/`education`/`skills` flatten same-kind sections back
into the old shape for ~50 call sites that only ever read one list — **never
`@computed_field`**, which would put those keys back into `model_dump` and let a saved file
carry two sources of truth. `resume.entry_sections` is `experience`+`project` kind sections
(the ones that carry bullets and go through selection); `list`/`education`/`skills` are
fixed overhead the fit loop never trims.

- **Selection ranks each section independently.** `fit.choose_entries` loops
  `resume.entry_sections`, ranking each against a per-kind default cap
  (`config.MAX_EXPERIENCE_ENTRIES`/`MAX_PROJECT_ENTRIES`) — a "Leadership" section's
  entries never compete with a job's for a slot, generalising the original
  experience-vs-projects split to any number of sections.
- **Bullet budgeting generalises the same way.** `rewrite._allocate_budgets(pools,
  weights, ...)` replaces the old two-section-only `_section_budgets`: floors per pool,
  proportional shares, then an iterative spill until every pool is satisfied or capped.
  `select_within_entries`'s old `experience_share` float is kept as two-pool sugar
  (`isinstance(e, Project)`-derived) for callers with no section wrapper at all; the
  `pools`/`weights` params are what `fit.py` uses once a resume can hold more than one
  section of a kind, since `isinstance` can no longer tell two same-kind sections apart.
- **The relevance table is computed once, before the loop, never inside it** — an API call
  in the retry path costs a dozen round trips per run, and a table that changed between
  iterations could let a grow step *swap* bullets rather than add them.
- **Two scoring signals, added not blended.** Tag overlap is exact/free;
  `config.SEMANTIC_WEIGHT` blends in the 0-10 LLM score. `SEMANTIC_WEIGHT = 0.0` reproduces
  keyword-only scoring exactly (`--no-semantic`), which is what makes a ranking change
  attributable rather than guessed at.
- **To debug a surprising ranking, read the cached artifacts first.**
  `output/*.requirements.json` shows what the posting was understood to require and each
  keyword's `canonical`; `output/*.scores.json` holds every bullet's relevance score and
  the model's one-line reason.
- **JD keywords are canonicalised against the resume's own tag vocabulary**, not in a
  vacuum — `TAG_ALIASES` is a small global spelling-collapser (does not generalise, by its
  own docstring); `known_tags` steering the model is what actually generalises.
- **Extraction is voted, not trusted from one call** — the same JD against the same
  resume, temperature 0, still ranged 3/10 to 6/11 must-have coverage across 8 runs on a
  live posting, because `canonical` is free text the model re-derives per call.
  `jd.extract_consensus` (`--extract-runs`, default `config.EXTRACT_CONSENSUS_RUNS = 3`)
  groups by verbatim `phrase`, keeps a phrase only if a majority proposed it, and prefers a
  canonical that hits `known_tags` over a more frequent one that doesn't.
- **A missed keyword says why, not just that it missed.** `report.diagnose_gaps`
  classifies every unmatched canonical as `near_miss` (a bullet tag names the same thing,
  spelled differently), `untagged_evidence` (matches `Project.tech`/skills/coursework but
  no bullet tag), or `no_evidence`. Takes the *pre-facets* `master=` resume specifically,
  because `facets.apply` truncates `Project.tech` to its render budget before the report is
  built.
- **`bullets: dict[id -> text]` is the pipeline's currency.** `render.build_context` uses
  it as both content source *and* selection filter — an entry whose bullets were all
  dropped is omitted entirely, which is how the fit loop sheds a whole entry. `None`
  renders the full master resume untailored (calibration/smoke tests).
- **`master_resume.json` is a superset**, deliberately larger than any one resume, so an
  ops/support-flavoured posting can surface roles a tech-flavoured one wouldn't.
- **Education/skills are tailored in wording, never resized.** `facets.select_facets` picks
  coursework titles and project tech labels (≤4, JD-anchored renames allowed) and may
  reword skill items toward the posting's wording, but item counts/order are fixed. A skill
  rename requires three guards together (`rename_is_jd_anchored`, `labels_are_equivalent`,
  `rename_preserves_claim`) and must not push the group's line count above its original.
- **`include.py` is a pure resume transform, applied once, after scoring, before facets.**
  `IncludeOptions.exclude_entries`/`exclude_sections` are the general form (one flat id
  namespace across every experience/project section, matching
  `data.MasterResume._ids_unique`, which checks every entry id together regardless of
  section); `exclude_experience`/`exclude_projects` are accepted as legacy aliases folded
  into the same set. Placement matters: earlier would invalidate the score cache on every
  toggle; later would let an excluded entry's tech/coursework still shape what facets
  shows.
- **Web UI is an alternate front door, not a second pipeline** — `src/resume_tailor/web/`
  queues jobs into the same pipeline. Jobs run concurrently up to
  `JobSettings.max_concurrent_jobs` (§2), each in its own `RunContext`; the process-wide
  module globals still make a **single process** a hard requirement. `events.py`'s one-way `ProgressEvent` callback is optional everywhere,
  which is what keeps it out of the callback-free CLI test suite.
- **MCP is a third front door, also not a second pipeline** — `src/resume_tailor/
  mcp_server/` is a stdio MCP server for Claude Desktop that talks plain HTTP to the
  running uvicorn process (`RESUME_TAILOR_API`, default `http://127.0.0.1:8000`). It never
  owns `config._ACTIVE`, never starts uvicorn, and never wraps write routes for master
  resume / template / vocabulary libraries / workspace delete. Scope is read-plus-starting-
  runs: list/activate profiles, `tailor_application`, read runs/artifacts, regenerate cover
  letter, `get_resume_facts`, `verify_claim`, plus the apply tools in §3. Example Claude
  Desktop entry: `docs/claude_desktop_config.example.json`. Run with
  `python -m resume_tailor.mcp_server` (stderr only — stdout is JSON-RPC).

---

## 10. Hard rules in full (guard mechanics, cache keys, cover letter)

- **`templates/cover_template.docx`** is generated by exactly one script,
  `scripts/build_cover_template.py` (wrapping `resume_tailor.cover_template`). It is
  derived from `original_export.docx` so letterhead matches the resume; never hand-edit
  it. The web Template tab regenerates it after a resume-template install. Rebuild also
  triggers when `cover_template.meta.json`'s `builder_version` lags
  `cover_template._BUILDER_VERSION` (code changes would otherwise leave stale files on
  disk). Layout constants: `config.COVER_MARGIN_INCHES` (1.0"),
  `config.COVER_CONTACT_FIELDS` (location/email/phone only — drops LinkedIn/GitHub from
  the letterhead), 1.15 body line spacing, and a cloned section-heading rule under the
  contact line.
- **The fabrication guard** decomposes compounds on both sides (`Python/FastAPI`,
  `Recall@k/MRR`) and matches plurals; only letter-bearing parts license a match (`96.3`
  never licenses a `3`), and numbers are checked whole (`99%`/`GPT-4.1` still fail if
  fabricated) — both pinned by tests. Beyond token membership, `rewrite.guard_offenders`
  also flags **number-noun rebinding** (`40 engineers` → `40 hours`) and
  **delegated-authorship escalation** (coordinating a vendor → claiming you built the
  work); coverletter/expand keep using `check_fabrication` alone. A fabricating first
  draft gets **one** targeted retry naming the offending bullet ids; a second
  fabrication, or a dropped id, falls back to that bullet's original master-resume text
  and is reported in `RewriteOutcome.fabrications_rejected` as a run warning, never
  raised — same pattern as a fabricating widow-repair candidate, which is likewise
  discarded and reported (`widow_repairs_rejected`) rather than raised, since the
  pre-polish text is already guard-clean. `FabricationError` still exists and is still
  raisable in principle, but nothing in `rewrite.py` raises it any more — the fallback
  text is always the verbatim source, so the "never invent" invariant holds without
  failing the whole run over one stubborn bullet.
- **Cover-letter guard** (`coverletter.py`, narrower than the rewrite guard): numbers and
  first-person claim sentences are checked against the tailored bullets plus resume entry
  headers (employer/title/school/project names packed into a synthetic context bullet —
  not the JD's vocabulary) and the raw JD for numbers only; company/location/addressee
  must appear verbatim in the posting or are blanked; AI tells (long dashes, phrase
  blocklist) and consecutive-"I" openers are enforced in code with one targeted retry.
  Cover letters may issue one guard retry.
- **Merge checks**: `rewrite._merge_bullets` fires only after a measured overflow
  (`fit.fit`'s `attempt >= 1`), and is accepted only when non-regressive, guard-clean,
  numeric-token-preserving, and free of `redundancy_offenders`. *Which* bullets are
  affinity-eligible to merge (`config.MERGE_AFFINITY_SCHEDULE`) is deterministic, no-LLM
  logic in `merge.py`; the rewrite + guard checks live in `rewrite._merge_bullets`.
- **Cache-key composition** (the full rule set): `config.fingerprint(purpose)`
  (`origin`, model, effort) is folded into `jd._slug` and `rewrite._score_cache_path`;
  `propose._cache_path` extends the same rule with `libraries.effective_fingerprint()`;
  `expand._cache_path` also folds in `style.digest("expand")` when a profile's
  expand-style override differs from the shipped default. Keys on `Backend.origin`, not
  `.provider` — Ollama/LM Studio/Gemini all remap to `provider == "openai"` for the
  client shape, so without `origin` two of them sharing a model string would collide.
- **Style splitting**: `rewrite._SYSTEM` and `expand._SYSTEM` split into non-editable
  fabrication/number/id/length rules plus an editable style block (`style.py`'s defaults,
  overridable via `JobSettings.rewrite_style` / `expand_style` / `cover_style` in
  `settings.json`). When no override is set, `_system()` returns the legacy prompt
  byte-for-byte; when overridden, the locked core is always prepended. Still plain
  strings — the architectural invariant holds. `style.activate()` sits beside
  `config.resolve()` in both `web/jobs.py` and `tailor.py`.

---

## 11. Testing conventions in full

- **API calls are stubbed with hand-written fake clients**, not a mocking library — see
  `_FakeClient` in `tests/test_jd.py`. A fake exposes `.messages.parse(**kwargs)`
  returning an object with `parsed_output`/`stop_reason`; tests assert against recorded
  `kwargs`.
- **A stage that can call twice needs a *shared* reply queue in its fake** —
  `llm.client_for` is invoked once per call, so a fake that copies its queue per client
  silently replays the first reply on a follow-up call. See the `rewrite_calls` fixture
  in `tests/test_rewrite.py`.
- **`tests/test_tailor_cli.py` has autouse fixtures stubbing `rewrite.score_table`,
  `facets.select_facets`, `expand.expand_experience`, `skills.select_skills`,
  `coverletter.draft_letter`, `review.review_bullets`.** Adding another API call to
  `tailor.main` needs those fixtures extended or the CLI tests reach the network.
  `tests/test_web.py` stubs the same seams on the job path (the `client` fixture's
  default `skills.select_skills` and `coverletter.draft_letter` stubs in particular — a
  per-test stub still wins by overriding it after fixture setup).
- **Word/COM is monkeypatched at `fit_mod.render`** so the loop's shorten/underflow logic
  is testable in isolation. `tests/test_render.py` is the exception — it renders a real
  `.docx` and parses it back, never converting to PDF.
- **Assert on the specific warning, not on `result.warnings` being empty** — `FitResult`
  carries underflow *and* widow warnings, and identity-rewrite fakes feed master-resume
  text straight through, so some source bullets legitimately end on a near-empty line.
- **The suite is hermetic — no developer's own `data/`/`templates/` is required.**
  `tests/fixtures.py` holds the shared synthetic-docx builders (`_add_bullet_numbering`,
  `_make_bullet`, `_docx_bytes`, `_add_hyperlink`, `_standard_resume`,
  `_multi_section_resume`, `_full_featured_resume`, `_table_resume`,
  `_sidebar_table_resume`) and `synthetic_resume()`, the matching `MasterResume` —
  tests needing real content use these, not `data.load()` against a personal
  `data/master_resume.json`. `_table_resume`/`_sidebar_table_resume` are `layout="table"`
  fixtures — raw `w:gridSpan` via `_shape_row`, never `_Cell.merge` (which operates on
  the logical grid and renumbers `Table.cell(r, c)`, so a fixture needing an exact
  physical `<w:tc>` count cannot express itself through it) — reproducing the real-world
  document that motivated table-layout support, including its gridSpan inconsistency
  between same-kind sections (3+1 vs 2+2) and its cross-cell skills grid; entry-header
  paragraphs need real bold/italic/alignment formatting, not plain text, or
  `_split_entries`' fingerprint-based re-split (correct, load-bearing behavior for real
  resumes) mis-splits every field into its own entry. `tests/conftest.py`'s autouse
  fixtures pin the rest of the machine-local state a bare run would otherwise pick up:
  `_pinned_calibration` (fixed `CHARS_PER_LINE`/`LINES_PER_PAGE` instead of whatever the
  local calibration file says), `_isolated_template_paths` (redirects baseline/tagged/
  profile paths into a temp dir), and session-scoped `built_template` (analyzes + builds
  `_full_featured_resume` once per session for tests that need a real tagged template).
  Verify hermeticity directly:
  `RESUME_TAILOR_DATA_DIR=<empty> RESUME_TAILOR_TEMPLATES_DIR=<empty> pytest`.
- **Anything genuinely specific to the real `data/master_resume.json` is
  `@pytest.mark.owner`-marked** and excluded by default (`pyproject.toml`'s
  `addopts = -m "not owner"`); run it explicitly with `pytest -m owner`. It still guards
  itself at runtime with a skip if the file isn't present, since it's gitignored and
  won't exist on a clean checkout or in CI.
- **`tests/conftest.py`'s `_isolated_libraries` autouse fixture** redirects the vocabulary
  pack store and resets `config.TAG_ALIASES`/`VERB_FAMILIES` per test, so a bare run never
  picks up a developer's own approved packs.
- **A staged/profile-based template build has an in-process fallback** —
  `template_ops._install_with_profile` shells out to `scripts/build_template.py` first,
  but falls back to calling `template_build.build_from_profile` directly whenever the
  subprocess exits non-zero *or* doesn't write the staged output path. A test stubbing
  `_run_build` to skip the subprocess (returning e.g. `(1, "stub: subprocess skipped")`
  without writing anything) therefore still exercises a real, verified build via that
  fallback — `_smoke_render`/`_verify_staged_build`/`template_verify` all run for real
  against it. See `tests/test_web.py::_resume_upload_with_profile` and its callers for
  the pattern: a real analyzable upload + its own suggested profile, not
  `_minimal_docx_bytes()`, since `POST /api/template` requires a profile now.

---
