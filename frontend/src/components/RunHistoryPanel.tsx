import {
  type RunHistoryEntry,
  downloadPdfUrl,
  downloadUrl,
} from "../api";
import { useRunState } from "../state/runState";

/**
 * Recent tailoring runs for the active profile — survives reload via disk-backed
 * `run.json`. "View" loads the run into the results tiles above without re-downloading.
 */
export function RunHistoryPanel() {
  const { history, jobId, loadRun, busy } = useRunState();

  if (history.length === 0) return null;

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm lg:col-start-1 lg:col-span-2 lg:row-start-7">
      <h2 className="font-display text-xl font-semibold">Recent runs</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Survives a page reload. Opening a past run shows its report and preview without
        downloading again.
      </p>
      <ul className="mt-4 divide-y divide-line">
        {history.map((run) => (
          <HistoryRow
            key={run.job_id}
            run={run}
            active={run.job_id === jobId}
            disabled={busy}
            onView={() => void loadRun(run.job_id)}
          />
        ))}
      </ul>
    </section>
  );
}

function HistoryRow({
  run,
  active,
  disabled,
  onView,
}: {
  run: RunHistoryEntry;
  active: boolean;
  disabled: boolean;
  onView: () => void;
}) {
  const when = formatWhen(run.created_at);
  const coverage =
    run.coverage_total != null && run.coverage_total > 0
      ? `${run.coverage_matched ?? 0}/${run.coverage_total}`
      : null;

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-ink truncate">{run.title}</span>
          <StatusPill status={run.status} />
          {active && (
            <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-accent">
              Showing
            </span>
          )}
        </div>
        <p className="mt-0.5 text-xs text-ink-muted">
          {when}
          {run.pages != null ? ` · ${run.pages} page${run.pages === 1 ? "" : "s"}` : ""}
          {coverage ? ` · must-haves ${coverage}` : ""}
          {run.error ? ` · ${run.error.split("\n")[0]}` : ""}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {run.has_pdf && (
          <a
            href={downloadPdfUrl(run.job_id)}
            className="rounded-md border border-line px-2.5 py-1 text-xs font-medium hover:border-accent hover:text-accent"
          >
            .pdf
          </a>
        )}
        {run.has_docx && (
          <a
            href={downloadUrl(run.job_id)}
            className="rounded-md border border-line px-2.5 py-1 text-xs font-medium hover:border-accent hover:text-accent"
          >
            .docx
          </a>
        )}
        <button
          type="button"
          disabled={disabled || active}
          onClick={onView}
          className="rounded-md border border-line px-2.5 py-1 text-xs font-medium hover:border-accent hover:text-accent disabled:opacity-50"
        >
          View
        </button>
      </div>
    </li>
  );
}

function StatusPill({ status }: { status: RunHistoryEntry["status"] }) {
  const tone =
    status === "succeeded"
      ? "bg-accent-soft text-accent"
      : status === "failed"
        ? "bg-danger-soft text-danger"
        : status === "cancelled"
          ? "bg-paper text-ink-muted"
          : "bg-warn-soft text-warn";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide ${tone}`}
    >
      {status}
    </span>
  );
}

/** Format an ISO timestamp for the history list, or em dash when missing. */
function formatWhen(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
