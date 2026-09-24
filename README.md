# ResumeTailor

Takes your master resume content, a job description, and your own `.docx` template, and produces a tailored resume that looks identical to the original — only the words change.

## Prerequisites

Before anything runs you need:

1. **`data/master_resume.json`** — every fact the tool can use
2. **`templates/original_export.docx`** — your baseline resume (read-only)
3. **`templates/main_template.docx`** — generated from the export (see below)
4. A **`.env`** file (copy from `.env.example`)

These folders are gitignored (they hold personal data). Restore them by hand after cloning.

```powershell
copy .env.example .env
# Edit .env — add ANTHROPIC_API_KEY for the default Claude setup
```

Generate the tagged template once (or after replacing the export). Prefer the **Template**
tab in the web UI (analyze → confirm mapping → install; optional calibrate). Each successful
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

---

## Local install (Windows)

Python **3.13** is required. On this machine use Anaconda's interpreter if `py -3.13` is unavailable:

```powershell
& C:\ProgramData\anaconda3\python.exe -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-dev.txt   # runtime deps + pytest/ruff/mypy
pip install -e .
```

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

## Automation (daily apply)

ResumeTailor can discover new internship and new-grad postings overnight, tailor them,
and fill ATS forms from a browser on your host. The Apply page exposes this as three
separate actions: **Find jobs**, **Prepare selected**, and **Fill selected**. Each operation
shows its current application, stage, counts, and recent activity.

Default sources (edit `settings.apply.sources[]` to add/disable):

| id | kind | repo |
| --- | --- | --- |
| `simplify-internships` | HTML table | SimplifyJobs/Summer2027-Internships |
| `simplify-newgrad` | HTML table | SimplifyJobs/New-Grad-Positions |
| `speedyapply` | pipe table | speedyapply/2027-SWE-College-Jobs |

Inspect a README's section headings before enabling categories:

```powershell
.\.venv\Scripts\python.exe scripts\apply_daily.py --list-sections https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md
```

1. **Microsoft Edge with remote debugging** (dedicated profile). Chrome refuses to open
   its remote-debugging port whenever *any* other Chrome window — any profile — is
   already running under your account, which would mean closing your normal browsing
   session every time. Edge is a separate process from Chrome, so it sidesteps that
   entirely and can sit in the background without touching your regular Chrome. (If you
   also use Edge as a daily browser, the same restriction applies there instead — pick
   whichever of the two you use less.) Create a Task Scheduler "At log on" action, or a
   shortcut:

```text
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%LOCALAPPDATA%\ResumeTailorEdge"
```

   Log into Workday / other ATS accounts once in that profile. `--remote-debugging-port`
   exposes that profile to any local process; keep it on localhost and use only job-site
   logins there.

2. `docker compose up -d` (sets `CHROME_CDP_URL=http://host.docker.internal:9222`).

3. Open **Apply** in the UI. Confirm the Browser CDP pill is green. Fill **Applicant
   profile** (or use the seeded `data/workspaces/default/applicant_profile.json`).

4. In Tailor settings (saved with the profile), set `apply.enabled` true and optionally
   `schedule_time` (local `HH:MM`). Or run once:

```powershell
docker compose exec app python scripts/apply_daily.py --limit 5
```

5. Morning: select queue rows, run **Prepare selected**, then **Fill selected**. Keep
   **Auto-submit verified forms** off to review each completed form in Edge. Turn it on
   when you want verified forms to submit automatically; the per-run cap still applies.
   Fill opens each prepared posting in turn, leaves its tab open, and continues through
   blockers. Use **Review tab** to return to a form and **Continue fill** after you resolve
   a blocker. **Reopen and fill** starts a new tab if the saved one has closed; unsaved
   answers in the old tab may be lost. Enter Workday verification codes in its browser
   tab, then use **Continue fill**. For calling-code menus shared by several countries,
   set the applicant profile's optional **Phone region** before filling.

**Prepare** tailors with the same model settings as the Tailor tab (shown as "Tailoring: …"
next to the selector) — change the model there. The **Autofill model** selector covers only
Fill's AI tasks: drafted written answers and hybrid form resolution.

Host-only CLI (when Docker is not running — do not run both against the same workspace):

```powershell
.\.venv\Scripts\python.exe scripts\apply_daily.py --dry-run
```

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
2. Set in `.env`:

```env
OLLAMA_BASE_URL=https://ollama.com/v1
OLLAMA_API_KEY=your-key-here
```

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
