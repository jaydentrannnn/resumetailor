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

Generate the tagged template once (or after replacing the export):

```powershell
python scripts\build_template.py
```

---

## Local install (Windows)

Python **3.13** is required. On this machine use Anaconda's interpreter if `py -3.13` is unavailable:

```powershell
& C:\ProgramData\anaconda3\python.exe -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### CLI

```powershell
python tailor.py --jd path\to\job.txt
```

Output lands in `output/` (`.docx` + `.pdf`). Useful flags:

| Flag | Effect |
|------|--------|
| `--model PROFILE` | Backend profile: `claude` (default), `ollama`, `lmstudio`, `hybrid` |
| `--rewrite-model SPEC` | Override rewrite stage only |
| `--expand-model SPEC` | Override expansion stage only |
| `--no-cache` | Ignore cached JD / score artifacts |
| `--no-expand` | Skip application-form experience text |
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

In the web UI, pick the **ollama** or **hybrid** profile under Models.

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

| Profile | Extract / Score | Rewrite | Expand |
|---------|-----------------|---------|--------|
| `claude` | Claude | Claude | Claude |
| `ollama` | Ollama | Ollama | Ollama |
| `lmstudio` | LM Studio | LM Studio | LM Studio |
| `hybrid` | Ollama | Claude | Ollama |

Per-stage overrides (`--rewrite-model`, `--expand-model`, or the web UI fields) always win over the profile defaults.
