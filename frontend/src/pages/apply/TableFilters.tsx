import type { ReactNode } from "react";
import { Button } from "../../components/ui";
import { applicationStatusLabel } from "../../lib/applicationStatus";
import { REVIEW_STATUSES } from "../../lib/applyPage";
import type { ApplicationTableState, Scope } from "./useApplicationTable";

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

/** Optional columns a tab can add, by id. */
function optionalColumns(scope: Scope): string[] {
  return scope === "archive"
    ? ["coverage", "discovered_at", "salary", "sources"]
    : ["discovered_at", "salary", "sources"];
}

/**
 * The filter row above a table: the group tabs on the left; the status filter, the
 * Columns picker, Refresh and the tab's own tools on the right.
 */
export function TableFilters({
  scope,
  state,
  extraColumns,
  onExtraColumns,
  lead,
  tools,
}: {
  scope: Scope;
  state: ApplicationTableState;
  extraColumns: string[];
  onExtraColumns: (next: string[]) => void;
  /** Left side of the row (the Needs you / In progress / Done tabs). */
  lead?: ReactNode;
  /** The tab's own tools after Refresh (Find jobs and its options). */
  tools?: ReactNode;
}) {
  const archived = scope === "archive";
  return (
    <div
      id={`${scope}-toolbar`}
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2.5"
    >
      {lead}
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Filter by status"
          className="field rt-control w-auto max-w-[14rem] py-0 text-[13px]"
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
        <details className="relative">
          <summary className="rt-control inline-flex cursor-pointer list-none items-center rounded-sm border border-ink/55 bg-field font-medium text-ink hover:border-ink hover:bg-sunken px-3 text-[13px]">
            Columns
          </summary>
          <div className="absolute right-0 z-20 mt-1 w-40 space-y-2 rounded-sm border border-line bg-chrome p-3 text-xs shadow-lg">
            {optionalColumns(scope).map((id) => (
              <label className="flex items-center gap-2" key={id}>
                <input
                  type="checkbox"
                  checked={extraColumns.includes(id)}
                  onChange={(e) =>
                    onExtraColumns(
                      e.target.checked
                        ? [...extraColumns, id]
                        : extraColumns.filter((v) => v !== id),
                    )
                  }
                />
                {id === "coverage"
                  ? "skill match"
                  : id === "discovered_at"
                    ? "found"
                    : id.replaceAll("_", " ")}
              </label>
            ))}
          </div>
        </details>
        <Button onClick={state.refresh}>Refresh</Button>
        {tools}
      </div>
    </div>
  );
}
