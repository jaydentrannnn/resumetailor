import { useNavigate } from "react-router-dom";
import { Button, EmptyState } from "../../components/ui";
import { SOURCES_PATH } from "../../lib/applyPage";
import { useGuide } from "../../state/guideState";

/**
 * The In progress tab's empty state: pick job sources when every board is off, otherwise
 * when the last search ran, with Find jobs now and a link to the finished applications.
 * While the applying half of setup is unfinished, it also offers "Set up applying".
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
  // Until stage 2 of setup is finished, offer it beside the search button.
  const setUp = useGuide().applyDone === false && (
    <Button variant="plain" onClick={() => navigate("/welcome")}>
      Set up applying
    </Button>
  );
  if (!anySource)
    return (
      <EmptyState
        title="Choose what to search for"
        action={
          <div className="flex flex-wrap justify-center gap-2">
            <Button variant="primary" onClick={() => navigate(SOURCES_PATH)}>
              Pick job sources
            </Button>
            {setUp}
          </div>
        }
      >
        Every job board is turned off, so there is nothing to find.
      </EmptyState>
    );
  return (
    <EmptyState
      title="No new postings"
      action={
        <div className="flex flex-wrap justify-center gap-2">
          <Button variant="primary" disabled={finding} onClick={onFind}>
            Find jobs now
          </Button>
          {setUp}
        </div>
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
