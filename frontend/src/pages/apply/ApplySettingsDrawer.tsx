import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { AppConfig, JobSettings, SchedulerStatus, SourceConfig } from "../../api";
import { Modal } from "../../components/Modal";
import { Button } from "../../components/ui";
import { autoSubmitCapLabel } from "../../lib/applyPage";
import { tailorModelLabel } from "../../lib/modelLabel";
import { newWatchlistSource, WATCHLIST_ID } from "../../lib/watchlist";
import { useConfirm } from "../../state/confirmState";
import { BrowserCommand, ConnectionStatus } from "./BrowserConnection";
import { CategoryPicker, WatchlistEditor } from "./SourceEditors";

function sourceLabel(source: SourceConfig): string {
  if (source.kind === "ats_board") {
    return source.id === WATCHLIST_ID ? "Company watchlist" : source.id;
  }
  return source.id;
}

/**
 * Platforms that may auto-submit. Workday, LinkedIn, Indeed and Handshake are absent: they
 * always stop for review (`fill.ASSIST_ONLY_ATS`).
 */
const AUTO_SUBMIT_ATS: { id: string; label: string }[] = [
  { id: "greenhouse", label: "Greenhouse" },
  { id: "lever", label: "Lever" },
  { id: "ashby", label: "Ashby" },
  { id: "smartrecruiters", label: "SmartRecruiters" },
  { id: "icims", label: "iCIMS" },
  { id: "oracle", label: "Oracle" },
];

export interface DiscoveryOptions {
  limit: string;
  setLimit: (value: string) => void;
  dryRun: boolean;
  setDryRun: (value: boolean) => void;
}

/**
 * Apply settings in a right-hand drawer: what to search, whether and where to
 * auto-submit, the Autofill model, the nightly schedule, the browser connection and
 * desktop notifications. Every change autosaves through `runState`.
 */
export function ApplySettingsDrawer({
  settings,
  setSettings,
  config,
  onClose,
  discovery,
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
  discovery: DiscoveryOptions;
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
                  <label htmlFor={`source-${source.id}`}>
                    <span className="font-medium">{sourceLabel(source)}</span>
                    {source.kind !== "ats_board" && source.categories.length > 0 && (
                      <span className="block text-xs text-ink-muted">
                        {source.categories.join(" · ")}
                      </span>
                    )}
                  </label>
                  {source.kind === "ats_board" ? (
                    <WatchlistEditor
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
          {!apply.sources.some((source) => source.kind === "ats_board") && (
            <button
              type="button"
              className="mt-2 text-xs text-accent underline"
              onClick={() => patch({ sources: [...apply.sources, newWatchlistSource()] })}
            >
              Add a company watchlist
            </button>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <label>
              Most postings per search{" "}
              <input
                className="field ml-2 w-20"
                type="number"
                min={1}
                max={500}
                placeholder="All"
                value={discovery.limit}
                onChange={(e) => discovery.setLimit(e.target.value)}
              />
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={discovery.dryRun}
                onChange={(e) => discovery.setDryRun(e.target.checked)}
              />
              Only list what's found (don't tailor)
            </label>
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
          <label className="mt-3 block">
            Nightly run submits at most{" "}
            <input
              className="field mx-1 inline-block w-20"
              type="number"
              min={0}
              max={500}
              value={apply.auto_submit_max_per_run}
              onChange={(e) =>
                patch({ auto_submit_max_per_run: Math.max(0, Number(e.target.value) || 0) })
              }
            />
            <span className="text-xs text-ink-muted">
              ({autoSubmitCapLabel(apply.auto_submit_max_per_run)})
            </span>
          </label>
          <label className="mt-3 block">
            In any 24 hours, submit at most{" "}
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
            />{" "}
            applications, and at most{" "}
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
            />{" "}
            to one company.
          </label>
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

        <Section title="Nightly run">
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={apply.enabled}
                onChange={(e) => patch({ enabled: e.target.checked })}
              />
              Search and tailor every day at
            </label>
            <input
              aria-label="Nightly run time"
              type="time"
              className="field w-28"
              value={apply.schedule_time}
              onChange={(e) => patch({ schedule_time: e.target.value })}
            />
          </div>
          <p className="mt-2 text-xs text-ink-muted">
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
          <p className="mt-1 text-xs text-ink-muted">
            The app must be open (or in the tray) at that time.
          </p>
          <Button className="mt-2" onClick={onRunNow} disabled={dailyRunning}>
            {dailyRunning ? "Running…" : "Run now"}
          </Button>
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
