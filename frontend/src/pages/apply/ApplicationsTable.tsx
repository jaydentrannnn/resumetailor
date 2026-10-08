import { useState, type ReactNode } from "react";
import { useNavigate, type To } from "react-router-dom";
import type { ApplicationRow } from "../../api";
import { DataTable, Pagination } from "../../components/TableControls";
import { Button, SelectionBar } from "../../components/ui";
import type { OpenTabs } from "../../lib/applicationRows";
import { TERMINAL_STATUSES } from "../../lib/applyPage";
import { applicationColumns } from "./applicationColumns";
import { TableFilters } from "./TableFilters";
import type { ApplicationTableState, Scope } from "./useApplicationTable";

// Tests and older imports reach PostedDate through this module.
export { PostedDate } from "./PostedDate";

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
 * One tab's application list: the filter row (group tabs, status filter, Columns,
 * Refresh, the tab's tools), the selection bar while rows are checked, and a paginated
 * table whose primary row action names the next step.
 */
export function ApplicationsTable({
  scope,
  state,
  actions,
  lead,
  tools,
  bulk,
  note,
  empty,
  onClearSearch,
}: {
  scope: Scope;
  state: ApplicationTableState;
  actions: TableActions;
  /** Left of the filter row: the group tabs. */
  lead?: ReactNode;
  /** The tab's own tools in the filter row (Find jobs and its options). */
  tools?: ReactNode;
  /** The tab's bulk actions, in the selection bar while rows are checked. */
  bulk?: ReactNode;
  /** A quiet line under the filter row (sources, auto-submit, blockers). */
  note?: ReactNode;
  /** Shown when the list is empty and no filter is set. */
  empty: ReactNode;
  /** Clears the page-wide search (the box lives in the tile header). */
  onClearSearch: () => void;
}) {
  const navigate = useNavigate();
  const { busy, active } = actions;
  const [extraColumns, setExtraColumns] = useState<string[]>([]);
  const archived = scope === "archive";
  const rows = state.data?.applications ?? [];
  const selectedIds = state.selectedRows.map((row) => row.source_job_id);
  const onScreen = new Set(rows.map((row) => row.source_job_id));
  const elsewhere = selectedIds.filter((id) => !onScreen.has(id)).length;
  const skippable = state.selectedRows.filter((row) => !TERMINAL_STATUSES.has(row.status));

  return (
    <div className="space-y-3">
      <TableFilters
        scope={scope}
        state={state}
        extraColumns={extraColumns}
        onExtraColumns={setExtraColumns}
        lead={lead}
        tools={tools}
      />
      {note}
      {selectedIds.length > 0 && (
        <SelectionBar count={selectedIds.length} onClear={state.clearSelection} clearLabel="Clear">
          {elsewhere > 0 && (
            <span className="mr-1 text-xs text-ink-muted">({elsewhere} on other pages)</span>
          )}
          {bulk}
          <Button
            size="sm"
            disabled={busy || active}
            title={active ? "Available when the current Apply task finishes" : undefined}
            onClick={() => actions.move(selectedIds, !archived)}
          >
            {archived ? "Restore" : "Archive"}
          </Button>
          {!archived && (
            <Button
              size="sm"
              variant="danger"
              disabled={busy || !skippable.length}
              title="Mark the selected applications as skipped and move them to Done"
              onClick={() => actions.skip(skippable)}
            >
              Skip ({skippable.length})
            </Button>
          )}
        </SelectionBar>
      )}
      {/* The table sits on the tile itself: no second box around it. */}
      <DataTable
        bare
        className="border-t border-line"
        rows={rows}
        id={(row) => row.source_job_id}
        rowLabel={(row) => `${row.company} ${row.role}`}
        columns={applicationColumns({ scope, actions, extraColumns, navigate })}
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
                className="mt-2 block w-full text-ink underline underline-offset-2"
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
    </div>
  );
}
