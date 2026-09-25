import { useEffect, useMemo, useRef, useState } from "react";
import { Stepper } from "../../components/ui";
import { type RunProgress, runProgress } from "../../lib/runProgress";
import { formatElapsed, formatTypical, runSteps, typicalRunSeconds } from "../../lib/runSteps";
import { useRunState } from "../../state/runState";

/**
 * The run in six plain steps, elapsed time against how long runs usually take, and
 * the raw stage log under "Details". Before any run it shows how page fit is measured.
 */
export function ProgressPanel() {
  const {
    config,
    settings,
    status,
    events,
    report,
    error,
    busy,
    queuePosition,
    cancelRun,
    cancelling,
    history,
  } = useRunState();
  const progress = useMemo(() => runProgress(events, status, busy), [events, status, busy]);
  const steps = useMemo(
    () => runSteps(events, status, settings.cover_letter && !settings.no_cover_letter),
    [events, status, settings.cover_letter, settings.no_cover_letter],
  );
  const typical = useMemo(() => typicalRunSeconds(history), [history]);
  const elapsed = useElapsedSeconds(busy);
  const logRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    /** Keep the log pinned to its newest row as events stream in. */
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events]);

  // A failed run leaves `error` set with `busy` false; progress owns the tile then.
  const showStatus = busy || events.length > 0 || Boolean(error) || Boolean(report);

  if (!showStatus) {
    if (!config) return null;
    return (
      <section className="rounded-xl border border-dashed border-line bg-panel/60 p-4 text-sm text-ink-muted">
        <p>
          Page fit is{" "}
          {config.calibration_source === "fallback"
            ? "estimated. Tune it once on the Template page for exact results."
            : "measured for your template."}
        </p>
        {config.calibration_rejection && (
          <p className="mt-2 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
            {config.calibration_rejection}
          </p>
        )}
        {config.contact_name && <p className="mt-2">Resume: {config.contact_name}</p>}
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm lg:absolute lg:inset-0 lg:flex lg:flex-col lg:overflow-hidden">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-display text-xl font-semibold">Progress</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-ink-muted tabular-nums" role="status" aria-live="polite">
            {progress.label}
            {busy && elapsed > 0 ? ` · ${formatElapsed(elapsed)}` : ""}
            {busy && typical ? ` (usually ${formatTypical(typical)})` : ""}
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
          Waiting for another run to finish (position {queuePosition})
        </p>
      )}
      <div className="mt-4">
        <VerticalSteps state={steps} />
      </div>
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      {events.length > 0 && (
        <details className="mt-3 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col">
          <summary className="cursor-pointer text-xs font-medium text-ink-muted">
            Details ({events.length})
          </summary>
          <ol
            ref={logRef}
            className="mt-2 max-h-56 space-y-2 overflow-y-auto text-sm lg:max-h-none lg:min-h-0 lg:flex-1"
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
        </details>
      )}
    </section>
  );
}

function VerticalSteps({ state }: { state: ReturnType<typeof runSteps> }) {
  return (
    <Stepper
      steps={state.steps}
      current={state.current}
      failed={state.failed}
      label="Run steps"
      orientation="vertical"
    />
  );
}

/**
 * Seconds since `active` last became true, ticking every second while it stays true.
 * A reload that re-attaches to a running job restarts at 0: it measures how long this
 * tab has watched the run, not the job's server-side age.
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

function ProgressBar({ progress, failed }: { progress: RunProgress; failed: boolean }) {
  /** Indeterminate only before the first stage event lands. */
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
