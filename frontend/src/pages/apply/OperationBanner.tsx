import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { type ApplyOperation, type JobStatus, fetchJob } from "../../api";
import {
  formatEta,
  itemProgress,
  operationEtaSeconds,
  operationHeadline,
} from "../../lib/applyPage";

/** Poll the tailor job Prepare is running, for progress inside the current item. */
function useCurrentJob(jobId: string, active: boolean): JobStatus | null {
  const [job, setJob] = useState<JobStatus | null>(null);
  useEffect(() => {
    setJob(null);
    if (!jobId || !active) return;
    let stopped = false;
    const load = () =>
      fetchJob(jobId)
        .then((next) => {
          if (!stopped) setJob(next);
        })
        .catch(() => {
          /* advisory: the bar falls back to whole items */
        });
    void load();
    const id = window.setInterval(load, 1500);
    return () => {
      stopped = true;
      window.clearInterval(id);
    };
  }, [jobId, active]);
  return job;
}

export type OperationControl = "pause" | "resume" | "skip" | "cancel";

/**
 * The current (or last) Apply task, pinned to the top of the page while it runs: a
 * plain phase ("Tailoring 3 of 12 · Acme"), an estimate of time left, and Pause /
 * Resume / Skip / Cancel. Pause takes effect between applications, never mid-form.
 */
export function OperationBanner({
  operation,
  onControl,
}: {
  operation: ApplyOperation;
  onControl: (action: OperationControl) => void;
}) {
  const active = ["queued", "running", "paused"].includes(operation.state);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  const job = useCurrentJob(
    operation.action === "prepare" ? (operation.current_job_id ?? "") : "",
    active,
  );
  const item = itemProgress(operation, job, now);
  const done = Math.min(operation.total, operation.processed + (item?.fraction ?? 0));
  const eta = operationEtaSeconds(operation, now, done);
  const pct = (n: number) =>
    operation.total > 0 ? Math.max(0, Math.min(100, (n / operation.total) * 100)) : 0;
  const userPaused = operation.state === "paused" && operation.stage === "paused_by_user";
  const pauseRequested =
    operation.state === "running" && operation.events.at(-1)?.stage === "pause_requested";
  const events = operation.events.filter(
    (event, index, all) => index === 0 || event.message !== all[index - 1].message,
  );
  const deadline = Date.parse(operation.application_deadline_at || "");

  return (
    <section
      className={`rounded-lg border bg-panel p-4 shadow-sm ${active ? "sticky top-2 z-20 border-accent/40" : "border-line"}`}
      aria-live="polite"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{operationHeadline(operation)}</h2>
          {active && (
            <p className="mt-0.5 text-sm text-ink-muted">
              {userPaused
                ? "Paused by you. Nothing is being filled."
                : operation.state === "paused"
                  ? operation.message || "Waiting on you before the next application."
                  : operation.current_action_label || operation.message}
              {!userPaused && operation.current_field_label
                ? ` · ${operation.current_field_label}`
                : ""}
            </p>
          )}
          {operation.current_application_id && active && (
            <Link
              className="text-xs text-accent underline"
              to={`/applications/${encodeURIComponent(operation.current_application_id)}`}
            >
              Open this application
            </Link>
          )}
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          {operation.state === "running" && operation.action !== "find" && (
            <button
              type="button"
              className="rounded-md border border-line px-2 py-1 font-medium hover:border-accent hover:text-accent disabled:opacity-50"
              disabled={pauseRequested}
              title="Stop before the next application; the one in progress finishes first"
              onClick={() => onControl("pause")}
            >
              Pause
            </button>
          )}
          {operation.state === "paused" && (
            <>
              <button
                type="button"
                className="rounded-md bg-accent px-2 py-1 font-medium text-on-accent"
                onClick={() => onControl("resume")}
              >
                Resume
              </button>
              {!userPaused && (
                <button
                  type="button"
                  className="rounded-md border border-line px-2 py-1 font-medium"
                  onClick={() => onControl("skip")}
                >
                  Skip this one
                </button>
              )}
            </>
          )}
          {active && (
            <button
              type="button"
              className="rounded-md border border-danger px-2 py-1 font-medium text-danger"
              onClick={() => onControl("cancel")}
            >
              Cancel
            </button>
          )}
        </div>
      </div>
      {operation.total > 0 ? (
        <div
          role="progressbar"
          aria-label="Apply task progress"
          aria-valuenow={Math.round(done * 10) / 10}
          aria-valuemin={0}
          aria-valuemax={operation.total}
          aria-valuetext={`${operation.processed} of ${operation.total} done${item ? `; ${item.detail}` : ""}`}
          className="relative mt-3 h-2 overflow-hidden rounded-full bg-line"
        >
          {/* Lighter: the item in flight, by its own progress. Solid: finished items. */}
          <div
            className="absolute inset-y-0 left-0 bg-accent/35 transition-[width] duration-500"
            style={{ width: `${pct(done)}%` }}
          />
          <div
            className="absolute inset-y-0 left-0 bg-accent transition-[width] duration-500"
            style={{ width: `${pct(operation.processed)}%` }}
          />
        </div>
      ) : (
        active && (
          <div
            role="progressbar"
            aria-label="Progress total unknown"
            className="rt-progress-indeterminate mt-3 h-2 rounded-full bg-accent-soft"
          />
        )
      )}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
        {active && operation.total > 0 && (
          <span className="font-medium text-ink">
            {operation.processed} of {operation.total} done
            {item
              ? ` · ${operation.current_label ? `${operation.current_label}: ` : ""}${item.detail}`
              : ""}
          </span>
        )}
        {eta != null && (
          <span>
            {formatEta(eta)} left{item?.estimate ? " (estimate)" : ""}
          </span>
        )}
        <span>{operation.ready_for_review ?? operation.completed} ready for you</span>
        <span>{operation.submitted} submitted</span>
        <span>{operation.needs_input ?? operation.blocked} need input</span>
        {operation.failed > 0 && <span className="text-danger">{operation.failed} failed</span>}
      </div>
      <details className="mt-3 border-t border-line pt-2 text-xs text-ink-muted">
        <summary className="cursor-pointer">Activity</summary>
        <p className="mt-2">
          Model: {operation.effective_model || "—"}
          {active && Number.isFinite(deadline)
            ? ` · This application times out in ${Math.max(0, Math.floor((deadline - now) / 1000))}s`
            : ""}
          {operation.heartbeat_at
            ? ` · Last heartbeat ${new Date(operation.heartbeat_at).toLocaleTimeString()}`
            : ""}
        </p>
        <ul className="mt-2 max-h-52 space-y-1 overflow-y-auto">
          {events.map((event, index) => (
            <li key={`${event.at}-${index}`}>
              {event.at ? new Date(event.at).toLocaleTimeString() : ""} {event.message}
            </li>
          ))}
        </ul>
        {Object.entries(operation.excluded ?? {}).length > 0 && (
          <p className="mt-2">
            Left out:{" "}
            {Object.entries(operation.excluded ?? {})
              .map(([id, reasons]) => `${id}: ${reasons.join(", ").replaceAll("_", " ")}`)
              .join("; ")}
          </p>
        )}
      </details>
    </section>
  );
}
