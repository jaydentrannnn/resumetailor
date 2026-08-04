import {
  type AppConfig,
  type JobSettings,
  type RunReport,
  downloadPdfUrl,
  downloadUrl,
} from "../api";
import { ExperienceCard } from "../components/ExperienceCard";
import { IncludePanel } from "../components/IncludePanel";
import { ModelSpecField } from "../components/ModelSpecField";
import { type RunProgress, runProgress } from "../lib/runProgress";
import { DEFAULT_SETTINGS, useRunState } from "../state/runState";
import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Main run page: paste a JD, adjust settings, watch progress, download results.
 *
 * State lives in `RunProvider` so switching to Master resume mid-run does not
 * lose the JD, settings, SSE stream, or results. PDF auto-download is also
 * owned there so a tab remount cannot re-fire it.
 *
 * Layout at `lg` is an explicit 2x4 grid rather than stacked columns: Settings
 * and What-to-include sit on row 1, Job description and Progress share row 2
 * (equal height — see the Progress cell below), the submit button spans both
 * columns on row 3, and Application experience / Report share row 4. Placement
 * is stated per tile (`col-start`/`row-start`) because several of the seven
 * tiles render conditionally — auto-flow would reshuffle the rest the moment
 * one of them disappeared.
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
    error,
    busy,
    queuePosition,
    startJob,
  } = useRunState();

  const progressListRef = useRef<HTMLOListElement>(null);
  const progress = useMemo(
    () => runProgress(events, status, busy),
    [events, status, busy],
  );

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
      className="grid gap-x-8 gap-y-5 lg:grid-cols-[1.1fr_0.9fr]"
    >
      <div className="lg:col-start-1 lg:row-start-1">
        <SettingsPanel config={config} settings={settings} onChange={setSettings} />
      </div>

      <div className="lg:col-start-2 lg:row-start-1">
        <IncludePanel settings={settings} onChange={setSettings} />
      </div>

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
          className="w-full resize-y rounded-lg border border-line bg-paper/40 px-3 py-2 text-sm leading-relaxed outline-none focus:border-accent"
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
              <span className="text-sm text-ink-muted">{progress.label}</span>
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
                  <span className="mt-0.5 shrink-0 rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
                    {ev.stage}
                  </span>
                  <span>{ev.message}</span>
                </li>
              ))}
            </ol>
            {error && (
              <p className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}
          </section>
        ) : (
          config && (
            <section className="rounded-xl border border-dashed border-line bg-panel/60 p-5 text-sm text-ink-muted">
              <p>
                Measuring with <strong className="text-ink">{config.pdf_backend}</strong>
                {config.calibration_source === "fallback"
                  ? " (using built-in fit constants)"
                  : " (calibrated)"}
                . {config.chars_per_line} chars/line · {config.lines_per_page} lines/page.
              </p>
              {config.contact_name && (
                <p className="mt-2">Master resume: {config.contact_name}</p>
              )}
            </section>
          )
        )}
      </div>

      <button
        type="submit"
        disabled={busy || !jdText.trim()}
        className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 lg:col-start-1 lg:col-span-2 lg:row-start-3"
      >
        {busy ? "Tailoring…" : "Tailor resume"}
      </button>

      {report && jobId && expansion && (
        <div className="lg:col-start-1 lg:row-start-4">
          <ExperienceCard expansion={expansion} jobId={jobId} />
        </div>
      )}

      {report && jobId && (
        <div className="lg:col-start-2 lg:row-start-4">
          <ReportCard report={report} jobId={jobId} />
        </div>
      )}
    </form>
  );
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
              ? "h-full w-1/3 rounded-full bg-accent [animation:rt-progress-slide_1.2s_ease-in-out_infinite]"
              : "h-full rounded-full bg-accent transition-[width] duration-500 ease-out"
        }
        style={progress.indeterminate ? undefined : { width: `${pct}%` }}
      />
      <style>{`
        @keyframes rt-progress-slide {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(300%); }
        }
      `}</style>
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

  function set<K extends keyof JobSettings>(key: K, value: JobSettings[K]) {
    onChange({ ...settings, [key]: value });
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
  // ["ollama", "hybrid"] — MODEL_PROFILES is free to change without this going stale.
  // Fall back to a name check only while /api/config is still in flight.
  const usesOllama = config
    ? config.ollama_profiles.includes(settings.model)
    : settings.model === "ollama" || settings.model === "hybrid";
  const usesGemini = config
    ? config.gemini_profiles.includes(settings.model)
    : settings.model === "gemini";
  // `provider_keys` holds booleans only, never the key itself — this just decides
  // whether to show the warning before a run fails deep in the job queue.
  const missingGeminiKey = usesGemini && config?.provider_keys.gemini === false;

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-xl font-semibold">Settings</h2>
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
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Pages" help="Target page count for the tailored resume.">
            <input
              type="number"
              min={1}
              max={5}
              value={settings.pages}
              onChange={(e) => set("pages", Number(e.target.value))}
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
              onChange={(e) => set("experience", Number(e.target.value))}
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
              onChange={(e) => set("projects", Number(e.target.value))}
              className="field"
            />
          </Field>
        </div>
      </fieldset>

      <fieldset className="mt-6 space-y-3">
        <legend className="text-sm font-semibold text-ink">Models</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Model profile"
            help={
              usesOllama && config
                ? `Ollama stages use ${settings.ollama_model || config.ollama_model} at ${config.ollama_base_url}.`
                : usesGemini && config
                  ? `Gemini stages use ${settings.gemini_model || config.gemini_model} at ${config.gemini_base_url}.`
                  : "claude, ollama, gemini, hybrid, or a custom provider:model spec."
            }
          >
            <select
              value={settings.model}
              onChange={(e) => set("model", e.target.value)}
              className="field"
            >
              {(
                config?.model_profiles ?? ["claude", "ollama", "lmstudio", "gemini", "hybrid"]
              ).map((p) => (
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
          {usesOllama && (
            <ModelSpecField
              label="Ollama model (optional)"
              value={settings.ollama_model}
              onChange={(v) => set("ollama_model", v)}
              placeholder={config?.ollama_model ?? "e.g. gemma4"}
            />
          )}
          {usesGemini && (
            <ModelSpecField
              label="Gemini model (optional)"
              value={settings.gemini_model}
              onChange={(v) => set("gemini_model", v)}
              placeholder={config?.gemini_model ?? "e.g. gemini-3.5-flash"}
            />
          )}
          <ModelSpecField
            label="Rewrite model (optional)"
            value={settings.rewrite_model}
            onChange={(v) => set("rewrite_model", v)}
            placeholder="e.g. claude-sonnet-5"
          />
          <ModelSpecField
            label="Expand model (optional)"
            value={settings.expand_model}
            onChange={(v) => set("expand_model", v)}
            placeholder="e.g. ollama:gemma4:cloud"
          />
        </div>
      </fieldset>

      <fieldset className="mt-6 space-y-2">
        <legend className="text-sm font-semibold text-ink">Rewriting quality</legend>
        <Toggle
          label="Skip semantic scoring"
          help="Rank on keyword tags only (cheaper; useful for A/B ranking)."
          checked={settings.no_semantic}
          onChange={(v) => set("no_semantic", v)}
        />
        <Toggle
          label="Skip widow repair"
          help="Do not re-cut bullets that wrapped onto a near-empty final line."
          checked={settings.no_widow_repair}
          onChange={(v) => set("no_widow_repair", v)}
        />
        <Toggle
          label="Skip verb variety repair"
          help="Do not revoice colliding opening verbs across bullets."
          checked={settings.no_verb_repair}
          onChange={(v) => set("no_verb_repair", v)}
        />
        <Toggle
          label="Merge redundant bullets"
          help="Only after a measured page overflow; combines near-duplicate lines."
          checked={settings.merge}
          onChange={(v) => set("merge", v)}
        />
      </fieldset>

      <div className="mt-6">
        <button
          type="button"
          onClick={() => setAdvancedOpen((o) => !o)}
          className="text-sm font-semibold text-ink hover:text-accent"
        >
          Advanced {advancedOpen ? "▾" : "▸"}
        </button>
        {advancedOpen && (
          <fieldset className="mt-3 space-y-3">
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
              label="Skip tech / coursework selection"
              help="Do not ask the model which project tags and courses to show; truncate pools in listed order to fit the line budgets."
              checked={settings.no_facets}
              onChange={(v) => set("no_facets", v)}
            />
          </fieldset>
        )}
      </div>

      <style>{`
        .field {
          width: 100%;
          border: 1px solid var(--color-line);
          border-radius: 0.5rem;
          padding: 0.4rem 0.65rem;
          font-size: 0.875rem;
          background: color-mix(in srgb, var(--color-paper) 40%, white);
          outline: none;
        }
        .field:focus { border-color: var(--color-accent); }
      `}</style>
    </section>
  );
}

function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      {children}
      {help && <span className="mt-1 block text-xs text-ink-muted">{help}</span>}
    </label>
  );
}

function Toggle({
  label,
  help,
  checked,
  onChange,
}: {
  label: string;
  help?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 accent-[var(--color-accent)]"
      />
      <span>
        <span className="font-medium">{label}</span>
        {help && <span className="mt-0.5 block text-xs text-ink-muted">{help}</span>}
      </span>
    </label>
  );
}

function ReportCard({ report, jobId }: { report: RunReport; jobId: string }) {
  /** End-of-run summary cards mirroring the CLI report. */
  const pct =
    report.coverage_total > 0
      ? Math.round((100 * report.coverage_matched) / report.coverage_total)
      : null;

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">{report.title}</h2>
          <p className="text-sm text-ink-muted">{report.seniority}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <a
            href={downloadPdfUrl(jobId)}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white"
          >
            .pdf
          </a>
          <a
            href={downloadUrl(jobId)}
            className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:text-accent"
          >
            .docx
          </a>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
        <Stat
          label="Must-haves"
          value={pct != null ? `${pct}%` : "n/a"}
          sub={`${report.coverage_matched}/${report.coverage_total}`}
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

      {report.missing_must_haves.length > 0 && (
        <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
          Not supported by master resume: {report.missing_must_haves.join(", ")}
        </p>
      )}

      {report.unmatched_canonicals.length > 0 && (
        <p className="mt-2 text-sm text-ink-muted">
          Matched no tag: {report.unmatched_canonicals.map(([c]) => c).join(", ")}
        </p>
      )}

      {report.gaps.some((g) => g.reason === "no_evidence") && (
        <p className="mt-2 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
          No evidence in the master resume:{" "}
          {report.gaps
            .filter((g) => g.reason === "no_evidence")
            .map((g) => g.phrase)
            .join(", ")}
        </p>
      )}

      {report.gaps.some((g) => g.reason !== "no_evidence") && (
        <div className="mt-2 text-sm text-ink-muted">
          {report.gaps
            .filter((g) => g.reason === "untagged_evidence")
            .map((g) => (
              <p key={g.canonical}>
                {g.phrase}: evidence exists but no bullet is tagged for it (
                {g.evidence.join("; ")})
              </p>
            ))}
          {report.gaps
            .filter((g) => g.reason === "near_miss")
            .map((g) => (
              <p key={g.canonical}>
                {g.phrase}: tagged under a different name ({g.evidence.join("; ")})
              </p>
            ))}
        </div>
      )}

      <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <EntryList title="Experience" entries={report.experience} />
        <EntryList title="Projects" entries={report.projects} />
      </div>

      {report.dropped.length > 0 && (
        <p className="mt-3 text-sm text-ink-muted">
          Dropped: {report.dropped.join(", ")}
        </p>
      )}

      {report.warnings.map((w) => (
        <p key={w} className="mt-2 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
          {w}
        </p>
      ))}

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
