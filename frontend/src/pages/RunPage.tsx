import {
  type AppConfig,
  type JobSettings,
  type RunReport,
  downloadPdfUrl,
  downloadUrl,
} from "../api";
import { ExperienceCard } from "../components/ExperienceCard";
import { ModelSpecField } from "../components/ModelSpecField";
import { useRunState } from "../state/runState";
import { useState } from "react";

/**
 * Main run page: paste a JD, adjust settings, watch progress, download results.
 *
 * State lives in `RunProvider` so switching to Master resume mid-run does not
 * lose the JD, settings, SSE stream, or results. PDF auto-download is also
 * owned there so a tab remount cannot re-fire it.
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

  return (
    <div className="space-y-8">
      <div className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <form onSubmit={onSubmit} className="space-y-5">
          <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
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

          <SettingsPanel config={config} settings={settings} onChange={setSettings} />

          <button
            type="submit"
            disabled={busy || !jdText.trim()}
            className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Tailoring…" : "Tailor resume"}
          </button>
        </form>

        <aside className="space-y-5">
          {(busy || events.length > 0 || error || report) && (
            <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
              <h2 className="font-display text-xl font-semibold">Progress</h2>
              {queuePosition != null && queuePosition > 1 && status === "queued" && (
                <p className="mt-2 text-sm text-ink-muted">
                  Queued — position {queuePosition}
                </p>
              )}
              <ol className="mt-3 max-h-56 space-y-2 overflow-y-auto text-sm">
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
          )}

          {report && jobId && (
            <ReportCard report={report} jobId={jobId} />
          )}

          {config && !report && !busy && (
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
          )}
        </aside>
      </div>

      {report && jobId && expansion && (
        <ExperienceCard expansion={expansion} jobId={jobId} />
      )}
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
      pages: config?.pages ?? 1,
      experience: config?.experience ?? 3,
      projects: config?.projects ?? 2,
      model: "claude",
      rewrite_model: null,
      expand_model: null,
      effort: null,
      no_semantic: false,
      no_widow_repair: false,
      no_verb_repair: false,
      merge: false,
      no_cache: false,
      no_expand: false,
      no_facets: false,
      no_project_links: false,
      fill_target: null,
    });
  }

  const fillValue = settings.fill_target ?? config?.fill_target ?? 0.93;

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
        <Toggle
          label="Hide project links"
          help="Omit the Github label and hyperlink from project headers."
          checked={settings.no_project_links}
          onChange={(v) => set("no_project_links", v)}
        />
      </fieldset>

      <fieldset className="mt-6 space-y-3">
        <legend className="text-sm font-semibold text-ink">Models</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Model profile" help="claude, ollama, hybrid, or a custom provider:model spec.">
            <select
              value={settings.model}
              onChange={(e) => set("model", e.target.value)}
              className="field"
            >
              {(config?.model_profiles ?? ["claude", "ollama", "lmstudio", "hybrid"]).map(
                (p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ),
              )}
            </select>
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
