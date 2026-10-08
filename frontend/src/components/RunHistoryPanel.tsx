import { useEffect, useMemo, useState } from "react";
import { type RunHistoryEntry, downloadPdfUrl, downloadUrl } from "../api";
import { type RunSort, type RunStatusFilter, filterRuns, sortRuns } from "../lib/runHistory";
import { useConfirm } from "../state/confirmState";
import { useRunState } from "../state/runState";
import { CompareRunsDialog } from "./CompareRunsDialog";
import { DataTable, Pagination, RowActionsMenu, type TableColumn } from "./TableControls";
import { Button, SelectionBar, StatusChip, Tile, type Tone } from "./ui";

/** Runs that can be removed from disk-backed history (not queued or running). */
function isDeletable(run: RunHistoryEntry): boolean {
  return run.status !== "queued" && run.status !== "running";
}

/**
 * Recent tailoring runs for the active profile — survives reload via disk-backed
 * `run.json`. The same table as the Apply page: search and status filter, sortable
 * headers, a bulk bar for selected rows, and a row menu. "Open" loads the run into the
 * results tiles above without re-downloading; two selected runs can be compared bullet
 * by bullet.
 */
export function RunHistoryPanel() {
  const { history, jobId, loadRun, busy, deleteHistoryRuns, refreshHistory } = useRunState();
  const { confirm } = useConfirm();
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(25);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<RunStatusFilter>("");
  const [sort, setSort] = useState<RunSort>("started");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [comparing, setComparing] = useState<[RunHistoryEntry, RunHistoryEntry] | null>(null);

  const filtered = useMemo(
    () => sortRuns(filterRuns(history, query, status), sort, direction),
    [history, query, status, sort, direction],
  );
  const visible = filtered.slice(page * size, (page + 1) * size);

  // Selection never outlives the rows it named (a deleted run, a finished filter change).
  useEffect(() => {
    const present = new Set(history.filter(isDeletable).map((run) => run.job_id));
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => present.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [history]);
  useEffect(() => {
    const last = Math.max(0, Math.ceil(filtered.length / size) - 1);
    if (page > last) setPage(last);
  }, [filtered.length, page, size]);

  if (history.length === 0) return null;

  const selectedIds = [...selected];
  const comparable = history.filter(
    (run) => selected.has(run.job_id) && run.status === "succeeded",
  );

  function openRun(run: RunHistoryEntry) {
    void loadRun(run.job_id).then(() =>
      document.getElementById("tailored-results")?.scrollIntoView(),
    );
  }

  function openCompare() {
    if (comparable.length !== 2) return;
    const [x, y] = [...comparable].sort((p, q) => p.created_at.localeCompare(q.created_at));
    setComparing([x, y]);
  }

  async function handleDelete(ids: string[]) {
    if (ids.length === 0) return;
    const ok = await confirm({
      title: ids.length === 1 ? "Delete this run?" : "Delete selected runs?",
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
        setDeleteError(failed.map(([id, reason]) => `${id}: ${reason}`).join("; "));
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

  const columns: TableColumn<RunHistoryEntry>[] = [
    {
      id: "title",
      heading: "Role",
      sortable: true,
      className: "w-[30%]",
      cell: (run) => (
        <span className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="text-left font-medium text-ink hover:underline disabled:no-underline"
            disabled={busy || deleting || run.job_id === jobId}
            onClick={() => openRun(run)}
          >
            {run.title || "Untitled posting"}
          </button>
          {run.job_id === jobId && (
            <span className="font-mono text-micro uppercase tracking-[0.08em] text-accent">
              Showing
            </span>
          )}
        </span>
      ),
    },
    {
      id: "company",
      heading: "Company",
      sortable: true,
      cell: (run) => run.company || <span className="text-ink-muted">—</span>,
    },
    {
      id: "started",
      heading: "Started",
      sortable: true,
      cell: (run) => (
        <span className="font-mono text-xs tabular-nums text-ink-muted">
          {formatWhen(run.created_at)}
        </span>
      ),
    },
    {
      id: "status",
      heading: "Status",
      sortable: true,
      cell: (run) => (
        <span className="flex flex-col items-start gap-1">
          <StatusPill status={run.status} />
          {run.error && (
            <span className="text-xs text-danger" title={run.error}>
              {run.error.split("\n")[0]}
            </span>
          )}
        </span>
      ),
    },
    {
      id: "coverage",
      heading: "Skill match",
      sortable: true,
      cell: (run) =>
        run.coverage_total != null && run.coverage_total > 0 ? (
          <span className="font-mono tabular-nums" title="Required skills the resume covers">
            {run.coverage_matched ?? 0}/{run.coverage_total} required
          </span>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    {
      id: "pages",
      heading: "Pages",
      sortable: true,
      className: "w-20",
      cell: (run) =>
        run.pages != null ? (
          <span className="font-mono tabular-nums">{run.pages}</span>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    {
      id: "actions",
      heading: "",
      className: "w-12",
      cell: (run) => (
        <RowActionsMenu
          label={`Actions for ${run.title}`}
          items={[
            {
              label: run.job_id === jobId ? "Showing above" : "Open",
              action: () => openRun(run),
              disabled: busy || deleting || run.job_id === jobId,
            },
            { label: "Download PDF", href: downloadPdfUrl(run.job_id), disabled: !run.has_pdf },
            { label: "Download .docx", href: downloadUrl(run.job_id), disabled: !run.has_docx },
            {
              label: "Delete",
              danger: true,
              disabled: !isDeletable(run) || busy || deleting,
              description: isDeletable(run)
                ? undefined
                : "A queued or running job can't be deleted",
              action: () => void handleDelete([run.job_id]),
            },
          ]}
        />
      ),
    },
  ];

  const pagination = (
    <Pagination
      page={page}
      size={size}
      total={filtered.length}
      onPage={setPage}
      onSize={(value) => {
        setSize(value);
        setPage(0);
      }}
    />
  );

  return (
    <Tile
      title={
        <>
          Recent runs
          <span className="ml-2 font-mono text-xs font-normal text-ink-muted">
            {history.length}
          </span>
        </>
      }
      aria-label="Recent runs"
      description="Survives a page reload. Opening a past run shows its report and preview without downloading again."
    >
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <input
            type="search"
            className="field min-w-48 flex-1 sm:w-auto"
            placeholder="Search by role or company"
            aria-label="Search runs by role or company"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(0);
            }}
          />
          <select
            aria-label="Filter runs by status"
            className="field w-auto"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as RunStatusFilter);
              setPage(0);
            }}
          >
            <option value="">All statuses</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
            <option value="active">Queued or running</option>
          </select>
          <Button onClick={() => void refreshHistory()}>Refresh</Button>
        </div>

        {selectedIds.length > 0 && (
          <SelectionBar
            count={selectedIds.length}
            onClear={() => setSelected(new Set())}
            clearLabel="Clear"
          >
            <Button
              size="sm"
              disabled={comparable.length !== 2 || selectedIds.length !== 2}
              title="Select two finished runs to compare their bullets"
              onClick={openCompare}
            >
              Compare
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={deleting || busy}
              onClick={() => void handleDelete(selectedIds)}
            >
              {deleting ? "Deleting…" : "Delete"}
            </Button>
          </SelectionBar>
        )}

        {deleteError && (
          <p role="alert" className="rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger">
            {deleteError}
          </p>
        )}

        {pagination}
        <DataTable
          rows={visible}
          id={(run) => run.job_id}
          rowLabel={(run) => (run.company ? `${run.title} at ${run.company}` : run.title)}
          columns={columns}
          selected={selected}
          onSelected={setSelected}
          selectable={(run) => isDeletable(run) && !busy && !deleting}
          sort={sort}
          direction={direction}
          onSort={(id) => {
            const next = id as RunSort;
            // Newest, most covered, longest first: the useful end of each column.
            const firstDirection = next === "title" || next === "company" ? "asc" : "desc";
            setDirection(sort === next ? (direction === "asc" ? "desc" : "asc") : firstDirection);
            setSort(next);
            setPage(0);
          }}
          loadingText="Loading runs…"
          empty={
            query || status ? (
              <>
                No runs match these filters.{" "}
                <button
                  type="button"
                  className="rt-link mt-2 block w-full"
                  onClick={() => {
                    setQuery("");
                    setStatus("");
                  }}
                >
                  Clear filters
                </button>
              </>
            ) : (
              "No runs yet."
            )
          }
        />
        {filtered.length > size && pagination}
      </div>
      {comparing && (
        <CompareRunsDialog a={comparing[0]} b={comparing[1]} onClose={() => setComparing(null)} />
      )}
    </Tile>
  );
}

const STATUS: Record<RunHistoryEntry["status"], { tone: Tone; label: string }> = {
  succeeded: { tone: "done", label: "Succeeded" },
  failed: { tone: "failed", label: "Failed" },
  cancelled: { tone: "muted", label: "Cancelled" },
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "live", label: "Running" },
};

function StatusPill({ status }: { status: RunHistoryEntry["status"] }) {
  const { tone, label } = STATUS[status] ?? { tone: "neutral", label: status };
  return <StatusChip tone={tone}>{label}</StatusChip>;
}

/** Format an ISO timestamp for the history table, or em dash when missing. */
function formatWhen(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
