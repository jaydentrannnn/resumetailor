# ResumeTailor

Takes your master resume content, a job description, and your own `.docx` resume, and
produces a tailored resume that looks identical to the original — only the words change.
Around that core it can find postings, tailor an application kit for each (resume, cover
letter, written answers), and fill the application forms in your browser.

- **Your layout, untouched.** The model only ever sees and returns plain text; your
  `.docx` is filled mechanically, so fonts, spacing and layout stay exactly as you made them.
- **No invented content.** Every fact comes from your master resume. A rewrite that adds a
  skill or number you never listed is caught in code and replaced with your own wording.
- **Fits the page.** Each draft is rendered and measured; it is shortened or grown until it
  fits, and it fails loudly rather than silently cutting content.
- **Any model.** Runs on local Ollama by default (no API key needed), or on Claude, Gemini,
  LM Studio, or a mix.

## Install the desktop app (Windows)

1. Download `ResumeTailor_<version>_x64-setup-windows-x64.exe` from the
   [latest release](https://github.com/jaydentrannnn/resumetailor/releases/latest) and run it.
   The installer is not code-signed, so Windows SmartScreen warns you: click **More info →
   Run anyway**.
2. Launch **ResumeTailor** from the Start menu. The first start takes a few seconds.
3. Follow the setup screen (see [First run](#first-run) below).

Good to know:

- **Updates install from inside the app:** an **Update available** chip appears in the
  header, and Settings → About has **Install and restart**. You never reinstall; your data
  is zipped to a backup before each update.
- **Closing the window hides it to the tray**, so scheduled runs keep going. Quit from the
  tray icon.
- **Your data** lives in `%LOCALAPPDATA%\ResumeTailorData` (profile, resume content,
  templates, outputs, logs). Settings such as the model can go in a `.env` file there.
- **PDFs** are made with Microsoft Word, so Office must be installed. Without Word, install
  LibreOffice and put `RESUME_TAILOR_PDF_BACKEND=soffice` in that `.env`.
- **A model:** have [Ollama](#using-ollama) running, or add an API key in Settings → Models.

The owner's walkthrough (building installers, moving data from a dev checkout, updating,
day-to-day operation) is [`docs/GUIDE.md`](docs/GUIDE.md).

## First run

The setup screen walks you through:

1. **What you're studying** — picks the skill words it recognises and which job lists to search.
2. **Upload your resume** (`.docx`) — the app analyzes its layout and turns it into a
   template. You can also import the content of a PDF resume.
3. **Your content** — review the sections, entries and bullets it read; this becomes your
   master resume, which you can edit any time in the **Editor**.
4. **Template and page fit** — tunes how much text fits on your page.

Then open **Tailor**, paste a job description, and run. Each run produces the tailored
`.docx` and `.pdf`, plus an optional cover letter, reviewer notes and application answers.

Other pages: **Profile** (your applicant details for forms, saved answers, and several
profiles you can switch between, each exported or imported as one `.zip` of up to 2 GB),
**Template** (install or switch saved templates), **Vocabulary** (the skill and
action-verb libraries the rewriter uses), **Apply** (see [Automation](#automation-apply-page)),
and **Settings** (models, browser, extension pairing, updates).

---

## Run from source

For development, or to run without the installer. Personal data lives in `data/`,
`templates/` and `output/`, which are gitignored; restore them by hand after cloning, or
start empty and use the setup screen.

```powershell
copy .env.example .env
# Ollama is the default backend and needs no key; add ANTHROPIC_API_KEY / GEMINI_API_KEY
# only if you use those models.
```

The files the pipeline reads:

1. **`data/master_resume.json`** — every fact the tool can use
2. **`templates/original_export.docx`** — your baseline resume (read-only)
3. **`templates/main_template.docx`** — generated from the export (see below)

Generate the tagged template once (or after replacing the export). Prefer the **Template**
page in the web UI (analyze → confirm mapping → install; optional calibrate). Each successful
install is saved under a label in **Saved templates** so you can switch without re-uploading
(max 20). The CLI reads whatever mapping the wizard already confirmed and saved to
`templates/template_profile.json`:

```powershell
python scripts\build_template.py
# or with an explicit mapping:
python scripts\build_template.py --from path\to\export.docx --profile templates\template_profile.json
```

After any template change, run `python scripts\calibrate.py` (or use the UI calibrate
checkbox on install/activate) so fit constants match.

### Install (Windows)

Python **3.13** is required. If `py -3.13` isn't available, point at any 3.13 interpreter (Anaconda's, for example):

```powershell
& C:\ProgramData\anaconda3\python.exe -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-dev.lock   # pinned runtime deps + pytest/ruff/mypy
pip install -e .
```

Dependency ranges live in `requirements*.txt`; the pinned sets actually installed are
`requirements*.lock`. After changing a range, regenerate both with
`uv pip compile --universal -p 3.13 requirements.txt -o requirements.lock` (and the same
for `requirements-dev`).

`requirements.txt` alone is the runtime set (what the Docker image installs); use it
instead if you will never run the tests.

### CLI

```powershell
python tailor.py --jd path\to\job.txt
```

Output lands in `output/` (`.docx` + `.pdf`). Useful flags:

| Flag | Effect |
|------|--------|
| `--model PROFILE` | Backend profile: `ollama` (default), `claude`, `gemini`, `lmstudio`, `hybrid` |
| `--rewrite-model SPEC` | Override rewrite stage only |
| `--expand-model SPEC` | Override expansion stage only |
| `--skills-model SPEC` | Override skills-selection stage only |
| `--no-cache` | Ignore cached JD / score artifacts |
| `--no-expand` | Skip application-form experience text |
| `--no-skills` | Skip the tailored skills list |
| `--effort low\|medium\|high` | Reasoning depth for all stages |

### Web UI

```powershell
cd frontend
npm install
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn resume_tailor.web.app:app --reload --app-dir src
```

Open http://127.0.0.1:8000.

For a hot-reload SPA during development, run `npm run dev` in `frontend/` (proxies `/api` to port 8000) alongside uvicorn.

### Tests

Needs the dev install above (`requirements-dev.txt`).

```powershell
pytest
```

No API key, network, or Word required.

---

## Docker

Requires Docker Desktop, a filled-in `.env`, and the local `data/` + `templates/` directories.

```powershell
docker compose up --build
```

Open http://localhost:8000.

First time (or after a template/font change), calibrate fit constants inside the container:

```powershell
docker compose run --rm app python scripts/calibrate.py
```

The container uses LibreOffice for PDF measurement. Host Ollama / LM Studio are reachable via `host.docker.internal` (already set in `docker-compose.yml`).

## Automation (Apply page)

The **Apply** page finds postings, tailors an application kit for each, and fills the
application forms in a browser on your PC. It can run all of that on a nightly schedule,
or you drive it with three buttons: **Find jobs**, **Tailor files for selected**, and
**Fill selected**. Postings are split into **Needs you** (sign-ins, emailed codes,
CAPTCHAs, questions it won't guess, final checks), **In progress** and **Done**, sorted
by the date each job was posted.

### Where postings come from

Add and edit sources in the Apply settings drawer (**What to search**):

| Source | What it reads |
| --- | --- |
| **Job lists** | Curated GitHub README lists, e.g. SimplifyJobs internships / new-grad and speedyapply (enabled by default for tech; the setup screen picks lists for your field) |
| **Company watchlist** | Paste a company's careers page or job-board link; it finds the Greenhouse, Lever, Ashby, SmartRecruiters or Workday board behind it and watches every posting there |
| **Keyword search** | Adzuna or USAJobs by keywords and location, for any industry. Needs free API keys, entered in Settings → Models |

Every source can filter titles (must contain / skip) and locations, and has a maximum
posting age. Postings that duplicate one you already have are merged, and eligibility
rules screen out senior roles, graduate-degree-only roles, and citizenship requirements
you don't meet.

### Set up the browser

Fill drives a browser through its remote-debugging port. Use a **dedicated Microsoft Edge
profile**: Chrome refuses to open the port while any other Chrome window is running,
which would mean closing your normal browsing every time. (If Edge is your everyday
browser, the same applies to Edge; use whichever you use less.) The Apply page's browser
card shows the exact command; for a shortcut or a Task Scheduler "At log on" action:

```text
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\ResumeTailorEdge"
```

macOS: `"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/ResumeTailorEdge"`.
Do not add `--remote-allow-origins=*`: it lets any web page open in that browser drive your
logged-in sessions, and the app does not need it. The debugging port is open to any local
process, so keep it on localhost and use only job-site logins in that profile. Log into
Workday and other ATS accounts there once. The browser pill on the Apply page turns green
when it is connected. (The [browser extension](#browser-extension) is an alternative.)

### Day to day

1. Fill in **Profile** (contact details, work authorization, education dates, salary
   range, equal-opportunity answers). Fill answers only from these facts and from answers
   you saved earlier; a question they don't cover is left for you, never guessed.
2. **Find jobs**, or schedule the nightly run in the Apply settings drawer (**Nightly
   run**). The app must be running; the tray is enough, and a run missed while the PC was
   off catches up at the next start within 12 hours.
3. Select postings and press **Tailor files for selected**. It tailors with the Tailor
   page's model settings, several at once (Settings → Advanced → **Concurrent tailoring
   runs**, default 2, up to 4).
4. Select prepared postings and press **Fill selected**. It fills several at once, each in
   its own tab (**Parallel fills** in the Apply settings drawer, default 2, up to 4), and
   the progress banner shows each one. Each tab stays open for you to review.
   - **Continue fill** resumes a tab after you sort out a blocker (such as a Workday
     verification code); **Reopen and fill** starts a new tab if the old one closed
     (unsaved answers in it may be lost).
   - **Auto-submit** is off until you turn it on. Even then it respects per-run, per-day
     and per-company caps, spaces submits out, skips likely duplicates, keeps before and
     after screenshots, and never submits on Workday, LinkedIn, Indeed, Handshake or
     SmartRecruiters. There you always press Submit yourself.
   - **Pause all automation** in the header stops everything at once.

The **Autofill model** selector covers only Fill's AI tasks (drafted written answers and
hybrid form resolution). For calling-code menus shared by several countries, set the
profile's optional **Phone region**.

From a dev checkout with Docker, `docker compose up -d` sets
`CHROME_CDP_URL=http://host.docker.internal:9222`; run once with
`docker compose exec app python scripts/apply_daily.py --limit 5`. Without Docker (never
both against the same profile):

```powershell
.\.venv\Scripts\python.exe scripts\apply_daily.py --dry-run
```

To look at a job list's section headings before enabling its categories:

```powershell
.\.venv\Scripts\python.exe scripts\apply_daily.py --list-sections https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md
```

### Browser extension

The unpacked Chrome/Edge extension in [`extension/`](extension/) captures the job page
you choose. In `chrome://extensions` or `edge://extensions`, enable **Developer mode**,
select **Load unpacked**, and choose the `extension/` folder. Open ResumeTailor
**Settings → Browser**, generate a six-digit code, and enter it in the extension popup.
You can revoke a paired browser in Settings.

**Send to ResumeTailor** captures the current job; **Tailor now** prepares it. **Fill this
page** starts Fill when preparation is ready. Extension requests always disable automatic
submission: inspect the completed form and submit it yourself. LinkedIn, Indeed,
Handshake, and Workday remain assist-only platforms. If the description is behind a
login wall or an inaccessible iCIMS iframe, select the JD and use **Send selection to
ResumeTailor** from the context menu. An iCIMS iframe may also be opened as its own tab.

CDP remains the default Fill browser. To fill the selected tab through the extension,
start the optional loopback relay with `python -m resume_tailor.apply.cdp_relay`, set
`BROWSER_MODE=extension` and `EXTENSION_CDP_URL` to the printed URL before starting the
app, then choose **Use this tab for Fill (relay)** in the popup. See
[`extension/README.md`](extension/README.md) for setup. The extension contacts the local ResumeTailor server on
127.0.0.1 ports 8000–8010. Opening its popup sends the current page URL for lookup;
description text is sent only when you choose a capture action. The extension itself
does not contact job sites or model providers.

### Remote access (Cloudflare Tunnel)

Reach the web UI from outside your own machine — no port forwarding, no static IP, no
TLS cert to manage — by routing a subdomain you own through Cloudflare's edge to the
container. This app has no login of its own and `master_resume.json` plus every
rendered resume hold real PII, so a **Cloudflare Access** policy sits in front and
authenticates every request before it reaches the container.

One-time setup, entirely in the Cloudflare dashboard:

1. Add your domain to Cloudflare if it isn't already (Websites → Add a site).
2. **Zero Trust → Networks → Tunnels → Create a tunnel** → connector type **Docker** →
   name it (e.g. `resumetailor`) → copy the `--token <value>` from the run command it
   shows you.
3. In that tunnel, add a **Public Hostname**: subdomain of your choice (e.g. `resume`),
   your domain, service type `HTTP`, URL `app:8000` (the compose service name).
4. **Zero Trust → Access → Applications → Add an application → Self-hosted**: domain =
   the hostname from step 3, a policy that includes your email, authentication method
   **One-Time PIN** (built in, no external identity provider needed).

Then locally:

```powershell
# In .env: CLOUDFLARE_TUNNEL_TOKEN=<the token from step 2>
# In .env: RESUME_TAILOR_ALLOWED_HOSTS=<the hostname from step 3, e.g. resume.example.com>
#   (the server answers only loopback Host names otherwise, and returns 400)
docker compose --profile cloudflare up --build
```

(Or set `COMPOSE_PROFILES=cloudflare` in `.env` so plain `docker compose up` picks it
up automatically.) Without either, the `cloudflared` service never starts — it's opt-in
by design. Check `docker compose logs cloudflared` for `Registered tunnel connection` to
confirm it authenticated; a wrong/missing token or unrouted hostname shows up there, not
in the browser.

Two things to know once it's up:

- **Don't calibrate through the tunnel.** Calibrating on template install/activate runs
  several LibreOffice PDF renders inside one HTTP request, which can exceed Cloudflare's
  fixed 100-second timeout and return a 524. Leave calibrate-on-install/activate
  unchecked when working remotely and run it locally instead:
  `docker compose run --rm app python scripts/calibrate.py`.
- **Uploads are capped at 100 MB** on Cloudflare's free plan — well above any resume
  `.docx`, noted only so a future failure is attributable.

---

## Using Ollama

Ollama serves an OpenAI-compatible API. ResumeTailor talks to it over HTTP — local daemon or Ollama Cloud.

### 1. Install and start Ollama

- Local: [ollama.com](https://ollama.com) → install → pull a model, e.g. `ollama pull gemma3`
- Cloud: `ollama signin`, then use a `:cloud` tag (default is `gemma4:cloud`)

### 2. Point `.env` at it (optional — defaults usually work)

```env
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=gemma4:cloud
```

Leave `LLM_API_KEY` unset for local Ollama. Do not set an Authorization header unless your endpoint requires one.

### Skipping the local daemon (Ollama Cloud, direct)

Cloud models can also be called directly at `https://ollama.com` — no local `ollama`
install, no `ollama serve`, nothing running on the machine at all. Useful for handing
this project to someone who just wants to run `tailor.py` without installing Ollama.

1. Create a key at [ollama.com/settings/keys](https://ollama.com/settings/keys) (just
   needs an ollama.com account — the free plan works, same quota as the daemon-proxied path).
2. In the web UI, open Settings → Models, pick **Ollama Cloud**, and paste the key into
   "Ollama cloud key". On the CLI, set the key in `.env` and pass `--model ollama-cloud`:

```env
OLLAMA_API_KEY=your-key-here
```

The switch goes both ways: pick **Ollama** again to go back to the local daemon. Without a
key, the Ollama Cloud profile is refused before any call, naming `OLLAMA_API_KEY`. The
older route — `OLLAMA_BASE_URL=https://ollama.com/v1` for the plain `ollama` profile —
still works.

`OLLAMA_MODEL` does not need setting — it already defaults to `gemma4:cloud`, and the tag
is the same whether you reach it through the local daemon or straight over HTTPS. If a tag
404s, the error names the exact one that failed; check
[ollama.com's model library](https://ollama.com/library) and set `OLLAMA_MODEL` to override.

### 3. Run with the Ollama profile

```powershell
# All four stages on Ollama
python tailor.py --jd jd.txt --model ollama

# Cheap ranking/expand on Ollama, rewrite on Claude (recommended hybrid)
python tailor.py --jd jd.txt --model hybrid

# Override one stage
python tailor.py --jd jd.txt --model ollama --rewrite-model claude-sonnet-5
python tailor.py --jd jd.txt --model hybrid --expand-model ollama:gemma3
```

Specs use `provider:model`. The first colon splits provider from model, so tags like `gemma4:cloud` keep the second colon:

```powershell
python tailor.py --jd jd.txt --model ollama:gemma4:cloud
```

**ollama** is the default profile in both the CLI and the web UI, so a fresh install runs
without an Anthropic key at all. Under Models you'll see an **Ollama model** field
whenever an Ollama-routed profile is selected: leave it blank and the run uses
`OLLAMA_MODEL` (`gemma4:cloud`), shown as the placeholder and in the help line under the
profile dropdown. Only a value you actually enter overrides it, and then only for that
run — no `.env` edit, no restart. Under
`hybrid` this leaves the Claude rewrite stage alone; the per-stage **Rewrite model** /
**Expand model** fields still win wherever they are set. Saved with the rest of the
profile's settings, so it sticks across runs.

---

## Using Gemini

Google's Gemini models are reachable through their own OpenAI-compatible endpoint — same
`_OpenAICompatClient` path as Ollama/LM Studio, but this one genuinely requires a key.

### 1. Get an API key

Create one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (an
ollama.com-style free tier is available; no billing setup required to start).

### 2. Set `.env`

```env
GEMINI_API_KEY=your-key-here
```

`GEMINI_MODEL` and `GEMINI_BASE_URL` do not need setting — they already default to
`gemini-3.5-flash` and Google's OpenAI-compatible endpoint. Override `GEMINI_MODEL` if you
want a different one.

### 3. Run with the Gemini profile

```powershell
python tailor.py --jd jd.txt --model gemini

# Cheap ranking on Gemini, rewrite on Claude
python tailor.py --jd jd.txt --model gemini --rewrite-model claude-sonnet-5

# Pin a specific model
python tailor.py --jd jd.txt --model gemini:gemini-3.5-pro
```

In the web UI, pick **gemini**; a missing `GEMINI_API_KEY` is flagged inline under the
profile dropdown before you can start a run, rather than failing partway through one. A
**Gemini model** field appears the same way the Ollama one does — leave it blank to use
`GEMINI_MODEL`, or enter a tag to override it for that run (saved with the rest of the
profile's settings).

### A note on token limits

Gemini counts its internal "thinking" toward the same output budget as the answer, so a
stage that reasons a lot can occasionally run out of room before finishing its JSON. This
project handles that automatically: a response that truncates is retried once or twice at
a doubled token ceiling (up to Gemini's real output cap) before giving up, and the working
ceiling is remembered for the rest of the run so later calls to the same model start there
instead of rediscovering it. You should not need to touch this — `LLM_MAX_TOKENS` in
`.env.example` documents the manual override, for debugging only.

---

## Using LM Studio

LM Studio runs models locally and exposes an OpenAI-compatible server.

### 1. Load a model and start the server

1. Open LM Studio and load a model
2. **Developer → Start Server** (default `http://localhost:1234`)
3. Copy the **exact model id** shown for the loaded model (e.g. `google/gemma-4-12b`) — not an Ollama-style tag

### 2. Set `.env`

```env
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_MODEL=google/gemma-4-12b
# Local rewrite batches can be slow:
LLM_TIMEOUT=900
```

No API key needed. Keep `LLM_STRUCTURED_MODE=prompt` (default).

### 3. Run with the LM Studio profile

```powershell
python tailor.py --jd jd.txt --model lmstudio

# Or pin a specific loaded model
python tailor.py --jd jd.txt --model lmstudio:google/gemma-4-12b
```

In the web UI, pick **lmstudio** and set the rewrite/expand model ids to match whatever is loaded in LM Studio.

### Docker + LM Studio on the host

`docker-compose.yml` already maps:

```text
LMSTUDIO_BASE_URL → http://host.docker.internal:1234/v1
```

Start the LM Studio server on the host, then use the `lmstudio` profile from the container UI or CLI.

---

## Model profiles at a glance

| Profile | Extract / Score | Rewrite | Expand | Skills |
|---------|-----------------|---------|--------|--------|
| `ollama` (default) | Ollama | Ollama | Ollama | Ollama |
| `claude` | Claude | Claude | Claude | Claude |
| `gemini` | Gemini | Gemini | Gemini | Gemini |
| `lmstudio` | LM Studio | LM Studio | LM Studio | LM Studio |
| `hybrid` | Ollama | Claude | Ollama | Ollama |

Per-stage overrides (`--rewrite-model`, `--expand-model`, `--skills-model`, or the web UI fields) always win over the profile defaults.

## License

ResumeTailor is released under the [MIT License](LICENSE). The desktop installer also
ships `THIRD-PARTY-NOTICES.txt`, the licenses of the libraries it bundles
(`scripts/third_party_notices.py` generates it at release time).
