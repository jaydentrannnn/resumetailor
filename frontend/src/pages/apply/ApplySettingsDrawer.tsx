import { type ReactNode, useEffect } from "react";
import { Link } from "react-router-dom";
import type { AppConfig, BrowserStatus, JobSettings, SchedulerStatus } from "../../api";
import { Modal } from "../../components/Modal";
import { Button, buttonClass, StatusChip, Switch } from "../../components/ui";
import { autoSubmitCapLabel, autoSubmitSummary, SOURCES_PATH } from "../../lib/applyPage";
import { tailorModelLabel } from "../../lib/modelLabel";
import { autofillLabel } from "../../lib/providers";
import { sourcesSummary } from "../../lib/sources";
import { useConfirm } from "../../state/confirmState";
import type { BrowserView } from "../../lib/browserState";
import { BrowserPicker, ConnectionStatus } from "./BrowserConnection";

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
 * the browser to start for Fill and desktop notifications. Every change autosaves through
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
  browser,
  browserStatus,
  onCheckBrowser,
  launch,
  notify,
}: {
  settings: JobSettings;
  setSettings: (next: JobSettings) => void;
  config: AppConfig | null;
  onClose: () => void;
  scheduler: SchedulerStatus | null;
  dailyRunning: boolean;
  onRunNow: () => void;
  browser: BrowserView;
  browserStatus: BrowserStatus | null;
  onCheckBrowser: () => void;
  launch: { run: () => void; busy: boolean };
  notify: { enabled: boolean; supported: boolean; onChange: (on: boolean) => void };
}) {
  const { confirm } = useConfirm();
  // Re-read which browsers are installed and whether one is running each time it opens.
  useEffect(onCheckBrowser, [onCheckBrowser]);
  const apply = settings.apply;
  const patch = (fields: Partial<JobSettings["apply"]>) =>
    setSettings({ ...settings, apply: { ...apply, ...fields } });
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
    <Modal title="Apply settings" onClose={onClose} placement="right" size="lg">
      <div className="mt-4 space-y-5 text-sm">
        <Section
          title="Nightly run"
          aside={
            <StatusChip tone={apply.enabled ? "done" : "muted"}>
              {apply.enabled ? "On" : "Off"}
            </StatusChip>
          }
        >
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2.5 font-medium">
              <Switch checked={apply.enabled} onChange={(on) => patch({ enabled: on })} />
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
          <fieldset className="mt-3 grid gap-4 sm:grid-cols-2" disabled={!apply.enabled}>
            <label className="block">
              <span className="mb-1 block">New postings each night</span>
              <input
                className="field w-full"
                type="number"
                min={1}
                max={500}
                aria-label="New postings per nightly run"
                value={apply.max_new_per_day}
                onChange={(e) =>
                  patch({ max_new_per_day: Math.max(1, Number(e.target.value) || 1) })
                }
              />
            </label>
            <p className="self-end text-xs text-ink-muted">
              Posting age, title words and eligibility are set in Filters for every source on{" "}
              <Link className="rt-link" to={SOURCES_PATH}>
                Job sources
              </Link>
              .
            </p>
          </fieldset>
          <div className="mt-4 flex items-center gap-3">
            <Button variant="plain" onClick={onRunNow} disabled={dailyRunning}>
              {dailyRunning ? "Running…" : "Run now"}
            </Button>
            <p className="min-w-0 text-xs text-ink-muted">
              Last run:{" "}
              {scheduler?.last_started_at ? formatWhen(scheduler.last_started_at) : "never"}
              {apply.enabled && scheduler?.next_run_at
                ? ` · Next: ${formatWhen(scheduler.next_run_at)}`
                : ""}
            </p>
          </div>
          {scheduler?.missed_today && (
            <p className="mt-1 text-xs text-attn">
              Today's run was missed because the app was closed.
            </p>
          )}
          {scheduler?.last_error && (
            <p className="mt-1 text-xs text-danger">{scheduler.last_error}</p>
          )}
        </Section>

        <Section title="What to search">
          <div className="flex items-center gap-3">
            <Link
              className={buttonClass("plain", "md", "shrink-0")}
              to={SOURCES_PATH}
              onClick={onClose}
            >
              Job sources →
            </Link>
            <p className="min-w-0 text-sm" aria-live="polite">
              {sourcesSummary(apply.sources)}
            </p>
          </div>
        </Section>

        <Section title="Auto-submit">
          <label className="flex items-center gap-2.5 font-medium">
            <Switch
              checked={apply.auto_submit_enabled}
              onChange={(on) => void toggleAutoSubmit(on)}
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
            <p className="mt-2 text-xs text-attn">
              No platform is ticked, so every application still stops for your review.
            </p>
          )}
          <fieldset
            className="mt-3 grid gap-3 border-t border-line pt-3 disabled:opacity-50 sm:grid-cols-2"
            disabled={!apply.auto_submit_enabled}
          >
            <legend className="text-xs font-medium">Limits on automatic submits</legend>
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
            <p className="self-center text-xs text-ink-muted">
              More tabs raise the chance of bot checks.
            </p>
            <label className="block">
              <span className="mb-1 block">Nightly run: at most</span>
              <input
                className="field w-full"
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
              <span className="mb-1 block">Any 24 hours, all sites: at most</span>
              <input
                className="field w-full"
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
              <span className="mb-1 block">Any 24 hours, one company: at most</span>
              <input
                className="field w-full"
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

        <Section title="AI models">
          <p className="text-xs text-ink-muted">
            Autofill writes answers with{" "}
            <span className="font-mono text-ink">
              {autofillLabel(apply.model_provider)} · {apply.model_name}
            </span>
            ; tailoring uses{" "}
            <span className="font-mono text-ink">{tailorModelLabel(settings, config)}</span>.{" "}
            <Link className="rt-link" to="/settings?tab=ai" onClick={onClose}>
              Change in Settings
            </Link>
          </p>
        </Section>

        <Section title="Browser" aside={<ConnectionStatus view={browser} />}>
          <BrowserPicker
            status={browserStatus}
            view={browser}
            selected={apply.browser ?? null}
            onSelect={(id) => patch({ browser: id })}
            launch={launch}
          />
        </Section>

        <Section title="Notifications">
          {notify.supported ? (
            <label className="flex items-center gap-2.5">
              <Switch checked={notify.enabled} onChange={notify.onChange} />
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
