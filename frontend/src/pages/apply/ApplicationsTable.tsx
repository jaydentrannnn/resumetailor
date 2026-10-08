import { useState, type ReactNode } from "react";
import { CapturedBadge } from "../CapturedStubs";
import { Link, useNavigate, type To } from "react-router-dom";
import type { ApplicationRow } from "../../api";
import { StatusChip } from "../../components/ui";
import {
  DataTable,
  Pagination,
  RowActionsMenu,
  type MenuItem,
  type TableColumn,
} from "../../components/TableControls";
import { applicationStatusLabel, applicationStatusTone } from "../../lib/applicationStatus";
import {
  canContinueFill,
  canFillAfterReview,
  canReopenFill,
  localDate,
  isTabClosed,
  retryShortLabel,
  retryTitle,
  type OpenTabs,
} from "../../lib/applicationRows";
import { REVIEW_STATUSES, TERMINAL_STATUSES, canRetailor, reviewReason } from "../../lib/applyPage";
import type { ApplicationTableState, Scope } from "./useApplicationTable";

// One fixed box for every row action, <button> or <Link>: same width so the column
// lines up, one line (short labels; the full wording is the tooltip), and the compact
// `rt-row-action` height. Font size is set on the cell wrapper (see TableControls'
// menuItemClass for why a text-* class on a <button> is ignored).
const actionBase =
  "rt-row-action inline-flex w-[5.5rem] shrink-0 items-center justify-center whitespace-nowrap rounded-md px-2 font-medium disabled:cursor-not-allowed disabled:opacity-40";
const TONE = {
  primary: "bg-accent text-on-accent hover:brightness-110",
  attention: "bg-warn-soft text-warn hover:brightness-95",
  neutral: "border border-line bg-panel text-ink hover:border-line-hover",
};
// A retry after a failure is red; the same button as a routine next step
// (e.g. "Fetch JD" on a newly discovered row) is a teal outline, not an alarm.
const retryTone = (status: string) =>
  applicationStatusTone(status) === "failed"
    ? "border border-danger/50 bg-panel text-danger hover:bg-danger-soft"
    : "border border-accent/60 bg-panel text-accent hover:bg-accent-soft";
const ALL_STATUSES = [
  "discovered",
  "jd_fetched",
  "needs_browser",
  "screened_out",
  "screened_in",
  "tailoring",
  "tailor_failed",
  "ready",
  "filling",
  "awaiting_otp",
  "fill_failed",
  "awaiting_review",
  "submitted",
  "submit_unconfirmed",
  "interview",
  "rejected",
  "ghosted",
  "skipped",
];

/** Everything a table row can do, owned by the page (it holds the operation state). */
export interface TableActions {
  busy: boolean;
  /** An Apply task or the nightly run is in progress: workflow actions wait. */
  active: boolean;
  browserConnected: boolean;
  openTabs: OpenTabs;
  start: (
    action: "find" | "prepare" | "fill",
    ids?: string[],
    mode?: "initial" | "continue" | "reopen",
    force?: boolean,
  ) => void;
  reopen: (rows: ApplicationRow[]) => void;
  /** Tailor files again (forced), asking first when a filled tab is still open. */
  retailor: (rows: ApplicationRow[]) => void;
  move: (ids: string[], archived: boolean) => void;
  undo: (row: ApplicationRow) => void;
  retry: (row: ApplicationRow) => void;
  mark: (row: ApplicationRow, status: "submitted" | "skipped") => void;
  /** Skip every row given (bulk); the page moves them to Done and offers Undo. */
  skip: (rows: ApplicationRow[]) => void;
  focusTab: (row: ApplicationRow) => void;
  detail: (row: ApplicationRow, tab?: string) => To;
  rememberScroll: () => void;
}

/**
 * One tab's application list: search and status filter, the tab's bulk actions, and a
 * paginated table whose primary row action names the next step.
 */
export function ApplicationsTable({
  scope,
  state,
  actions,
  toolbar,
  empty,
  onClearSearch,
}: {
  scope: Scope;
  state: ApplicationTableState;
  actions: TableActions;
  /** Bulk actions for this tab, above the table. */
  toolbar?: ReactNode;
  /** Shown when the list is empty and no filter is set. */
  empty: ReactNode;
  /** Clears the page-wide search (the box lives above the tabs). */
  onClearSearch: () => void;
}) {
  const navigate = useNavigate();
  const { busy, active, browserConnected, openTabs } = actions;
  const [extraColumns, setExtraColumns] = useState<string[]>([]);
  const archived = scope === "archive";
  const rows = state.data?.applications ?? [];
  const selectedIds = state.selectedRows.map((row) => row.source_job_id);
  const onScreen = new Set(rows.map((row) => row.source_job_id));
  const elsewhere = selectedIds.filter((id) => !onScreen.has(id)).length;
  const skippable = state.selectedRows.filter((row) => !TERMINAL_STATUSES.has(row.status));
  const dateColumn = archived ? "archived_at" : scope === "review" ? "status_at" : "posted_at";

  function menu(row: ApplicationRow): MenuItem[] {
    const items: MenuItem[] = [];
    if (row.job_id)
      items.push({
        label: "Tailored PDF",
        href: `/api/jobs/${encodeURIComponent(row.job_id)}/preview.pdf`,
      });
    if (row.posting_url) items.push({ label: "Job posting", href: row.posting_url });
    if (archived)
      return [
        ...items,
        {
          label: row.status === "submitted" ? "Restore (undo submitted)" : "Restore",
          disabled: busy || active,
          action: () => actions.move([row.source_job_id], false),
          description: "Available when Apply is idle",
        },
      ];
    if (["submitted", "skipped"].includes(row.status))
      items.push({
        label: "Not submitted — move back",
        disabled: busy || active,
        action: () => actions.undo(row),
      });
    if (canRetailor(row))
      items.push({
        label: "Tailor files again",
        disabled: busy || active,
        action: () => actions.retailor([row]),
        description: "Available when Apply is idle",
      });
    const tabOpen = !!row.fill?.browser_target_id && !isTabClosed(row, openTabs);
    if (tabOpen) items.push({ label: "Open application tab", action: () => actions.focusTab(row) });
    if (tabOpen && !["submitted", "filling", "submit_unconfirmed"].includes(row.status))
      items.push({
        label: "Continue fill",
        disabled: busy || active || !canFillAfterReview(row),
        action: () => actions.start("fill", [row.source_job_id], "continue"),
      });
    if (canReopenFill(row))
      items.push({
        label: "Reopen and fill",
        disabled: busy || active,
        action: () => actions.reopen([row]),
      });
    if (["awaiting_review", "awaiting_otp", "submit_unconfirmed"].includes(row.status))
      items.push({ label: "Mark submitted", action: () => actions.mark(row, "submitted") });
    if (!TERMINAL_STATUSES.has(row.status))
      items.push({ label: "Skip", action: () => actions.mark(row, "skipped"), danger: true });
    return [
      ...items,
      {
        label: "Archive",
        disabled: busy || active,
        action: () => actions.move([row.source_job_id], true),
        description: "Available when Apply is idle",
      },
    ];
  }

  function actionCell(row: ApplicationRow) {
    const needsYou = !archived && REVIEW_STATUSES.has(row.status);
    const reason = needsYou ? reviewReason(row) : null;
    const retryLabel =
      !archived &&
      !TERMINAL_STATUSES.has(row.status) &&
      !REVIEW_STATUSES.has(row.status) &&
      row.retry_kind
        ? retryShortLabel(row.retry_kind, row.status)
        : null;
    const kind: "continue" | "reopen" | "review" | "fill" | "retry" | "view" =
      archived || TERMINAL_STATUSES.has(row.status)
        ? "view"
        : needsYou
          ? canContinueFill(row, openTabs)
            ? "continue"
            : isTabClosed(row, openTabs) && canReopenFill(row)
              ? "reopen"
              : "review"
          : row.status === "ready" && canFillAfterReview(row)
            ? "fill"
            : retryLabel
              ? "retry"
              : "view";
    // The primary action is left out of the menu; Review stays one menu item away
    // when Continue or Reopen takes its place.
    const primaryLabel =
      kind === "continue"
        ? "Continue fill"
        : kind === "reopen"
          ? "Reopen and fill"
          : kind === "fill"
            ? "Fill"
            : null;
    const items = [
      ...(kind === "continue" || kind === "reopen"
        ? [{ label: "Review", action: () => navigate(actions.detail(row, "review")) }]
        : []),
      ...menu(row).filter((item) => item.label !== primaryLabel),
    ];
    const needsBrowser = "Connect the browser in Apply settings first";
    let primary: ReactNode;
    if (kind === "continue")
      primary = (
        <button
          type="button"
          className={`${actionBase} ${TONE.attention}`}
          title={browserConnected ? "Continue the fill in its open tab" : needsBrowser}
          disabled={busy || active || !browserConnected}
          onClick={() => actions.start("fill", [row.source_job_id], "continue")}
        >
          Continue
        </button>
      );
    else if (kind === "reopen")
      primary = (
        <button
          type="button"
          className={`${actionBase} ${TONE.attention}`}
          title="The tab was closed: open the posting again and fill it from the start"
          disabled={busy || active || !browserConnected}
          onClick={() => actions.reopen([row])}
        >
          Reopen
        </button>
      );
    else if (kind === "fill")
      primary = (
        <button
          type="button"
          className={`${actionBase} ${TONE.primary}`}
          title={browserConnected ? "Open the posting and fill the form" : needsBrowser}
          disabled={busy || active || !browserConnected}
          onClick={() => actions.start("fill", [row.source_job_id])}
        >
          Fill
        </button>
      );
    else if (kind === "retry")
      primary = (
        <button
          type="button"
          className={`${actionBase} ${retryTone(row.status)}`}
          title={row.retry_kind ? retryTitle(row.retry_kind) : undefined}
          disabled={busy || active}
          onClick={() => actions.retry(row)}
        >
          {retryLabel}
        </button>
      );
    else if (kind === "review" && reason?.profilePath)
      primary = (
        <Link
          to={reason.profilePath}
          title={reason.why}
          className={`${actionBase} ${TONE.attention}`}
        >
          {reason.action}
        </Link>
      );
    else
      primary = (
        <Link
          to={actions.detail(row, kind === "review" ? "review" : "overview")}
          onClick={actions.rememberScroll}
          title={reason?.why}
          className={`${actionBase} ${kind === "review" ? TONE.attention : TONE.neutral}`}
        >
          {kind === "review" ? reason!.action : "View"}
        </Link>
      );
    return (
      <div className="flex flex-nowrap items-center gap-1 text-xs">
        {primary}
        <RowActionsMenu label={`More actions for ${row.company} ${row.role}`} items={items} />
      </div>
    );
  }

  const statusPill = (row: ApplicationRow) => (
    <StatusChip tone={applicationStatusTone(row.status)}>
      {applicationStatusLabel(row.status)}
    </StatusChip>
  );

  const cols: TableColumn<ApplicationRow>[] = [
    {
      id: "company",
      heading: "Company",
      sortable: true,
      className: "w-[17%]",
      cell: (row) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <strong className="font-medium">{row.company}</strong>
          {!!row.resume_review?.warnings.length && (
            <p className="mt-1 text-xs text-warn" title={row.resume_review.warnings.join("\n")}>
              {row.resume_review.required ? "Resume needs review" : "Resume warnings reviewed"} ·{" "}
              {row.resume_review.warnings.join(" ")}
            </p>
          )}
          <CapturedBadge row={row} />
        </span>
      ),
    },
    {
      id: "role",
      heading: "Role / location",
      sortable: true,
      className: "w-[22%]",
      cell: (row) => (
        <>
          <Link
            className="font-medium text-accent hover:underline"
            to={actions.detail(row)}
            onClick={actions.rememberScroll}
          >
            {row.role}
          </Link>
          <p className="text-xs text-ink-muted">{row.location}</p>
        </>
      ),
    },
    {
      id: "ats",
      heading: "Platform",
      sortable: true,
      className: "w-[9%]",
      cell: (row) =>
        row.ats ? (
          <span className="whitespace-nowrap rounded bg-panel px-1.5 py-0.5 text-xs">
            {row.ats}
          </span>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    scope === "review"
      ? {
          id: "status",
          heading: "Why it needs you",
          sortable: true,
          className: "w-[24%]",
          cell: (row) => {
            const reason = reviewReason(row);
            return (
              <>
                <p className="text-sm font-medium text-ink">{reason.why}</p>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                  {statusPill(row)}
                  {isTabClosed(row, openTabs) && <span>Tab closed</span>}
                </p>
              </>
            );
          },
        }
      : {
          id: "status",
          heading: "Status",
          sortable: true,
          className: "w-[17%]",
          cell: (row) => (
            <>
              {statusPill(row)}
              {row.screen_label && (
                <p
                  className="mt-1 line-clamp-1 text-xs text-ink-muted"
                  title={row.screen?.reasons.join("; ")}
                >
                  {row.screen_label}
                </p>
              )}
              {row.error && !archived && (
                <p className="mt-1 line-clamp-1 text-xs text-danger" title={row.error}>
                  {row.error}
                </p>
              )}
            </>
          ),
        },
    ...(scope === "queue"
      ? [
          {
            id: "coverage",
            heading: "Skill match",
            sortable: true,
            className: "w-[10%]",
            cell: (row: ApplicationRow) =>
              row.screen?.coverage_total
                ? `${row.screen.coverage_matched}/${row.screen.coverage_total} · ${Math.round((row.screen.coverage_matched / row.screen.coverage_total) * 100)}%`
                : "Not checked",
          },
        ]
      : []),
    {
      id: dateColumn,
      heading: archived ? "Done on" : scope === "review" ? "Waiting since" : "Posted",
      sortable: true,
      className: "w-[10%]",
      cell: (row) => {
        if (scope === "review") return <WaitingSince at={row.status_at || row.discovered_at} />;
        if (!archived) return <PostedDate row={row} />;
        return row.archived_at ? new Date(row.archived_at).toLocaleDateString() : "—";
      },
    },
    ...extraColumns.map((id) => ({
      id,
      heading:
        id === "coverage"
          ? "Skill match"
          : id === "discovered_at"
            ? "Found"
            : id[0].toUpperCase() + id.slice(1),
      sortable: true,
      className: "w-[10%]",
      cell: (row: ApplicationRow) =>
        id === "sources"
          ? [...new Set(row.sources)].join(", ")
          : id === "coverage"
            ? row.screen?.coverage_total
              ? `${row.screen.coverage_matched}/${row.screen.coverage_total}`
              : "Not checked"
            : id === "discovered_at"
              ? row.discovered_at
                ? new Date(row.discovered_at).toLocaleDateString()
                : "—"
              : String(row[id as "salary"] || "—"),
    })),
    {
      id: "actions",
      heading: "Next step",
      className: "w-[19%]",
      cell: actionCell,
    },
  ];

  const pagination = (
    <Pagination
      page={state.page}
      size={state.size}
      total={state.data?.total ?? 0}
      onPage={(page) => {
        state.change({ page: String(page + 1) });
        document.getElementById(`${scope}-toolbar`)?.scrollIntoView();
      }}
      onSize={(size) =>
        // Keep the first row in view: the new page is the one that still holds it.
        state.change({
          size: String(size),
          page: String(Math.floor((state.page * state.size) / size) + 1),
        })
      }
    />
  );
  const optionalColumns = archived
    ? ["coverage", "discovered_at", "salary", "sources"]
    : ["discovered_at", "salary", "sources"];

  return (
    <div className="space-y-3">
      <div id={`${scope}-toolbar`} className="flex flex-wrap justify-end gap-2">
        <select
          aria-label="Filter by status"
          className="rounded-md border border-line bg-panel px-2 text-sm"
          value={state.status}
          onChange={(e) => state.change({ status: e.target.value })}
        >
          <option value="">All statuses</option>
          {[...new Set([...ALL_STATUSES, ...Object.keys(state.data?.counts ?? {})])]
            .filter((value) => archived || REVIEW_STATUSES.has(value) === (scope === "review"))
            .map((value) => (
              <option value={value} key={value}>
                {applicationStatusLabel(value)} ({state.data?.counts[value] ?? 0})
              </option>
            ))}
        </select>
        <button
          type="button"
          className="rounded-md border border-line bg-panel px-3 text-sm"
          onClick={state.refresh}
        >
          Refresh
        </button>
        <details className="relative">
          <summary className="cursor-pointer rounded-md border border-line bg-panel px-3 py-2 text-sm">
            Columns
          </summary>
          <div className="absolute right-0 z-20 w-36 space-y-2 rounded-md border border-line bg-panel p-3 text-xs shadow">
            {optionalColumns.map((id) => (
              <label className="block" key={id}>
                <input
                  type="checkbox"
                  checked={extraColumns.includes(id)}
                  onChange={(e) =>
                    setExtraColumns((current) =>
                      e.target.checked ? [...current, id] : current.filter((v) => v !== id),
                    )
                  }
                />{" "}
                {id === "coverage"
                  ? "skill match"
                  : id === "discovered_at"
                    ? "found"
                    : id.replaceAll("_", " ")}
              </label>
            ))}
          </div>
        </details>
      </div>
      {toolbar}
      {selectedIds.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-md bg-accent-soft p-2 text-sm">
          <strong>{selectedIds.length} selected</strong>
          {elsewhere > 0 && (
            <span className="text-xs text-ink-muted">({elsewhere} on other pages)</span>
          )}
          <button type="button" onClick={state.clearSelection}>
            Clear
          </button>
          <button
            type="button"
            disabled={busy || active}
            title={active ? "Available when the current Apply task finishes" : undefined}
            onClick={() => actions.move(selectedIds, !archived)}
          >
            {archived ? "Restore" : "Archive"}
          </button>
          {!archived && (
            <button
              type="button"
              className="text-danger disabled:opacity-40"
              disabled={busy || !skippable.length}
              title="Mark the selected applications as skipped and move them to Done"
              onClick={() => actions.skip(skippable)}
            >
              Skip ({skippable.length})
            </button>
          )}
        </div>
      )}
      {pagination}
      <DataTable
        rows={rows}
        id={(row) => row.source_job_id}
        columns={cols}
        selected={state.selected}
        onSelected={state.setSelected}
        sort={state.sort}
        direction={state.direction}
        onSort={(id) =>
          state.change({
            sort: id,
            direction: state.sort === id && state.direction === "asc" ? "desc" : "asc",
          })
        }
        loading={state.loading}
        error={state.error}
        empty={
          state.q || state.status ? (
            <>
              No applications match these filters.{" "}
              <button
                type="button"
                className="mt-2 block w-full text-accent underline"
                onClick={() => {
                  if (state.status) state.change({ status: "" });
                  onClearSearch();
                }}
              >
                Clear filters
              </button>
            </>
          ) : (
            empty
          )
        }
      />
      {pagination}
    </div>
  );
}

/** When the posting went up; the date found, marked "~", when the source gave none. */
export function PostedDate({ row }: { row: ApplicationRow }) {
  const value = row.posted_at || row.discovered_at;
  if (!value) return <>—</>;
  if (row.posted_at && row.posted_known) return <>{localDate(value)}</>;
  return (
    <span className="text-ink-muted" title="Posting date unknown — date found">
      ~{localDate(value)}
    </span>
  );
}

function WaitingSince({ at }: { at: string }) {
  const date = new Date(at);
  if (!at || Number.isNaN(date.getTime())) return <>—</>;
  const elapsed = Math.max(0, Date.now() - date.getTime());
  const minutes = Math.floor(elapsed / 60000);
  const label =
    minutes < 60
      ? `${minutes} min ago`
      : minutes < 1440
        ? `${Math.floor(minutes / 60)} h ago`
        : `${Math.floor(minutes / 1440)} d ago`;
  return (
    <time dateTime={at} title={date.toLocaleString()}>
      {label}
    </time>
  );
}
