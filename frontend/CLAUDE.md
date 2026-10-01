# frontend/ — React + TypeScript SPA (Vite)

Talks only to `/api` (`src/api.ts`, whose types mirror `src/resume_tailor/web/schemas.py`).
It never sees document XML — same invariant as the backend.

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

- `src/api.ts` — typed API client + response types.
- `src/state/` — React context providers (run, template, library, workspace, editor, ...).
- `src/pages/` — one folder per page area (`apply/`, `run/`, `editor/`, `onboarding/`,
  `profile/`, `settings/`); `src/components/` — shared UI (`ui/` primitives).
- `src/lib/` — pure logic with colocated `*.test.ts`; keep components thin and put
  testable logic here.

## Conventions

- Files: aim for ≤ ~400 lines; components ≤ ~150. Extract hooks into `lib/` or `state/`.
- Polling goes through `lib/adaptivePoll.ts` / `conditionalGet` (in `api.ts`); errors through
  `lib/errors.ts`; toasts through `lib/toast.ts`.
- Don't re-propose declined features: per-stage model overrides, hybrid routing,
  always-on repair toggles, run history.
