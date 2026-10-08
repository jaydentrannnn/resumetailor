import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AttentionList } from "./AttentionList";
import { Button, Meter, StatusMark, Tile } from "../../components/ui";
import { type ApplyOperation, type JobStatus, fetchJob } from "../../api";
import {
  formatEta,
  findProgress,
  itemProgress,
  operationEtaSeconds,
  operationHeadline,
} from "../../lib/applyPage";

/** Poll the tailor jobs Prepare is running, for progress inside each item. */
function useCurrentJobs(jobIds: string[], active: boolean): Record<string, JobStatus> {
  const [jobs, setJobs] = useState<Record<string, JobStatus>>({});
  const key = jobIds.filter(Boolean).join(",");
  useEffect(() => {
    setJobs({});
    if (!key || !active) return;
    let stopped = false;
    const load = () => {
      for (const jobId of key.split(",")) {
        void fetchJob(jobId)
          .then((next) => {
            if (!stopped) setJobs((previous) => ({ ...previous, [jobId]: next }));
          })
          .catch(() => {
            /* advisory: the bar falls back to whole items */
          });
      }
    };
    void load();
    const id = window.setInterval(load, 1500);
    return () => {
      stopped = true;
      window.clearInterval(id);
    };
  }, [key, active]);
  return jobs;
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
  const inFlight = operation.in_flight ?? [];
  const multiple = inFlight.length > 1;
  const jobs = useCurrentJobs(
    operation.action === "prepare"
      ? multiple
        ? inFlight.map((item) => item.job_id)
        : [operation.current_job_id ?? ""]
      : [],
    active,
  );
  const item = itemProgress(operation, jobs[operation.current_job_id ?? ""] ?? null, now);
  const itemLines = multiple
    ? inFlight.map((entry) => ({
        entry,
        progress: itemProgress(operation, jobs[entry.job_id] ?? null, now, entry),
      }))
    : [];
  const done = Math.min(
    operation.total,
    operation.processed +
      (multiple
        ? itemLines.reduce((sum, line) => sum + (line.progress?.fraction ?? 0), 0)
        : (item?.fraction ?? 0)),
  );
  const eta = operationEtaSeconds(operation, now, done);
  const finding = operation.action === "find";
  const search = findProgress(operation);
  const pct = (n: number) =>
    operation.total > 0 ? Math.max(0, Math.min(100, (n / operation.total) * 100)) : 0;
  const userPaused = operation.state === "paused" && operation.stage === "paused_by_user";
  const pauseRequested =
    operation.state === "running" && operation.events.at(-1)?.stage === "pause_requested";
  const events = operation.events
    .filter((event, index, all) => index === 0 || event.message !== all[index - 1].message)
    .reverse();
  const deadline = Date.parse(operation.application_deadline_at || "");
  const detail =
    active && !multiple
      ? `${
          userPaused
            ? "Paused by you. Nothing is being filled."
            : operation.state === "paused"
              ? operation.message || "Waiting on you before the next application."
              : operation.current_action_label || operation.message
        }${!userPaused && operation.current_field_label ? ` · ${operation.current_field_label}` : ""}`
      : "";
  const attention = operation.attention ?? [];

  return (
    <Tile
      padding="sm"
      className={`sm:px-5 ${active ? "sticky top-2 z-20" : ""}`}
      aria-live="polite"
    >
      <div className="grid items-center gap-x-5 gap-y-3 lg:grid-cols-[minmax(0,auto)_minmax(120px,1fr)_auto]">
        <div className="min-w-0 text-[13px]">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            {active && <StatusMark tone={userPaused ? "attention" : "live"} />}
            <h2 className="font-semibold text-ink">{operationHeadline(operation)}</h2>
            {detail && <p className="text-ink-muted">{detail}</p>}
          </div>
          {active && multiple && (
            <ul className="mt-1 space-y-0.5 text-ink-muted">
              {itemLines.map(({ entry, progress }) => (
                <li key={entry.application_id}>
                  {entry.label} · {entry.stage || operation.action} ·{" "}
                  {progress?.detail || entry.action_label || "Starting"}
                </li>
              ))}
            </ul>
          )}
          {operation.current_application_id && active && !multiple && (
            <Link
              className="text-xs text-ink-2 underline decoration-line-hover underline-offset-2 hover:text-ink hover:decoration-ink"
              to={`/applications/${encodeURIComponent(operation.current_application_id)}`}
            >
              Open this application
            </Link>
          )}
        </div>
        <div className="min-w-0">
          {finding && search ? (
            <Meter
              label="Find jobs progress"
              value={search.fraction * 100}
              valueText={search.detail}
            />
          ) : !finding && operation.total > 0 ? (
            <div
              role="progressbar"
              aria-label="Apply task progress"
              aria-valuenow={Math.round(done * 10) / 10}
              aria-valuemin={0}
              aria-valuemax={operation.total}
              aria-valuetext={`${operation.processed} of ${operation.total} done${item ? `; ${item.detail}` : ""}`}
              className="relative h-1 overflow-hidden rounded-xs bg-sunken"
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
            active && <Meter label="Progress total unknown" indeterminate />
          )}
        </div>
        <OperationControls
          operation={operation}
          userPaused={userPaused}
          pauseRequested={pauseRequested}
          onControl={onControl}
        />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
        {finding && search && <span className="font-medium text-ink-2">{search.detail}</span>}
        {finding && search && active && (
          <span>Sources and postings each make up half the progress bar.</span>
        )}
        {!finding && active && operation.total > 0 && (
          <span className="font-medium text-ink-2">
            <span className="font-mono">
              {operation.processed} of {operation.total}
            </span>{" "}
            done
            {!multiple && item
              ? ` · ${operation.current_label ? `${operation.current_label}: ` : ""}${item.detail}`
              : ""}
          </span>
        )}
        {eta != null && (
          <span>
            <span className="font-mono">{formatEta(eta)}</span> left
            {item?.estimate ? " (estimate)" : ""}
          </span>
        )}
        {!finding && (
          <Count n={operation.ready_for_review ?? operation.completed} text="ready for you" />
        )}
        {!finding && <Count n={operation.submitted} text="submitted" />}
        {!finding && <Count n={operation.needs_input ?? operation.blocked} text="need input" />}
        {operation.failed > 0 && (
          <span className="text-danger">
            <Count n={operation.failed} text="failed" />
          </span>
        )}
      </div>
      <OperationActivity
        operation={operation}
        events={events}
        timeout={
          active && Number.isFinite(deadline)
            ? Math.max(0, Math.floor((deadline - now) / 1000))
            : null
        }
      />
      {attention.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <AttentionList items={attention} collapsible />
        </div>
      )}
    </Tile>
  );
}

function Count({ n, text }: { n: number; text: string }) {
  return (
    <span>
      <span className="font-mono">{n}</span> {text}
    </span>
  );
}

/** The "Activity" disclosure: model, heartbeat and the task's events, newest first. */
function OperationActivity({
  operation,
  events,
  timeout,
}: {
  operation: ApplyOperation;
  events: ApplyOperation["events"];
  /** Seconds before the current application times out, while one runs. */
  timeout: number | null;
}) {
  const excluded = Object.entries(operation.excluded ?? {});
  return (
    <details className="mt-2 text-xs text-ink-muted">
      <summary className="rt-row-action -ml-2 inline-flex cursor-pointer items-center rounded-sm px-2 font-medium hover:bg-sunken hover:text-ink">
        Activity
      </summary>
      <p className="mt-2">
        Model: <span className="font-mono">{operation.effective_model || "—"}</span>
        {timeout != null ? ` · This application times out in ${timeout}s` : ""}
        {operation.heartbeat_at
          ? ` · Last heartbeat ${new Date(operation.heartbeat_at).toLocaleTimeString()}`
          : ""}
      </p>
      <ul className="mt-2 max-h-52 space-y-1 overflow-y-auto">
        {events.map((event, index) => (
          <li key={`${event.at}-${index}`}>
            <span className="font-mono">
              {event.at ? new Date(event.at).toLocaleTimeString() : ""}
            </span>{" "}
            {event.message}
          </li>
        ))}
      </ul>
      {excluded.length > 0 && (
        <p className="mt-2">
          Left out:{" "}
          {excluded
            .map(([id, reasons]) => `${id}: ${reasons.join(", ").replaceAll("_", " ")}`)
            .join("; ")}
        </p>
      )}
    </details>
  );
}

/** Pause / Resume / Skip this one / Cancel, as the task's state allows. */
function OperationControls({
  operation,
  userPaused,
  pauseRequested,
  onControl,
}: {
  operation: ApplyOperation;
  userPaused: boolean;
  pauseRequested: boolean;
  onControl: (action: OperationControl) => void;
}) {
  if (!["queued", "running", "paused"].includes(operation.state)) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {operation.state === "running" && operation.action !== "find" && (
        <Button
          size="sm"
          disabled={pauseRequested}
          title="Stop before the next application; the one in progress finishes first"
          onClick={() => onControl("pause")}
        >
          Pause
        </Button>
      )}
      {operation.state === "paused" && (
        <>
          <Button size="sm" variant="primary" onClick={() => onControl("resume")}>
            Resume
          </Button>
          {!userPaused && (
            <Button size="sm" onClick={() => onControl("skip")}>
              Skip this one
            </Button>
          )}
        </>
      )}
      <Button size="sm" variant="danger" onClick={() => onControl("cancel")}>
        Cancel
      </Button>
    </div>
  );
}
