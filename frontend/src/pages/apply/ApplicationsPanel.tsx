import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { buttonClass, EmptyState, Tabs, Tile } from "../../components/ui";
import { SOURCES_PATH, type ApplyTab } from "../../lib/applyPage";
import { NeedsDescriptionGroup } from "../CapturedStubs";
import { ApplicationsTable, type TableActions } from "./ApplicationsTable";
import { ProgressEmpty } from "./ProgressEmpty";
import type { ApplicationTableState } from "./useApplicationTable";

/**
 * The Applications tile: the page-wide search, the Needs you / In progress / Done tabs
 * with their counts, and the selected tab's table with its own tools and bulk actions.
 */
export function ApplicationsPanel({
  tab,
  onTab,
  q,
  onQuery,
  search,
  review,
  queue,
  archive,
  archiveTotal,
  actions,
  progress,
  reviewBulk,
  anySource,
  lastChecked,
  onFind,
}: {
  tab: ApplyTab;
  onTab: (tab: ApplyTab) => void;
  /** The search box's text; `search` is the debounced value the tables query with. */
  q: string;
  onQuery: (value: string) => void;
  search: string;
  review: ApplicationTableState;
  queue: ApplicationTableState;
  archive: ApplicationTableState;
  archiveTotal: number;
  actions: TableActions;
  progress: { tools: ReactNode; bulk: ReactNode; note: ReactNode };
  reviewBulk: ReactNode;
  anySource: boolean;
  lastChecked: string | null | undefined;
  onFind: () => void;
}) {
  const doneCount = search ? (archive.data?.total ?? 0) : archiveTotal;
  const counts = { needs: review.data?.total ?? 0, progress: queue.data?.total ?? 0 };
  const tables = { needs: review, progress: queue, done: archive };

  // A new search that finds nothing on this tab jumps to the first tab that has matches,
  // once per search, so it never fights a tab the user clicks afterwards.
  const switchedFor = useRef("");
  useEffect(() => {
    if (!search) {
      switchedFor.current = "";
      return;
    }
    const trimmed = search.trim();
    if (switchedFor.current === search || Object.values(tables).some((t) => t.dataQ !== trimmed))
      return;
    switchedFor.current = search;
    const total = (id: ApplyTab) => tables[id].data?.total ?? 0;
    if (total(tab) > 0) return;
    const hit = (["needs", "progress", "done"] as const).find((id) => total(id) > 0);
    if (hit) onTab(hit);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onTab only writes the URL
  }, [
    search,
    tab,
    review.dataQ,
    queue.dataQ,
    archive.dataQ,
    review.data,
    queue.data,
    archive.data,
  ]);

  const tabs = (
    <Tabs
      label="Applications"
      variant="segmented"
      items={[
        { id: "needs", label: "Needs you", count: counts.needs },
        { id: "progress", label: "In progress", count: counts.progress },
        { id: "done", label: "Done", count: doneCount },
      ]}
      value={tab}
      onChange={(id) => onTab(id as ApplyTab)}
    />
  );
  const scopes = { needs: "review", progress: "queue", done: "archive" } as const;
  const empties = {
    needs: (
      <EmptyState title="Nothing needs you right now">
        Applications that need a sign-in, an emailed code or an answer only you can give will show
        up here.
      </EmptyState>
    ),
    progress: (
      <ProgressEmpty
        anySource={anySource}
        finding={actions.busy || actions.active}
        lastChecked={lastChecked}
        hasDone={archiveTotal > 0}
        onFind={onFind}
        onDone={() => onTab("done")}
      />
    ),
    done: (
      <EmptyState title="Nothing finished yet">
        Submitted, skipped and archived applications appear here.
      </EmptyState>
    ),
  };

  return (
    <Tile
      title={
        <>
          Applications
          <span className="ml-2 font-mono text-xs font-normal text-ink-muted">
            {counts.needs + counts.progress + doneCount}
          </span>
        </>
      }
      actions={
        <>
          <div className="relative w-full sm:w-64">
            <input
              className="field rt-control py-0 pr-8"
              aria-label="Search applications"
              data-shortcut="search"
              placeholder="Search every tab by company, role, or location"
              value={q}
              onChange={(e) => onQuery(e.target.value)}
            />
            {q && (
              <button
                type="button"
                aria-label="Clear search"
                className="absolute right-1 top-1/2 -translate-y-1/2 px-1.5 text-ink-muted hover:text-ink"
                onClick={() => onQuery("")}
              >
                ×
              </button>
            )}
          </div>
          <Link className={buttonClass("ghost", "sm", "rt-control")} to={SOURCES_PATH}>
            Job sources →
          </Link>
        </>
      }
    >
      {/* One table for every tab, so switching tabs keeps the tablist (and its focus). */}
      <ApplicationsTable
        scope={scopes[tab]}
        state={tables[tab]}
        actions={actions}
        lead={tabs}
        intro={tab === "needs" && <NeedsDescriptionGroup />}
        bulk={tab === "needs" ? reviewBulk : tab === "progress" ? progress.bulk : undefined}
        tools={tab === "progress" ? progress.tools : undefined}
        note={tab === "progress" ? progress.note : undefined}
        empty={empties[tab]}
        onClearSearch={() => onQuery("")}
      />
    </Tile>
  );
}
