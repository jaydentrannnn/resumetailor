import type { ApplicationRow } from "../../api";
import { Button } from "../../components/ui";
import { canContinueFill, canReopenFill, type OpenTabs } from "../../lib/applicationRows";
import { EXCLUSIVE_NOTE, isHeld } from "../../lib/applyPage";

/** Needs you tab, selection bar: Continue fill and Start over for the checked rows. */
export function ReviewToolbar({
  selected,
  openTabs,
  busy,
  exclusiveBusy,
  held,
  browserUsable,
  onContinue,
  onReopen,
}: {
  selected: ApplicationRow[];
  openTabs: OpenTabs;
  busy: boolean;
  /** Find jobs or the nightly run has Apply to itself. */
  exclusiveBusy: boolean;
  /** Rows a running task still owns (a Fill coming back to them, say): left out. */
  held: Set<string>;
  browserUsable: boolean;
  onContinue: (ids: string[]) => void;
  onReopen: (rows: ApplicationRow[]) => void;
}) {
  const free = selected.filter((row) => !isHeld(row, held));
  const continueIds = free
    .filter((row) => canContinueFill(row, openTabs))
    .map((row) => row.source_job_id);
  const reopenRows = free.filter(canReopenFill);
  const notConnected = "The browser isn't available — see Apply settings";
  const idleNote = exclusiveBusy ? EXCLUSIVE_NOTE : undefined;
  return (
    <>
      {selected.length > continueIds.length && (
        <span className="mr-1 text-xs text-ink-muted">
          {selected.length - continueIds.length} selected can't continue (not started yet)
        </span>
      )}
      <Button
        variant="attention"
        size="sm"
        disabled={busy || exclusiveBusy || !continueIds.length || !browserUsable}
        title={
          idleNote ??
          (browserUsable
            ? "Resume the fills (closed tabs reopen with the saved draft)"
            : notConnected)
        }
        onClick={() => onContinue(continueIds)}
      >
        Continue fill ({continueIds.length})
      </Button>
      <Button
        size="sm"
        disabled={busy || exclusiveBusy || !reopenRows.length || !browserUsable}
        title={
          idleNote ??
          (browserUsable ? "Open the postings again and fill from the start" : notConnected)
        }
        onClick={() => onReopen(reopenRows)}
      >
        Start over ({reopenRows.length})
      </Button>
    </>
  );
}
