# frontend/ — React + TypeScript SPA (Vite)

Talks only to `/api` (`src/api/`, whose types mirror `src/resume_tailor/web/schemas.py`).
It never sees document XML — same invariant as the backend.

This file is mirrored byte-for-byte by `AGENTS.md` beside it: edit both together with the
same text (`tests/tooling/test_agent_docs.py` enforces it).

## Commands (run in `frontend/`)

```powershell
npm install; npm run build     # build dist/ served by uvicorn at http://127.0.0.1:8000
npm run dev                    # hot-reload SPA, proxies /api to the running server
npm run lint                   # oxlint
npm run test                   # vitest;  single file: npx vitest run src/lib/runProgress.test.ts
npx tsc -b                     # typecheck
```

`e2e/` holds Playwright specs (`playwright.config.ts`; `scripts/e2e_server.py` serves a
hermetic backend).

## Layout

- `src/api/` — typed API client + response types, one file per area (`jobs`, `settings`,
  `resume`, `templates`, `libraries`, `applySettings`, `applications`, `sources`) over
  `core.ts` (fetch/error/ETag plumbing, not re-exported). Always import from `../api`
  (the `index.ts` barrel) so `vi.mock("../api")` keeps covering every call.
- `src/state/` — React context providers (run, template, library, workspace, editor, ...).
- `src/pages/` — one folder per page area (`apply/`, `run/`, `editor/`, `onboarding/`,
  `profile/`, `settings/`); `src/components/` — shared UI (`ui/` primitives).
- `src/lib/` — pure logic with colocated `*.test.ts`; keep components thin and put
  testable logic here.

## Conventions

- Files: aim for ≤ ~400 lines; components ≤ ~150. Extract hooks into `lib/` or `state/`.
- Polling goes through `lib/adaptivePoll.ts` / `conditionalGet` (in `api/core.ts`); errors through
  `lib/errors.ts`; toasts through `lib/toast.ts`.
- Don't re-propose declined features: per-stage model overrides, hybrid routing,
  always-on repair toggles, run history.

## Template switching and resume review

Template state commits one `/api/template/state` snapshot; obsolete requests cannot overwrite it. `TemplatePreview` fetches the exact revision and discards old PDF responses. Ordinary saved/starter activation skips calibration. Tailor and Apply show `ResumeQualityNotice`; Fill confirms flagged resumes using their current revision. After bullet edits, refresh both document previews and quality reports. Settings > Advanced exposes shared simultaneous model request limits (local 1, cloud 3 by default).
