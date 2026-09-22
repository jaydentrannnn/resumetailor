import {
  type AppConfig,
  type JobSettings,
  type RunReport,
} from "../api";
import { DocumentsCard } from "../components/DocumentsCard";
import { ExperienceCard } from "../components/ExperienceCard";
import { Field, Toggle } from "../components/Field";
import { IncludePanel } from "../components/IncludePanel";
import { RunHistoryPanel } from "../components/RunHistoryPanel";
import { StylePromptField } from "../components/StylePromptField";
import { SkillsCard } from "../components/SkillsCard";
import { type RunProgress, runProgress } from "../lib/runProgress";
import { DEFAULT_SETTINGS, useRunState } from "../state/runState";
import { useWorkspaceState } from "../state/workspaceState";
import { useEffect, useId, useMemo, useRef, useState } from "react";

/**
 * Main run page: paste a JD, adjust settings, watch progress, download results.
 *
 * State lives in `RunProvider` so switching to Master resume mid-run does not
 * lose the JD, settings, SSE stream, or results. PDF auto-download is also
 * owned there so a tab remount cannot re-fire it.
 *
 * Layout at `lg` is an explicit grid: Run options and What-to-include share
 * row 1 (set once, then left alone), Job description and Progress sit on row 2
 * — the primary input and its feedback — the submit button spans both columns
 * on row 3, then results / preview / history. Source order matches this on
 * mobile too, where the grid collapses to one column and row-start has no
 * effect. Placement is stated per tile (`col-start`/`row-start`) because
 * several tiles render conditionally — auto-flow would reshuffle the rest the
 * moment one disappeared.
 */
export function RunPage() {
  const {
    config,
    jdText,
    setJdText,
    settings,
    setSettings,
    jobId,
    status,
    events,
    report,
    expansion,
    skills,
    coverLetter,
    setCoverLetter,
    error,
    busy,
    queuePosition,
    settingsLoaded,
    startJob,
    cancelRun,
    cancelling,
  } = useRunState();
  const { switching } = useWorkspaceState();

  const progressListRef = useRef<HTMLOListElement>(null);
  const progress = useMemo(
    () => runProgress(events, status, busy),
    [events, status, busy],
  );
  const elapsed = useElapsedSeconds(busy);

  useEffect(() => {
    /** Keep the progress list pinned to its newest row as events stream in. */
    const el = progressListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events]);

  async function onSubmit(e: React.FormEvent) {
    /** Start a new job from the current JD text and settings. */
    e.preventDefault();
    await startJob();
  }

  function onFormKeyDown(e: React.KeyboardEvent<HTMLFormElement>) {
    /** Enter in a text/number field must not implicitly submit the whole
     * Run-options form (Pages, Experience entries, Model name, …). Textareas,
     * selects, and buttons are unaffected. */
    if (e.key === "Enter" && (e.target as HTMLElement).tagName === "INPUT") {
      e.preventDefault();
    }
  }

  function onFile(file: File | null) {
    /** Load a .txt job description from disk into the paste area. */
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setJdText(String(reader.result ?? ""));
    reader.readAsText(file);
  }

  // Progress and the calibration note share one cell and are mutually exclusive:
  // a failed run leaves `error` set with `busy` false, which used to render both
  // stacked. Only one can occupy the pinned tile.
  const showStatus = busy || events.length > 0 || Boolean(error) || Boolean(report);

  return (
    <form
      onSubmit={onSubmit}
      onKeyDown={onFormKeyDown}
      className="grid grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-[1.1fr_0.9fr]"
    >
      <h1 className="sr-only">Tailor resume</h1>

      <div className="lg:col-start-1 lg:row-start-1">
        {/* Native fieldset disabling: blocks every descendant control until
            settings finish loading, so no edit can race the initial fetch and
            get silently overwritten when it resolves. `display: contents` keeps
            it out of the grid/flex layout. */}
        <fieldset disabled={!settingsLoaded} className="contents">
          <SettingsPanel config={config} settings={settings} onChange={setSettings} />
        </fieldset>
      </div>

      <div className="lg:col-start-2 lg:row-start-1">
        <fieldset disabled={!settingsLoaded} className="contents">
          <IncludePanel settings={settings} onChange={setSettings} />
        </fieldset>
      </div>

      {/* Job description is the primary input — it and its Progress feedback sit
          on row 2 at `lg`, after the settings panels. */}
      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm lg:col-start-1 lg:row-start-2">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-display text-xl font-semibold">Job description</h2>
          <label className="cursor-pointer rounded-md border border-line px-3 py-1.5 text-sm text-ink-muted hover:border-accent hover:text-accent">
            Upload .txt
            <input
              type="file"
              accept=".txt,text/plain"
              className="hidden"
              onChange={(e) => onFile(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>
        <textarea
          value={jdText}
          onChange={(e) => setJdText(e.target.value)}
          rows={14}
          placeholder="Paste the posting here…"
          className="w-full resize-y rounded-lg border border-line bg-paper/40 px-3 py-2 text-sm leading-relaxed focus:border-accent"
          required
        />
      </section>

      {/*
        The progress tile is absolutely positioned inside this cell at `lg`, so it
        contributes no height of its own: row 2 is sized by the job-description tile
        alone and `inset-0` then stretches progress to exactly that height, in both
        directions and through a manual textarea resize. The event list takes the
        slack (`flex-1 min-h-0`) and scrolls rather than growing the row. Static on
        mobile, where the grid collapses to one column.
      */}
      <div className="lg:relative lg:col-start-2 lg:row-start-2">
        {showStatus ? (
          <section className="rounded-xl border border-line bg-panel p-5 shadow-sm lg:absolute lg:inset-0 lg:flex lg:flex-col lg:overflow-hidden">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="font-display text-xl font-semibold">Progress</h2>
              <div className="flex items-center gap-3">
                <span
                  className="text-sm text-ink-muted tabular-nums"
                  role="status"
                  aria-live="polite"
                >
                  {progress.label}
                  {busy && elapsed > 0
                    ? ` · watching ${formatElapsed(elapsed)}`
                    : busy
                      ? " · watching…"
                      : ""}
                </span>
                {busy && (
                  <button
                    type="button"
                    onClick={() => void cancelRun()}
                    disabled={cancelling}
                    className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink-muted hover:border-danger hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {cancelling ? "Cancelling…" : "Cancel"}
                  </button>
                )}
              </div>
            </div>
            <ProgressBar progress={progress} failed={status === "failed"} />
            {queuePosition != null && queuePosition > 1 && status === "queued" && (
              <p className="mt-2 text-sm text-ink-muted">
                Queued — position {queuePosition}
              </p>
            )}
            <ol
              ref={progressListRef}
              className="mt-3 max-h-56 space-y-2 overflow-y-auto text-sm lg:max-h-none lg:min-h-0 lg:flex-1"
            >
              {events.map((ev, i) => (
                <li key={`${ev.stage}-${i}`} className="flex gap-2">
                  <span className="mt-0.5 shrink-0 rounded bg-accent-soft px-1.5 py-0.5 text-micro font-semibold uppercase tracking-wide text-accent">
                    {ev.stage}
                  </span>
                  <span>{ev.message}</span>
                </li>
              ))}
            </ol>
            {error && (
              <p
                role="alert"
                className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
              >
                {error}
              </p>
            )}
          </section>
        ) : (
          config && (
            <section className="rounded-xl border border-dashed border-line bg-panel/60 p-4 text-sm text-ink-muted">
              <p>
                Measuring with <strong className="text-ink">{config.pdf_backend}</strong>
                {config.calibration_source === "fallback"
                  ? " (using built-in fit constants)"
                  : " (calibrated)"}
                . {config.chars_per_line} chars/line · {config.lines_per_page} lines/page.
              </p>
              {config.calibration_rejection && (
                <p className="mt-2 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
                  {config.calibration_rejection}
                </p>
              )}
              {config.contact_name && (
                <p className="mt-2">Master resume: {config.contact_name}</p>
              )}
            </section>
          )
        )}
      </div>

      <button
        type="submit"
        disabled={busy || !jdText.trim() || !settingsLoaded || switching}
        className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-on-accent transition-[filter] duration-[var(--dur-short)] ease-out hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 lg:col-start-1 lg:col-span-2 lg:row-start-3"
      >
        {busy
          ? "Tailoring…"
          : switching
            ? "Switching profile…"
            : !settingsLoaded
              ? "Loading settings…"
              : "Tailor resume"}
      </button>

      {report && jobId && expansion && (
        <div className="lg:col-start-1 lg:col-span-2 lg:row-start-4">
          <ExperienceCard expansion={expansion} jobId={jobId} />
        </div>
      )}

      {report && jobId && skills && (
        <div className="lg:col-start-1 lg:row-start-5">
          <SkillsCard plan={skills} gaps={report.gaps} jobId={jobId} />
        </div>
      )}

      {report && jobId && (
        <div
          className={
            skills
              ? "lg:col-start-2 lg:row-start-5"
              : "lg:col-start-1 lg:col-span-2 lg:row-start-5"
          }
        >
          <ReportCard report={report} />
        </div>
      )}

      {report && jobId && (
        <div className="lg:col-start-1 lg:col-span-2 lg:row-start-6">
          <DocumentsCard
            jobId={jobId}
            coverLetter={coverLetter}
            onCoverRegenerated={setCoverLetter}
          />
        </div>
      )}

      <RunHistoryPanel />
    </form>
  );
}

/**
 * Seconds elapsed since `active` last became true, ticking every second while it
 * stays true and resetting to 0 once it goes false. A reload that re-attaches to an
 * already-running job restarts this at 0 — it measures how long *this browser tab*
 * has been watching the run, not the job's true server-side age (not tracked
 * client-side today).
 */
function useElapsedSeconds(active: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      startRef.current = null;
      setElapsed(0);
      return;
    }
    startRef.current = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => {
      if (startRef.current != null) {
        setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [active]);

  return elapsed;
}

/** e.g. 45 -> "45s", 125 -> "2m 05s". */
function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

function ProgressBar({
  progress,
  failed,
}: {
  progress: RunProgress;
  failed: boolean;
}) {
  /**
   * The run's position in the pipeline. Indeterminate only before the first stage
   * event lands — after that `runProgress` always has a band to sit in.
   */
  const pct = Math.round(progress.value * 100);
  return (
    <div
      role="progressbar"
      aria-label="Tailoring progress"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={progress.indeterminate ? undefined : pct}
      aria-valuetext={progress.label}
      className="mt-3 h-1.5 overflow-hidden rounded-full bg-paper/80"
    >
      <div
        className={
          failed
            ? "h-full rounded-full bg-danger"
            : progress.indeterminate
              ? "rt-progress-indeterminate h-full w-1/3 rounded-full bg-accent [animation:rt-progress-slide_1.2s_var(--ease-in-out)_infinite]"
              : "h-full rounded-full bg-accent transition-[width] duration-500 ease-out"
        }
        style={progress.indeterminate ? undefined : { width: `${pct}%` }}
      />
    </div>
  );
}

function SettingsPanel({
  config,
  settings,
  onChange,
}: {
  config: AppConfig | null;
  settings: JobSettings;
  onChange: (s: JobSettings) => void;
}) {
  /** Grouped run knobs mirroring the CLI flags, with short help under each control. */
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const advancedId = useId();

  function set<K extends keyof JobSettings>(key: K, value: JobSettings[K]) {
    onChange({ ...settings, [key]: value });
  }

  /** Parse a number-input's raw string, clamped to [min, max]. Returns `undefined`
   * for an empty or unparseable value so the caller can skip the write entirely —
   * `Number("")` is `0`, which would otherwise silently persist and 422 on save. */
  function parseClamped(raw: string, min: number, max: number): number | undefined {
    if (raw.trim() === "") return undefined;
    const n = Number(raw);
    if (!Number.isFinite(n)) return undefined;
    return Math.min(max, Math.max(min, Math.round(n)));
  }

  function resetDefaults() {
    onChange({
      ...DEFAULT_SETTINGS,
      pages: config?.pages ?? DEFAULT_SETTINGS.pages,
      experience: config?.experience ?? 3,
      projects: config?.projects ?? 2,
    });
  }

  const fillValue = settings.fill_target ?? config?.fill_target ?? 0.93;
  const initialShareValue = settings.initial_bullet_share ?? config?.initial_bullet_share ?? 1;
  const experienceShareValue =
    settings.experience_bullet_share ?? config?.experience_bullet_share ?? 0.65;

  // Which profiles route a stage to Ollama comes from the server, not a hardcoded
  // ["ollama"] — MODEL_PROFILES is free to change without this going stale. Fall back
  // to a name check only while /api/config is still in flight.
  const usesOllama = config
    ? config.ollama_profiles.includes(settings.model)
    : settings.model === "ollama";
  const usesGemini = config
    ? config.gemini_profiles.includes(settings.model)
    : settings.model === "gemini";
  // `provider_keys` holds booleans only, never the key itself — this just decides
  // whether to show the warning before a run fails deep in the job queue.
  const missingGeminiKey = usesGemini && config?.provider_keys.gemini === false;
  // `hybrid` is hidden from the dropdown below (one provider per run covers every
  // real use case here) but kept selectable if a saved settings.json already has it,
  // so the <select> doesn't render with no matching option.
  const modelProfileOptions = (
    config?.model_profiles ?? ["claude", "ollama", "lmstudio", "gemini"]
  ).filter((p) => p !== "hybrid" || p === settings.model);

  /** Placeholder for the blanket model override — mirrors the profile's default tag. */
  function profileModelPlaceholder(): string {
    if (!config) return "e.g. gemma4:cloud";
    if (config.ollama_profiles.includes(settings.model)) return config.ollama_model;
    if (config.gemini_profiles.includes(settings.model)) return config.gemini_model;
    if (settings.model === "claude") return "claude-sonnet-5";
    if (settings.model === "lmstudio") return "local-model";
    return "provider:model";
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-xl font-semibold">Run options</h2>
        <button
          type="button"
          onClick={resetDefaults}
          className="text-xs text-ink-muted underline-offset-2 hover:text-accent hover:underline"
        >
          Reset to defaults
        </button>
      </div>

      <fieldset className="mt-4 space-y-3">
        <legend className="text-sm font-semibold text-ink">Output</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Pages" help="Target page count for the tailored resume.">
            <input
              type="number"
              min={1}
              max={5}
              value={settings.pages}
              onChange={(e) => {
                const next = parseClamped(e.target.value, 1, 5);
                if (next !== undefined) set("pages", next);
              }}
              className="field"
            />
          </Field>
          <Field
            label="Experience entries"
            help="Max work experience roles to keep (ranked by relevance)."
          >
            <input
              type="number"
              min={1}
              max={10}
              value={settings.experience ?? config?.experience ?? 3}
              onChange={(e) => {
                const next = parseClamped(e.target.value, 1, 10);
                if (next !== undefined) set("experience", next);
              }}
              className="field"
            />
          </Field>
          <Field
            label="Project entries"
            help="Max projects to keep (ranked separately from experience)."
          >
            <input
              type="number"
              min={1}
              max={10}
              value={settings.projects ?? config?.projects ?? 2}
              onChange={(e) => {
                const next = parseClamped(e.target.value, 1, 10);
                if (next !== undefined) set("projects", next);
              }}
              className="field"
            />
          </Field>
        </div>
        <Toggle
          label="Generate cover letter"
          help="Off by default. Drafts a cover letter from the tailored resume and this posting, then renders it as .docx and .pdf beside the resume."
          checked={settings.cover_letter}
          onChange={(v) => set("cover_letter", v)}
        />
        {settings.cover_letter && (
          <div className="space-y-3 rounded-md border border-line/80 bg-paper/40 p-3">
            <p className="text-xs text-ink-muted">
              Optional angles — durable per-application inputs (cached and guarded). Leave
              blank for the default letter.
            </p>
            <Field label="Why this company">
              <textarea
                value={settings.cover_angles.why_company}
                onChange={(e) =>
                  set("cover_angles", {
                    ...settings.cover_angles,
                    why_company: e.target.value,
                  })
                }
                rows={2}
                className="field"
              />
            </Field>
            <Field label="Problem to solve">
              <textarea
                value={settings.cover_angles.problem}
                onChange={(e) =>
                  set("cover_angles", {
                    ...settings.cover_angles,
                    problem: e.target.value,
                  })
                }
                rows={2}
                className="field"
              />
            </Field>
            <Field label="Your approach">
              <textarea
                value={settings.cover_angles.approach}
                onChange={(e) =>
                  set("cover_angles", {
                    ...settings.cover_angles,
                    approach: e.target.value,
                  })
                }
                rows={2}
                className="field"
              />
            </Field>
            <Field label="Tone">
              <select
                value={settings.cover_angles.tone}
                onChange={(e) =>
                  set("cover_angles", {
                    ...settings.cover_angles,
                    tone: e.target.value as JobSettings["cover_angles"]["tone"],
                  })
                }
                className="field"
              >
                <option value="">Default</option>
                <option value="formal">Formal</option>
                <option value="direct">Direct</option>
                <option value="conversational">Conversational</option>
                <option value="mirror">Mirror the posting</option>
              </select>
            </Field>
          </div>
        )}
      </fieldset>

      <fieldset className="mt-6 space-y-3">
        <legend className="text-sm font-semibold text-ink">Models</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Model profile"
            help={
              usesOllama && config
                ? `Ollama stages use ${config.ollama_model} at ${config.ollama_base_url}.`
                : usesGemini && config
                  ? `Gemini stages use ${config.gemini_model} at ${config.gemini_base_url}.`
                  : "claude, ollama, gemini, or a custom provider:model spec."
            }
          >
            <select
              value={settings.model}
              onChange={(e) => set("model", e.target.value)}
              className="field"
            >
              {modelProfileOptions.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            {missingGeminiKey && (
              <p className="mt-1 rounded-md bg-danger-soft px-2 py-1 text-xs text-danger">
                No Gemini API key found. Set GEMINI_API_KEY in .env before running.
              </p>
            )}
          </Field>
          <Field label="Effort" help="Reasoning depth for every stage. Blank uses per-stage defaults.">
            <select
              value={settings.effort ?? ""}
              onChange={(e) =>
                set("effort", (e.target.value || null) as JobSettings["effort"])
              }
              className="field"
            >
              <option value="">Per-stage defaults</option>
              {(config?.effort_options ?? ["low", "medium", "high"]).map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Model name (optional)"
            help="Override the model for every stage of the selected profile. Leave blank to use the profile default."
          >
            <input
              type="text"
              value={settings.model_name ?? ""}
              onChange={(e) => set("model_name", e.target.value || null)}
              placeholder={profileModelPlaceholder()}
              className="field"
            />
          </Field>
        </div>
      </fieldset>

      <div className="mt-6">
        <button
          type="button"
          onClick={() => setAdvancedOpen((o) => !o)}
          aria-expanded={advancedOpen}
          aria-controls={advancedId}
          className="text-sm font-semibold text-ink hover:text-accent"
        >
          Advanced {advancedOpen ? "▾" : "▸"}
        </button>
        {advancedOpen && (
          <fieldset id={advancedId} className="mt-3 space-y-3">
            <Field
              label={`Page fill target (${Math.round(fillValue * 100)}%)`}
              help="Grow when measured fill is below this. Lower = sparser page, fewer rewrites."
            >
              <input
                type="range"
                min={80}
                max={95}
                step={1}
                value={Math.round(fillValue * 100)}
                onChange={(e) => set("fill_target", Number(e.target.value) / 100)}
                className="w-full accent-[var(--color-accent)]"
              />
            </Field>
            <Field
              label={`First-draft bullets (${Math.round(initialShareValue * 100)}%)`}
              help="Cap the opening selection to this share of available bullets. Lower starts sparser — but the page fill target above may still grow it back, so lower both to end sparser."
            >
              <input
                type="range"
                min={30}
                max={100}
                step={5}
                value={Math.round(initialShareValue * 100)}
                onChange={(e) => set("initial_bullet_share", Number(e.target.value) / 100)}
                className="w-full accent-[var(--color-accent)]"
              />
            </Field>
            <Toggle
              label="Weight bullets toward experience"
              help="Budget experience and projects separately instead of one shared pool, where a keyword-dense project can otherwise out-rank every job."
              checked={settings.experience_bullet_share !== null}
              onChange={(v) => set("experience_bullet_share", v ? 0.65 : null)}
            />
            {settings.experience_bullet_share !== null && (
              <Field
                label={`${Math.round(experienceShareValue * 100)}% experience / ${100 - Math.round(experienceShareValue * 100)}% projects`}
              >
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={Math.round(experienceShareValue * 100)}
                  onChange={(e) => set("experience_bullet_share", Number(e.target.value) / 100)}
                  className="w-full accent-[var(--color-accent)]"
                />
              </Field>
            )}
            <Field
              label="Max bullets per entry"
              help="Cap on how many bullets any single job or project may take."
            >
              <select
                value={settings.max_bullets_per_entry ?? ""}
                onChange={(e) =>
                  set(
                    "max_bullets_per_entry",
                    e.target.value === "" ? null : Number(e.target.value),
                  )
                }
                className="field"
              >
                <option value="">No limit</option>
                {[2, 3, 4, 5, 6].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </Field>
            <Toggle
              label="Merge redundant bullets"
              help="Only after a measured page overflow; combines near-duplicate lines."
              checked={settings.merge}
              onChange={(v) => set("merge", v)}
            />
            <Toggle
              label="Bypass cache"
              help="Re-extract JD and re-score bullets instead of reusing cached files."
              checked={settings.no_cache}
              onChange={(v) => set("no_cache", v)}
            />
            <Toggle
              label="Skip experience expansion"
              help="Do not generate application-form paste text after a successful fit."
              checked={settings.no_expand}
              onChange={(v) => set("no_expand", v)}
            />
            <Toggle
              label="Skip skills list"
              help="Do not generate the tailored skills list for application-form Skills fields."
              checked={settings.no_skills}
              onChange={(v) => set("no_skills", v)}
            />
            <Toggle
              label="Skip tech / coursework selection"
              help="Do not ask the model which project tags and courses to show; truncate pools in listed order to fit the line budgets."
              checked={settings.no_facets}
              onChange={(v) => set("no_facets", v)}
            />
            <Toggle
              label="Suggest vocabulary from this run"
              help="One extra call after a successful run: drafts tag-alias/verb suggestions from this posting's own keyword gaps for review on the Settings tab. Uses this run's own backend."
              checked={settings.suggest_vocabulary}
              onChange={(v) => set("suggest_vocabulary", v)}
            />
            <StylePromptField
              label="Resume bullet style"
              help="Voice and emphasis rules for resume bullet rewriting. Length and verb variety are also enforced in code by widow and verb repair passes."
              value={settings.rewrite_style}
              defaultText={config?.rewrite_style_default ?? ""}
              lockedCoreRules={config?.rewrite_core_rules ?? ""}
              onChange={(text) => {
                if (text === null) {
                  set("rewrite_style", null);
                  return;
                }
                const trimmed = text.trim();
                if (!trimmed || trimmed === config?.rewrite_style_default?.trim()) {
                  set("rewrite_style", null);
                } else {
                  set("rewrite_style", text);
                }
              }}
            />
            <StylePromptField
              label="Application-form expansion style"
              help="Voice rules for the longer experience descriptions pasted into application forms."
              value={settings.expand_style}
              defaultText={config?.expand_style_default ?? ""}
              lockedCoreRules={config?.expand_core_rules ?? ""}
              onChange={(text) => {
                if (text === null) {
                  set("expand_style", null);
                  return;
                }
                const trimmed = text.trim();
                if (!trimmed || trimmed === config?.expand_style_default?.trim()) {
                  set("expand_style", null);
                } else {
                  set("expand_style", text);
                }
              }}
            />
            <StylePromptField
              label="Cover letter style"
              help="Voice and structure rules for the cover letter body paragraphs."
              value={settings.cover_style}
              defaultText={config?.cover_style_default ?? ""}
              lockedCoreRules={config?.cover_core_rules ?? ""}
              onChange={(text) => {
                if (text === null) {
                  set("cover_style", null);
                  return;
                }
                const trimmed = text.trim();
                if (!trimmed || trimmed === config?.cover_style_default?.trim()) {
                  set("cover_style", null);
                } else {
                  set("cover_style", text);
                }
              }}
            />
          </fieldset>
        )}
      </div>

    </section>
  );
}

function ReportCard({ report }: { report: RunReport }) {
  /** End-of-run summary cards mirroring the CLI report. */
  const diagnosis = report.extraction_diagnosis;
  const pct =
    diagnosis == null && report.coverage_total > 0
      ? Math.round((100 * report.coverage_matched) / report.coverage_total)
      : null;
  const mustHaveValue = diagnosis
    ? "inconclusive"
    : pct != null
      ? `${pct}%`
      : "n/a";
  const mustHaveSub = diagnosis
    ? diagnosis.replaceAll("_", " ")
    : `${report.coverage_matched}/${report.coverage_total}`;

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div>
        <h2 className="font-display text-xl font-semibold">{report.title}</h2>
        <p className="text-sm text-ink-muted">{report.seniority}</p>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm tabular-nums sm:grid-cols-5">
        <Stat
          label="Must-haves"
          value={mustHaveValue}
          sub={mustHaveSub}
        />
        <Stat
          label="Pages"
          value={String(report.pages)}
          sub={report.pages_are_estimated ? "estimated" : `${report.iterations} iter`}
        />
        <Stat
          label="Bullets"
          value={`${report.bullets_selected}`}
          sub={`of ${report.bullets_total}`}
        />
        <Stat
          label="Widows"
          value={String(report.widows_remaining)}
          sub={report.widows_repaired ? `${report.widows_repaired} fixed` : "none fixed"}
        />
        <Stat
          label="Verb repeats"
          value={String(report.verb_collisions_remaining)}
          sub={
            report.verbs_diversified
              ? `${report.verbs_diversified} fixed`
              : "none fixed"
          }
        />
      </dl>

      {(() => {
        const bandRank: Record<string, number> = {
          critical: 4,
          high: 3,
          meaningful: 2,
          preferred: 1,
          low_signal: 0,
        };
        const byBand = (a: (typeof report.gaps)[number], b: (typeof report.gaps)[number]) =>
          (bandRank[b.band ?? "meaningful"] ?? 0) - (bandRank[a.band ?? "meaningful"] ?? 0);
        const annotate = (g: (typeof report.gaps)[number]) =>
          g.band
            ? `${g.phrase} (${g.band}${g.evidence_tier ? `, ${g.evidence_tier}` : ""})`
            : g.phrase;
        const noEvidence = report.gaps
          .filter((g) => g.reason === "no_evidence")
          .slice()
          .sort(byBand);
        const otherGaps = report.gaps
          .filter((g) => g.reason !== "no_evidence")
          .slice()
          .sort(byBand);
        const gapCount =
          (report.missing_must_haves.length > 0 ? 1 : 0) +
          (report.unmatched_canonicals.length > 0 ? 1 : 0) +
          noEvidence.length +
          otherGaps.length;
        if (gapCount === 0) return null;
        return (
          <details className="mt-3 rounded-md border border-line/80 bg-paper/40 open:pb-2">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">
              Coverage gaps ({gapCount})
            </summary>
            <div className="space-y-2 px-3 pb-1 text-sm">
              {report.missing_must_haves.length > 0 && (
                <p className="rounded-md bg-warn-soft px-3 py-2 text-warn">
                  Not supported by master resume: {report.missing_must_haves.join(", ")}
                </p>
              )}
              {report.unmatched_canonicals.length > 0 && (
                <p className="text-ink-muted">
                  Matched no tag: {report.unmatched_canonicals.map(([c]) => c).join(", ")}
                </p>
              )}
              {noEvidence.length > 0 && (
                <p className="rounded-md bg-warn-soft px-3 py-2 text-warn">
                  No evidence in the master resume:{" "}
                  {noEvidence.map(annotate).join(", ")}
                </p>
              )}
              {otherGaps.map((g) => (
                <p key={g.canonical} className="text-ink-muted">
                  {g.reason === "untagged_evidence"
                    ? `${annotate(g)}: evidence exists but no bullet is tagged for it (${g.evidence.join("; ")})`
                    : `${annotate(g)}: tagged under a different name (${g.evidence.join("; ")})`}
                </p>
              ))}
            </div>
          </details>
        );
      })()}

      <div className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <EntryList title="Experience" entries={report.experience} />
        <EntryList title="Projects" entries={report.projects} />
      </div>

      {(() => {
        const warnCount =
          report.dropped.length +
          report.warnings.length +
          (report.calibration_rejection ? 1 : 0);
        if (warnCount === 0) return null;
        return (
          <details className="mt-3 rounded-md border border-line/80 bg-paper/40 open:pb-2">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">
              Run warnings ({warnCount})
            </summary>
            <div className="space-y-2 px-3 pb-1 text-sm">
              {report.dropped.length > 0 && (
                <p className="text-ink-muted">Dropped: {report.dropped.join(", ")}</p>
              )}
              {report.warnings.map((w) => (
                <p key={w} className="rounded-md bg-warn-soft px-3 py-2 text-warn">
                  {w}
                </p>
              ))}
              {report.calibration_rejection && (
                <p className="rounded-md bg-warn-soft px-3 py-2 text-warn">
                  {report.calibration_rejection}
                </p>
              )}
            </div>
          </details>
        );
      })()}

      <p className="mt-3 text-xs text-ink-muted">
        Model: {report.model} · ranking:{" "}
        {report.semantic_used ? "keyword + semantic" : "keyword only"} · PDF:{" "}
        {report.pdf_backend}
        {report.calibration_source === "fallback" ? " (fallback calibration)" : ""}
      </p>
    </section>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg bg-paper/60 px-3 py-2">
      <dt className="text-xs uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="font-display text-2xl font-semibold">{value}</dd>
      <dd className="text-xs text-ink-muted">{sub}</dd>
    </div>
  );
}

function EntryList({
  title,
  entries,
}: {
  title: string;
  entries: { label: string; kept: number; total: number; rewritten: number }[];
}) {
  if (!entries.length) return null;
  return (
    <div>
      <h3 className="font-medium">{title}</h3>
      <ul className="mt-1 space-y-1 text-ink-muted">
        {entries.map((e) => (
          <li key={e.label}>
            {e.label}: {e.kept}/{e.total}, {e.rewritten} rewritten
          </li>
        ))}
      </ul>
    </div>
  );
}
