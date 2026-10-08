import { useEffect, useRef, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, buttonClass, EmptyState, Tabs, Tile } from "../../components/ui";
import { SOURCES_PATH, type ApplyTab } from "../../lib/applyPage";
import { NeedsDescriptionGroup } from "../CapturedStubs";
import { ApplicationsTable, type TableActions } from "./ApplicationsTable";
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
  const navigate = useNavigate();
  const doneCount = search ? (archive.data?.total ?? 0) : archiveTotal;
  const counts = { needs: review.data?.total ?? 0, progress: queue.data?.total ?? 0 };

  // A new search that finds nothing on this tab jumps to the first tab that has matches,
  // once per search, so it never fights a tab the user clicks afterwards.
  const switchedFor = useRef("");
  useEffect(() => {
    if (!search) {
      switchedFor.current = "";
      return;
    }
    const tables = { needs: review, progress: queue, done: archive };
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
  const common = { actions, lead: tabs, onClearSearch: () => onQuery("") };

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
      <div role="tabpanel">
        {tab === "needs" && (
          <>
            <NeedsDescriptionGroup />
            <ApplicationsTable
              scope="review"
              state={review}
              bulk={reviewBulk}
              {...common}
              empty={
                <EmptyState title="Nothing needs you right now">
                  Applications that need a sign-in, an emailed code or an answer only you can give
                  will show up here.
                </EmptyState>
              }
            />
          </>
        )}
        {tab === "progress" && (
          <ApplicationsTable
            scope="queue"
            state={queue}
            {...progress}
            {...common}
            empty={
              !anySource ? (
                <EmptyState
                  title="Choose what to search for"
                  action={
                    <Button variant="primary" onClick={() => navigate(SOURCES_PATH)}>
                      Pick job sources
                    </Button>
                  }
                >
                  Every job board is turned off, so there is nothing to find.
                </EmptyState>
              ) : (
                <EmptyState
                  title="No new postings"
                  action={
                    <Button
                      variant="primary"
                      disabled={actions.busy || actions.active}
                      onClick={onFind}
                    >
                      Find jobs now
                    </Button>
                  }
                >
                  {lastChecked
                    ? `Last checked ${new Date(lastChecked).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}.`
                    : "Nothing has been searched yet."}
                  {archiveTotal > 0 && (
                    <>
                      {" "}
                      <button type="button" className="rt-link" onClick={() => onTab("done")}>
                        See finished applications
                      </button>
                    </>
                  )}
                </EmptyState>
              )
            }
          />
        )}
        {tab === "done" && (
          <ApplicationsTable
            scope="archive"
            state={archive}
            {...common}
            empty={
              <EmptyState title="Nothing finished yet">
                Submitted, skipped and archived applications appear here.
              </EmptyState>
            }
          />
        )}
      </div>
    </Tile>
  );
}
