import { useNavigate } from "react-router-dom";
import { Button, EmptyState } from "../../components/ui";
import { SOURCES_PATH } from "../../lib/applyPage";

/**
 * The In progress tab's empty state: pick job sources when every board is off, otherwise
 * when the last search ran, with Find jobs now and a link to the finished applications.
 */
export function ProgressEmpty({
  anySource,
  finding,
  lastChecked,
  hasDone,
  onFind,
  onDone,
}: {
  anySource: boolean;
  /** An operation is running, so Find jobs now waits. */
  finding: boolean;
  lastChecked: string | null | undefined;
  hasDone: boolean;
  onFind: () => void;
  onDone: () => void;
}) {
  const navigate = useNavigate();
  if (!anySource)
    return (
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
    );
  return (
    <EmptyState
      title="No new postings"
      action={
        <Button variant="primary" disabled={finding} onClick={onFind}>
          Find jobs now
        </Button>
      }
    >
      {lastChecked
        ? `Last checked ${new Date(lastChecked).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}.`
        : "Nothing has been searched yet."}
      {hasDone && (
        <>
          {" "}
          <button type="button" className="rt-link" onClick={onDone}>
            See finished applications
          </button>
        </>
      )}
    </EmptyState>
  );
}
