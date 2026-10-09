import type { ApplicationRow } from "../../api";
import { Button } from "../../components/ui";
import { canContinueFill, canReopenFill, type OpenTabs } from "../../lib/applicationRows";

/** Needs you tab, selection bar: Continue fill and Reopen and fill for the checked rows. */
export function ReviewToolbar({
  selected,
  openTabs,
  busy,
  active,
  browserUsable,
  onContinue,
  onReopen,
}: {
  selected: ApplicationRow[];
  openTabs: OpenTabs;
  busy: boolean;
  active: boolean;
  browserUsable: boolean;
  onContinue: (ids: string[]) => void;
  onReopen: (rows: ApplicationRow[]) => void;
}) {
  const continueIds = selected
    .filter((row) => canContinueFill(row, openTabs))
    .map((row) => row.source_job_id);
  const reopenRows = selected.filter(canReopenFill);
  const notConnected = "The browser isn't available — see Apply settings";
  const idleNote = active ? "Available when the current Apply task finishes" : undefined;
  return (
    <>
      {selected.length > continueIds.length && (
        <span className="mr-1 text-xs text-ink-muted">
          {selected.length - continueIds.length} selected can't continue (tab closed or not started)
        </span>
      )}
      <Button
        variant="attention"
        size="sm"
        disabled={busy || active || !continueIds.length || !browserUsable}
        title={
          idleNote ?? (browserUsable ? "Resume the fills in their open tabs" : notConnected)
        }
        onClick={() => onContinue(continueIds)}
      >
        Continue fill ({continueIds.length})
      </Button>
      <Button
        variant="attention"
        size="sm"
        disabled={busy || active || !reopenRows.length || !browserUsable}
        title={
          idleNote ??
          (browserUsable ? "Open the postings again and fill from the start" : notConnected)
        }
        onClick={() => onReopen(reopenRows)}
      >
        Reopen and fill ({reopenRows.length})
      </Button>
    </>
  );
}
