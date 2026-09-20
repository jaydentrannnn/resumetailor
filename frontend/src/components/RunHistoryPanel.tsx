import { useEffect, useMemo, useState } from "react";
import {
  type RunHistoryEntry,
  downloadPdfUrl,
  downloadUrl,
} from "../api";
import { useConfirm } from "../state/confirmState";
import { useRunState } from "../state/runState";

/** Runs that can be removed from disk-backed history (not queued or running). */
function isDeletable(run: RunHistoryEntry): boolean {
  return run.status !== "queued" && run.status !== "running";
}

/**
 * Recent tailoring runs for the active profile — survives reload via disk-backed
 * `run.json`. "View" loads the run into the results tiles above without re-downloading.
 */
export function RunHistoryPanel() {
  const { history, jobId, loadRun, busy, deleteHistoryRuns } = useRunState();
  const { confirm } = useConfirm();
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const deletableIds = useMemo(
    () => history.filter(isDeletable).map((run) => run.job_id),
    [history],
  );

  useEffect(() => {
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => deletableIds.includes(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [deletableIds]);

  if (history.length === 0) return null;

  const allSelected =
    deletableIds.length > 0 && deletableIds.every((id) => selected.has(id));
  const someSelected = selected.size > 0;

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(deletableIds));
  }

  async function handleDelete() {
    const ids = [...selected];
    if (ids.length === 0) return;
    const ok = await confirm({
      title: "Delete selected runs?",
      message: `Remove ${ids.length} run${ids.length === 1 ? "" : "s"} from history? Their files will be deleted and cannot be recovered.`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;

    setDeleting(true);
    setDeleteError(null);
    try {
      const errors = await deleteHistoryRuns(ids);
      const failed = Object.entries(errors);
      if (failed.length > 0) {
        setDeleteError(
          failed.map(([id, reason]) => `${id}: ${reason}`).join("; "),
        );
      }
      setSelected((prev) => {
        const next = new Set(prev);
        for (const id of ids) {
          if (!errors[id]) next.delete(id);
        }
        return next;
      });
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm lg:col-start-1 lg:col-span-2 lg:row-start-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Recent runs</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Survives a page reload. Opening a past run shows its report and preview without
            downloading again.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              className="rounded border-line"
              checked={allSelected}
              disabled={deletableIds.length === 0 || deleting || busy}
              onChange={toggleAll}
            />
            Select all
          </label>
          <button
            type="button"
            disabled={!someSelected || deleting || busy}
            onClick={() => void handleDelete()}
            className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-danger hover:border-danger disabled:opacity-50"
          >
            {deleting ? "Deleting…" : "Delete selected"}
          </button>
        </div>
      </div>

      {deleteError && (
        <p role="alert" className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {deleteError}
        </p>
      )}

      <ul className="mt-4 divide-y divide-line">
        {history.map((run) => (
          <HistoryRow
            key={run.job_id}
            run={run}
            active={run.job_id === jobId}
            disabled={busy || deleting}
            selectable={isDeletable(run)}
            selected={selected.has(run.job_id)}
            onToggleSelect={() => toggleOne(run.job_id)}
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
  selectable,
  selected,
  onToggleSelect,
  onView,
}: {
  run: RunHistoryEntry;
  active: boolean;
  disabled: boolean;
  selectable: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  onView: () => void;
}) {
  const when = formatWhen(run.created_at);
  const coverage =
    run.coverage_total != null && run.coverage_total > 0
      ? `${run.coverage_matched ?? 0}/${run.coverage_total}`
      : null;

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 rounded border-line"
          checked={selected}
          disabled={!selectable || disabled}
          title={selectable ? undefined : "Cannot delete a queued or running job"}
          onChange={onToggleSelect}
          aria-label={`Select ${run.title}`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium text-ink">{run.title}</span>
            <StatusPill status={run.status} />
            {active && (
              <span className="rounded bg-accent-soft px-1.5 py-0.5 text-micro font-semibold uppercase tracking-wide text-accent">
                Showing
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs tabular-nums text-ink-muted">
            {when}
            {run.pages != null ? ` · ${run.pages} page${run.pages === 1 ? "" : "s"}` : ""}
            {coverage ? ` · must-haves ${coverage}` : ""}
            {run.error ? ` · ${run.error.split("\n")[0]}` : ""}
          </p>
        </div>
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
      className={`rounded-full px-2 py-0.5 text-micro font-semibold uppercase tracking-wide ${tone}`}
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
