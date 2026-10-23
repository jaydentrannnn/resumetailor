import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { TrackerCard, TrackerColumn } from "../../api";
import { CopyButton } from "../../components/CopyButton";
import { CommandBar, EmptyState, InlineHelp, Page, Segmented, Skeleton } from "../../components/ui";
import { describe } from "../../lib/errors";
import { filterCards, readHidden, shortDate, writeHidden, type TrackerFilters as Filters } from "../../lib/tracker";
import { useTrackerBoard } from "../../lib/useTrackerBoard";
import { useCommands } from "../../state/commandState";
import { useWorkspaceState } from "../../state/workspaceState";
import { EmailTray } from "./EmailTray";
import { TrackerBoardView } from "./TrackerBoardView";
import { TrackerFilters } from "./TrackerFilters";
import { TrackerList } from "./TrackerList";
import { TrackerContext, type PendingEmail, type TrackerDrag } from "./trackerContext";

const ASK_CLAUDE = "Check my email for job updates";

/**
 * Tracker: every Done application in columns by hiring stage. Moving a card records
 * what happened (an outcome event); email updates Claude Desktop read sit on their
 * cards, or in a tray to drag onto the right one.
 */
export function TrackerPage() {
  const actions = useTrackerBoard();
  const navigate = useNavigate();
  const workspaceId = useWorkspaceState().activeId ?? "";
  const [params, setParams] = useSearchParams();
  const [hidden, setHiddenState] = useState<TrackerColumn[]>(() => readHidden(workspaceId));
  const [drag, setDrag] = useState<TrackerDrag | null>(null);
  const [pendingEmail, setPendingEmail] = useState<PendingEmail | null>(null);
  const view = params.get("view") === "list" ? "list" : "board";
  const filters: Filters = {
    q: params.get("q") ?? "",
    from: params.get("from") ?? "",
    until: params.get("until") ?? "",
    email: params.get("email") === "1",
  };
  const setParam = (patch: Record<string, string>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(patch)) {
          if (value) next.set(key, value);
          else next.delete(key);
        }
        return next;
      },
      { replace: true },
    );
  const setHidden = (next: TrackerColumn[]) => {
    setHiddenState(next);
    writeHidden(workspaceId, next);
  };
  const toggle = (column: TrackerColumn) =>
    setHidden(hidden.includes(column) ? hidden.filter((c) => c !== column) : [...hidden, column]);

  const { board, loadError } = actions;
  const cards = filterCards(board?.cards ?? [], filters);
  const shown = view === "list" ? cards.filter((c) => !hidden.includes(c.column)) : cards;
  const emails = (board?.unmatched.length ?? 0) + (board?.cards ?? []).reduce((n, c) => n + c.proposals.length, 0);

  const open = (card: TrackerCard) =>
    navigate(
      {
        pathname: `/applications/${encodeURIComponent(card.id)}`,
        search: card.column === "not_sent" ? "" : "?tab=outcome",
      },
      { state: { from: `/tracker${params.toString() ? `?${params}` : ""}`, archive: true } },
    );

  useCommands(() => [
    { id: "tracker-board", title: "Tracker: board view", group: "Apply", disabled: view === "board", run: () => setParam({ view: "" }) },
    { id: "tracker-list", title: "Tracker: list view", group: "Apply", disabled: view === "list", run: () => setParam({ view: "list" }) },
    {
      id: "tracker-not-sent",
      title: hidden.includes("not_sent") ? "Tracker: show Not sent" : "Tracker: hide Not sent",
      group: "Apply",
      keywords: "skipped screened out",
      run: () => toggle("not_sent"),
    },
  ]);

  const sent = board ? board.cards.length - board.counts.not_sent : 0;
  return (
    <TrackerContext.Provider value={{ ...actions, drag, setDrag, pendingEmail, setPendingEmail, open }}>
      <Page width="wide" className="pb-4">
        <CommandBar
          title="Tracker"
          state={board ? `${sent} sent · ${board.counts.not_sent} not sent${emails ? ` · ${emails} email ${emails === 1 ? "update" : "updates"}` : ""}` : undefined}
          actions={
            <Segmented
              label="View"
              value={view}
              onChange={(id) => setParam({ view: id === "list" ? "list" : "" })}
              items={[
                { id: "board", label: "Board" },
                { id: "list", label: "List" },
              ]}
            />
          }
        />
        <TrackerFilters
          filters={filters}
          onChange={(f) => setParam({ q: f.q, from: f.from, until: f.until, email: f.email ? "1" : "" })}
          hidden={hidden}
          onShow={toggle}
        />
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
          {board?.last_synced ? `Email last checked ${shortDate(board.last_synced)}.` : "Email not checked yet."}
          <InlineHelp label="checking email">
            In Claude Desktop, with Gmail and ResumeTailor connected, ask: “{ASK_CLAUDE}”. Updates appear
            here to accept; nothing is recorded until you do.
          </InlineHelp>
          <CopyButton label="Copy the request" text={ASK_CLAUDE} />
        </p>
        {loadError && !board ? (
          <EmptyState title="Could not load the tracker">{describe(loadError).detail}</EmptyState>
        ) : !board ? (
          <Skeleton className="h-64 w-full" />
        ) : board.cards.length === 0 ? (
          <EmptyState title="Nothing in Done yet">
            Applications you send (or skip) move to Done on the Apply page and show here.
          </EmptyState>
        ) : (
          <>
            <EmailTray proposals={board.unmatched} />
            {view === "list" ? (
              <TrackerList cards={shown} />
            ) : (
              <TrackerBoardView cards={cards} hidden={hidden} onHide={toggle} />
            )}
          </>
        )}
      </Page>
    </TrackerContext.Provider>
  );
}
