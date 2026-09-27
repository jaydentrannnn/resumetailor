import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { AppConfig, JobSettings, SchedulerStatus, SourceConfig } from "../../api";
import { Modal } from "../../components/Modal";
import { Button } from "../../components/ui";
import { autoSubmitCapLabel, autoSubmitSummary } from "../../lib/applyPage";
import { tailorModelLabel } from "../../lib/modelLabel";
import { newWatchlistSource, WATCHLIST_ID } from "../../lib/watchlist";
import { useConfirm } from "../../state/confirmState";
import { AgeWindowPicker } from "./AgeWindowPicker";
import { BrowserCommand, ConnectionStatus } from "./BrowserConnection";
import { CategoryPicker, JobSearchEditor, WatchlistEditor } from "./SourceEditors";

function sourceLabel(source: SourceConfig): string {
  if (source.kind === "ats_board") {
    return source.id === WATCHLIST_ID ? "Company watchlist" : source.id;
  }
  if (source.kind === "job_search") {
    const prov =
      source.provider === "adzuna"
        ? "Adzuna"
        : source.provider === "usajobs"
          ? "USAJobs"
          : "Job search";
    return source.query ? `${prov}: "${source.query}"` : `${prov} search`;
  }
  return source.id;
}

/**
 * Platforms that may auto-submit. Workday, LinkedIn, Indeed, Handshake and SmartRecruiters
 * are absent: they always stop for review (`fill.ASSIST_ONLY_ATS`).
 */
const AUTO_SUBMIT_ATS: { id: string; label: string }[] = [
  { id: "greenhouse", label: "Greenhouse" },
  { id: "lever", label: "Lever" },
  { id: "ashby", label: "Ashby" },
  { id: "icims", label: "iCIMS" },
  { id: "oracle", label: "Oracle" },
];

/**
 * Apply settings in a right-hand drawer: the nightly run first (on/off, time, how much
 * it finds), then what to search, whether and where to auto-submit, the Autofill model,
 * the browser connection and desktop notifications. Every change autosaves through
 * `runState`. One-off search options ("this search only") live beside Find jobs.
 */
export function ApplySettingsDrawer({
  settings,
  setSettings,
  config,
  onClose,
  scheduler,
  dailyRunning,
  onRunNow,
  browserConnected,
  onCheckBrowser,
  notify,
}: {
  settings: JobSettings;
  setSettings: (next: JobSettings) => void;
  config: AppConfig | null;
  onClose: () => void;
  scheduler: SchedulerStatus | null;
  dailyRunning: boolean;
  onRunNow: () => void;
  browserConnected: boolean;
  onCheckBrowser: () => void;
  notify: { enabled: boolean; supported: boolean; onChange: (on: boolean) => void };
}) {
  const { confirm } = useConfirm();
  const apply = settings.apply;
  const patch = (fields: Partial<JobSettings["apply"]>) =>
    setSettings({ ...settings, apply: { ...apply, ...fields } });
  const updateSource = (index: number, next: SourceConfig) =>
    patch({ sources: apply.sources.map((s, i) => (i === index ? next : s)) });
  const allowed = new Set(apply.auto_submit_ats.map((a) => a.toLowerCase()));

  async function toggleAutoSubmit(on: boolean) {
    if (!on) {
      patch({ auto_submit_enabled: false });
      return;
    }
    const ok = await confirm({
      title: "Turn on auto-submit?",
      message: `Applications on the platforms you tick below will be submitted without you seeing them first. Workday always stops for your review. Nightly run: ${autoSubmitCapLabel(apply.auto_submit_max_per_run).toLowerCase()}; at most ${apply.auto_submit_max_per_day} in any 24 hours.`,
      confirmLabel: "Turn on",
      tone: "danger",
    });
    if (ok) patch({ auto_submit_enabled: true });
  }

  return (
    <Modal title="Apply settings" onClose={onClose} placement="right">
      <div className="mt-4 space-y-5 text-sm">
        <Section
          title="Nightly run"
          aside={
            <span
              className={`rounded-full px-2 py-0.5 text-micro font-semibold uppercase tracking-wide ${apply.enabled ? "bg-accent-soft text-accent" : "bg-paper text-ink-muted"}`}
            >
              {apply.enabled ? "On" : "Off"}
            </span>
          }
        >
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 font-medium">
              <input
                type="checkbox"
                role="switch"
                aria-checked={apply.enabled}
                className="h-4 w-4"
                checked={apply.enabled}
                onChange={(e) => patch({ enabled: e.target.checked })}
              />
              Run automatically every day at
            </label>
            <input
              aria-label="Nightly run time"
              type="time"
              className="field inline-block w-32"
              value={apply.schedule_time}
              onChange={(e) => patch({ schedule_time: e.target.value })}
            />
          </div>
          <p className="mt-1 text-xs text-ink-muted">
            It finds new postings and tailors your resume for each. The app must be open (or in the
            tray) at that time.
          </p>
          <fieldset className="mt-3 space-y-2" disabled={!apply.enabled}>
            <label className="block">
              Find up to{" "}
              <input
                className="field mx-1 inline-block w-20"
                type="number"
                min={1}
                max={500}
                aria-label="New postings per nightly run"
                value={apply.max_new_per_day}
                onChange={(e) =>
                  patch({ max_new_per_day: Math.max(1, Number(e.target.value) || 1) })
                }
              />{" "}
              new postings each night
            </label>
            <div>
              <p className="mb-1">Only postings from the last</p>
              <AgeWindowPicker
                ariaLabel="Posting age in days"
                value={apply.max_age_days}
                onChange={(days) => patch({ max_age_days: days })}
              />
              <p className="mt-1 text-xs text-ink-muted">
                A company watchlist keeps its own limit when that one is longer.
              </p>
            </div>
          </fieldset>
          <p className="mt-3 text-xs text-ink-muted">
            Last run: {scheduler?.last_started_at ? formatWhen(scheduler.last_started_at) : "never"}
            {apply.enabled && scheduler?.next_run_at
              ? ` · Next: ${formatWhen(scheduler.next_run_at)}`
              : ""}
          </p>
          {scheduler?.missed_today && (
            <p className="mt-1 text-xs text-warn">
              Today's run was missed because the app was closed.
            </p>
          )}
          {scheduler?.last_error && (
            <p className="mt-1 text-xs text-danger">{scheduler.last_error}</p>
          )}
          <Button className="mt-2" variant="secondary" onClick={onRunNow} disabled={dailyRunning}>
            {dailyRunning ? "Running…" : "Run now"}
          </Button>
        </Section>

        <Section title="What to search">
          <ul className="space-y-2">
            {apply.sources.map((source, index) => (
              <li key={source.id} className="flex items-start gap-2">
                <input
                  id={`source-${source.id}`}
                  type="checkbox"
                  className="mt-1"
                  checked={source.enabled}
                  onChange={(e) =>
                    patch({
                      sources: apply.sources.map((s, i) =>
                        i === index ? { ...s, enabled: e.target.checked } : s,
                      ),
                    })
                  }
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <label htmlFor={`source-${source.id}`}>
                      <span className="font-medium">{sourceLabel(source)}</span>
                      {source.kind !== "ats_board" &&
                        source.kind !== "job_search" &&
                        source.categories.length > 0 && (
                          <span className="block text-xs text-ink-muted">
                            {source.categories.join(" · ")}
                          </span>
                        )}
                    </label>
                    {source.kind === "job_search" && (
                      <button
                        type="button"
                        className="text-xs text-ink-muted hover:text-danger"
                        onClick={() =>
                          patch({
                            sources: apply.sources.filter((_, i) => i !== index),
                          })
                        }
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  {source.kind === "ats_board" ? (
                    <WatchlistEditor
                      source={source}
                      onChange={(next) => updateSource(index, next)}
                    />
                  ) : source.kind === "job_search" ? (
                    <JobSearchEditor
                      source={source}
                      onChange={(next) => updateSource(index, next)}
                    />
                  ) : (
                    <CategoryPicker
                      source={source}
                      onChange={(next) => updateSource(index, next)}
                    />
                  )}
                </div>
              </li>
            ))}
          </ul>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            {!apply.sources.some((source) => source.kind === "ats_board") && (
              <button
                type="button"
                className="text-xs text-accent underline"
                onClick={() => patch({ sources: [...apply.sources, newWatchlistSource()] })}
              >
                Add a company watchlist
              </button>
            )}
            <button
              type="button"
              className="text-xs text-accent underline"
              onClick={() =>
                patch({
                  sources: [
                    ...apply.sources,
                    {
                      id: `job-search-${Date.now().toString(36)}`,
                      kind: "job_search",
                      url: "",
                      categories: [],
                      enabled: true,
                      provider: "adzuna",
                      query: "",
                      location: "",
                      country: "us",
                      include: [],
                      exclude: [],
                      locations: [],
                      max_age_days: 14,
                    },
                  ],
                })
              }
            >
              Add a keyword search
            </button>
          </div>
        </Section>

        <Section title="Auto-submit">
          <label className="flex items-center gap-2 font-medium">
            <input
              type="checkbox"
              checked={apply.auto_submit_enabled}
              onChange={(e) => void toggleAutoSubmit(e.target.checked)}
            />
            Submit verified forms without stopping for review
          </label>
          <fieldset className="mt-3" disabled={!apply.auto_submit_enabled}>
            <legend className="text-xs text-ink-muted">
              Only on these platforms (Workday always stops for review)
            </legend>
            <div className="mt-1 grid grid-cols-2 gap-1">
              {AUTO_SUBMIT_ATS.map((ats) => (
                <label key={ats.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={allowed.has(ats.id)}
                    onChange={(e) =>
                      patch({
                        auto_submit_ats: e.target.checked
                          ? [...apply.auto_submit_ats, ats.id]
                          : apply.auto_submit_ats.filter((a) => a.toLowerCase() !== ats.id),
                      })
                    }
                  />
                  {ats.label}
                </label>
              ))}
            </div>
          </fieldset>
          {apply.auto_submit_enabled && allowed.size === 0 && (
            <p className="mt-2 rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">
              No platform is ticked, so every application still stops for your review.
            </p>
          )}
          <fieldset
            className="mt-3 space-y-2 rounded-md border border-line p-3 disabled:opacity-50"
            disabled={!apply.auto_submit_enabled}
          >
            <legend className="px-1 text-xs font-medium">Limits on automatic submits</legend>
            <label className="block">
              Parallel fills{" "}
              <input
                className="field mx-1 inline-block w-16"
                type="number"
                min={1}
                max={4}
                aria-label="Parallel fills"
                value={apply.max_parallel_fills}
                onChange={(e) =>
                  patch({
                    max_parallel_fills: Math.min(4, Math.max(1, Number(e.target.value) || 1)),
                  })
                }
              />
            </label>
            <p className="text-xs text-ink-muted">More tabs raise the chance of bot checks.</p>
            <label className="block">
              Nightly run: at most{" "}
              <input
                className="field mx-1 inline-block w-20"
                type="number"
                min={0}
                max={500}
                aria-label="Automatic submits per nightly run"
                value={apply.auto_submit_max_per_run}
                onChange={(e) =>
                  patch({ auto_submit_max_per_run: Math.max(0, Number(e.target.value) || 0) })
                }
              />
              <span className="text-xs text-ink-muted">
                ({autoSubmitCapLabel(apply.auto_submit_max_per_run)})
              </span>
            </label>
            <label className="block">
              Any 24 hours, all sites: at most{" "}
              <input
                className="field mx-1 inline-block w-20"
                type="number"
                min={0}
                max={500}
                aria-label="Automatic submits per 24 hours"
                value={apply.auto_submit_max_per_day}
                onChange={(e) =>
                  patch({ auto_submit_max_per_day: Math.max(0, Number(e.target.value) || 0) })
                }
              />
            </label>
            <label className="block">
              Any 24 hours, one company: at most{" "}
              <input
                className="field mx-1 inline-block w-16"
                type="number"
                min={0}
                max={50}
                aria-label="Automatic submits per company per 24 hours"
                value={apply.auto_submit_max_per_company_per_day}
                onChange={(e) =>
                  patch({
                    auto_submit_max_per_company_per_day: Math.max(0, Number(e.target.value) || 0),
                  })
                }
              />
            </label>
          </fieldset>
          <p className="mt-2 text-sm font-medium" aria-live="polite">
            {autoSubmitSummary(apply)}
          </p>
          <p className="mt-2 text-xs text-ink-muted">
            Forms over a limit, and possible duplicates of something you already applied to, wait
            for your review instead. Automatic submits are spaced 20–90 seconds apart.
          </p>
        </Section>

        <Section title="Autofill model">
          <p className="text-xs text-ink-muted">
            Writes answers to form questions. Tailoring uses{" "}
            <Link className="text-accent underline" to="/settings?tab=models">
              {tailorModelLabel(settings, config)}
            </Link>
            .
          </p>
          <div className="mt-2 flex flex-wrap gap-3">
            <label>
              Provider{" "}
              <select
                className="field ml-2 w-auto"
                value={apply.model_provider}
                onChange={(e) =>
                  patch({ model_provider: e.target.value as typeof apply.model_provider })
                }
              >
                <option value="ollama">Ollama</option>
                <option value="ollama-cloud">Ollama Cloud</option>
                <option value="lmstudio">LM Studio</option>
                <option value="gemini">Gemini</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </label>
            <label>
              Model{" "}
              <input
                className="field ml-2 w-44"
                value={apply.model_name}
                onChange={(e) => patch({ model_name: e.target.value })}
              />
            </label>
          </div>
        </Section>

        <Section title="Browser" aside={<ConnectionStatus connected={browserConnected} />}>
          <Button variant="secondary" onClick={onCheckBrowser}>
            Check connection
          </Button>
          <BrowserCommand />
        </Section>

        <Section title="Notifications">
          {notify.supported ? (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={notify.enabled}
                onChange={(e) => notify.onChange(e.target.checked)}
              />
              Notify me when an application needs me or a run finishes
            </label>
          ) : (
            <p className="text-xs text-ink-muted">This browser can't show notifications.</p>
          )}
        </Section>
      </div>
    </Modal>
  );
}

function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="border-t border-line pt-4 first:border-t-0 first:pt-0">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="font-semibold">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
