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
- `src/pages/` — one folder per page area (`apply/`, `run/`, `editor/`, `resume/`, `onboarding/`,
  `profile/`, `settings/`); `src/components/` — shared UI (`ui/` primitives).
- `src/lib/` — pure logic with colocated `*.test.ts`; keep components thin and put
  testable logic here.

## Conventions

- Files: aim for ≤ ~400 lines; components ≤ ~150. Extract hooks into `lib/` or `state/`.
- Every page starts with `ui/CommandBar` (title, state, actions; no intro copy) inside
  `ui/Page`. Setup pages (Profile, Resume, Template, Vocabulary, Job sources) use one
  centred column; Tailor, Apply, Settings and the setup wizard run full width (the main
  area has no max width, so wide windows don't leave a blank right side). The shell
  (`components/shell/`: `AppRail`, `StatusBar`) owns navigation, the theme row, the
  window title and only what needs attention (setup steps left, an update); Pause
  automation sits in Apply's command bar. Under it, the progress banner (`pages/apply/progress/`, numbers from
  `/api/applications/progress` worked out in `lib/applyProgress.ts`) shows the weekly goal, the
  13-week activity heatmap or the pipeline, chosen per profile in Apply settings › Progress banner. Success/info toasts show in the status bar; errors stay toasts.
  Don't hand-roll page widths or title sizes.
- Polling goes through `lib/adaptivePoll.ts` / `conditionalGet` (in `api/core.ts`); errors through
  `lib/errors.ts`; toasts through `lib/toast.ts`.
- Visual language (tokens, fonts, primitives, status marks, selected state): `docs/design.md`;
  the approved target to match is `docs/design/reference.html`. Use `components/ui`
  primitives; never hand-build tiles, buttons or status pills. Settings-like pages
  (Settings, Vocabulary, Job sources, the Apply list) wrap their tiles in `TileLayout`
  "flat" so they read as rows; Profile and the setup wizard keep boxed tiles, like the
  Resume page; `SettingRow` lives in `components/ui/`.
- Don't re-propose declined features: per-stage model overrides, hybrid routing,
  always-on repair toggles, run history.

## Template switching and resume review

Template state commits one `/api/template/state` snapshot; obsolete requests cannot overwrite it. `TemplatePreview` fetches the exact revision and discards old PDF responses. Ordinary saved/starter activation skips calibration. Tailor and Apply show `ResumeQualityNotice`; Fill confirms flagged resumes using their current revision. After bullet edits, refresh both document previews and quality reports. Settings has four tabs (AI model, Data & backups, Browser extension, About); the theme is a rail row and notifications are in Apply settings. The master resume has its own page, `/resume` (Ctrl+3); Profile keeps Personal information, Application details and Tailoring, and old `/profile/resume` links redirect. Its structural edits (add, remove, move) undo with Ctrl+Z / Ctrl+Shift+Z outside text fields (`lib/undoStack.ts`, `pages/editor/useResumeUndo.ts`); a step puts back the structure only (`restoreStructure`), so text edited since stays; the last step shows in the status bar with Undo/Redo. Page shortcuts are markers: Ctrl+S presses `data-shortcut="save"` (after blurring, so buffered fields commit), and "/" or, in the desktop app, Ctrl+F focuses `data-shortcut="search"`. Ctrl+K lists every page plus what the open page offers: a component adds its actions with `useCommands` (`state/commandState.tsx`, matched by `lib/commands.ts`), the shell adds navigation, theme, print and Reload window (`components/shell/useAppCommands.ts`); a command the page cannot run right now is `disabled`, not left out of the builder. The palette looks a command up again when it runs it (opening it commits a buffered field, so the listed closure can be stale). Light and Heavy task models are app-wide (`app_settings.py`); one AI models tile (`ModelsCard`, a `ModelRow` per role) picks provider, model and plan (Free / Pay as you go / API subscription / On this computer; it sets that server's default request concurrency), shows a custom server's format and URL inline, and connections are tested automatically (`useRoleModel` → `pages/settings/useModelCheck.ts`). Every API key is one combined list (`ModelKeysCard` over `ApiKeysCard`); a role on a custom server gets its key as a block at the top of that list. Onboarding uses the same tile and lists only the needed keys. Light handles tailoring and app tools; Heavy handles autofill and application answers. Custom credentials are bound to role, API format and URL. Advanced is a switch in the AI models tile header (`advanced` prop; hidden in onboarding) that reveals `AiAdvancedSettings` inside the tile; each control sits beside its label (`SettingRow` `split`, label column `ROW_LABEL_COLUMN`, shared with `ModelRow`). Each model row's chip shows the provider's rate limit (`lib/modelLimits.ts`, from `/api/model-queue` `roles`). Reasoning effort is Recommended | Custom per step (`EffortSetting`, `lib/effortSteps.ts`). Request concurrency presets control shared limits (Balanced = local 1, cloud 3), with collapsed per-server overrides in Custom; Resumes at once goes up to 8. Tailor: the posting with Tailor resume under it, then the options, on the left; the document on the right, split 5:5 so both grow with the window (`lib/viewer.ts` `BESIDE_DOCUMENT`, shared with an application's page; no zoom/fit controls); History is a second, full-width view (`?view=history`) and opening a run returns to Tailor. Profile is laid out like the Resume page: its sections in a list down the left, boxed tiles on the right. The setup wizard has its step list on the left and a sticky Back/Skip/Next bar under each step. The Template page is v1.17.0's layout: one tile with the document on the left and, on the right, the Resume | Cover letter switch and Refresh over that view's tools (`components/template/workspace/`, `?view=cover`), then page fit and the library; each view shows only its own tools, and cover-letter settings save as they change (`lib/useCoverAutosave.ts`). Quick adjustments is a mode of the Resume view (`components/template/adjust/AdjustMode.tsx`): a debounced live draft preview (`lib/useAdjustPreview.ts`, latest wins, 409 = superseded) beside the settings; Apply installs directly via `lib/useQuickAdjust.ts`.
