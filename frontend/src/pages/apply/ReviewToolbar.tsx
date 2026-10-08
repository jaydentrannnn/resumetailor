import type { ApplicationRow } from "../../api";
import { Button } from "../../components/ui";
import { canContinueFill, canReopenFill, type OpenTabs } from "../../lib/applicationRows";

/** Needs you tab, selection bar: Continue fill and Reopen and fill for the checked rows. */
export function ReviewToolbar({
  selected,
  openTabs,
  busy,
  active,
  browserConnected,
  onContinue,
  onReopen,
}: {
  selected: ApplicationRow[];
  openTabs: OpenTabs;
  busy: boolean;
  active: boolean;
  browserConnected: boolean;
  onContinue: (ids: string[]) => void;
  onReopen: (rows: ApplicationRow[]) => void;
}) {
  const continueIds = selected
    .filter((row) => canContinueFill(row, openTabs))
    .map((row) => row.source_job_id);
  const reopenRows = selected.filter(canReopenFill);
  const notConnected = "Connect the browser in Apply settings first";
  const idleNote = active ? "Available when the current Apply task finishes" : undefined;
  return (
    <>
      {selected.length > continueIds.length && (
        <span className="mr-1 text-xs text-ink-muted">
          {selected.length - continueIds.length} selected can't continue (tab closed or not started)
        </span>
      )}
      <Button
        size="sm"
        disabled={busy || active || !continueIds.length || !browserConnected}
        title={
          idleNote ?? (browserConnected ? "Resume the fills in their open tabs" : notConnected)
        }
        onClick={() => onContinue(continueIds)}
      >
        Continue fill ({continueIds.length})
      </Button>
      <Button
        size="sm"
        disabled={busy || active || !reopenRows.length || !browserConnected}
        title={
          idleNote ??
          (browserConnected ? "Open the postings again and fill from the start" : notConnected)
        }
        onClick={() => onReopen(reopenRows)}
      >
        Reopen and fill ({reopenRows.length})
      </Button>
    </>
  );
}
