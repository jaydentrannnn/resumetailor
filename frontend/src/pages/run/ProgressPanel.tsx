import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Meter, Stat, StatusChip, Stepper, Tile, type Tone } from "../../components/ui";
import { runProgress } from "../../lib/runProgress";
import { formatElapsed, formatTypical, runSteps, typicalRunSeconds } from "../../lib/runSteps";
import { useRunState } from "../../state/runState";
import { useStepTimings } from "./useStepTimings";

const STATUS_TONE: Record<string, Tone> = {
  succeeded: "done",
  failed: "failed",
  cancelled: "muted",
};

/**
 * The "This run" tile: percent done, a meter, the six plain steps with how long each
 * took in this tab, and the raw stage log under "Details". Before any run it is a
 * single muted line.
 */
export function ProgressPanel() {
  const {
    config,
    settings,
    jobId,
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
  const timings = useStepTimings(steps.current, steps.steps.length, jobId ?? null, busy);
  const logRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    /** Keep the log pinned to its newest row as events stream in. */
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events]);

  // A failed run leaves `error` set with `busy` false; progress owns the tile then.
  const showStatus = busy || events.length > 0 || Boolean(error) || Boolean(report);
  const failed = status === "failed";
  const pct = Math.round(progress.value * 100);
  // A failed or cancelled run reads 100% in `runProgress` (the bar fills red); the figure
  // must not claim the run completed.
  const stopped = !busy && (failed || status === "cancelled");

  return (
    <Tile
      as="aside"
      title="This run"
      aria-label="This run"
      meta={
        showStatus && (
          <span className="font-mono tabular-nums">
            {busy && elapsed > 0 ? `${formatElapsed(elapsed)} elapsed` : ""}
            {busy && typical ? ` · usually ${formatTypical(typical)}` : ""}
          </span>
        )
      }
    >
      {!showStatus ? (
        <IdleNote
          estimated={config?.calibration_source === "fallback"}
          rejection={config?.calibration_rejection ?? null}
        />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <Stat
              value={stopped ? "—" : progress.indeterminate ? "…" : `${pct}%`}
              label={busy ? "done so far" : stopped ? "stopped early" : "complete"}
            />
            <span role="status" aria-live="polite">
              <StatusChip tone={STATUS_TONE[status ?? ""] ?? "live"}>{progress.label}</StatusChip>
            </span>
          </div>
          <Meter
            label="Tailoring progress"
            value={pct}
            valueText={progress.label}
            indeterminate={progress.indeterminate && !failed}
            tone={failed ? "danger" : "accent"}
          />
          {queuePosition != null && queuePosition > 1 && status === "queued" && (
            <p className="mt-3 text-sm text-ink-muted">
              Waiting for another run to finish (position {queuePosition})
            </p>
          )}
          <div className="mt-5">
            <Stepper
              steps={steps.steps.map((step, index) => ({ ...step, meta: timings[index] }))}
              current={steps.current}
              failed={steps.failed}
              label="Run steps"
              orientation="vertical"
              divided
            />
          </div>
          {error && (
            <p
              role="alert"
              className="mt-4 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger"
            >
              {error}
            </p>
          )}
          {(busy || events.length > 0) && (
            <div className="mt-5 flex flex-wrap items-start gap-3">
              {busy && (
                <Button size="sm" onClick={() => void cancelRun()} disabled={cancelling}>
                  {cancelling ? "Cancelling…" : "Cancel"}
                </Button>
              )}
              {events.length > 0 && <EventLog events={events} logRef={logRef} />}
            </div>
          )}
        </>
      )}
    </Tile>
  );
}

function IdleNote({ estimated, rejection }: { estimated: boolean; rejection: string | null }) {
  return (
    <>
      <p className="text-sm text-ink-muted">
        No run yet. Progress shows here once you tailor a resume.
      </p>
      {estimated && (
        <p className="mt-2 text-sm text-ink-muted">
          Page fit is estimated. Tune it once on the{" "}
          <Link className="rt-link" to="/template">
            Template page
          </Link>{" "}
          for exact results.
        </p>
      )}
      {rejection && <p className="mt-3 text-sm text-attn">{rejection}</p>}
    </>
  );
}

function EventLog({
  events,
  logRef,
}: {
  events: { stage: string; message: string }[];
  logRef: React.RefObject<HTMLOListElement | null>;
}) {
  return (
    <details className="ml-auto min-w-0 open:basis-full">
      <summary className="cursor-pointer py-1.5 text-right text-xs font-medium text-ink-muted hover:text-ink">
        Details ({events.length})
      </summary>
      <ol ref={logRef} className="mt-2 max-h-56 space-y-2 overflow-y-auto text-[13px]">
        {events.map((ev, i) => (
          <li key={`${ev.stage}-${i}`} className="flex gap-3">
            <span className="w-16 shrink-0 pt-px font-mono text-micro uppercase text-ink-muted">
              {ev.stage}
            </span>
            <span className="min-w-0 text-ink-2">{ev.message}</span>
          </li>
        ))}
      </ol>
    </details>
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
