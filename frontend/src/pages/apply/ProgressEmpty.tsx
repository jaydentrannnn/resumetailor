import { useNavigate } from "react-router-dom";
import { Button, EmptyState } from "../../components/ui";
import { SOURCES_PATH } from "../../lib/applyPage";
import { outcomeCopy, searchOutcome } from "../../lib/searchOutcome";
import { useGuide } from "../../state/guideState";
import { useRunState } from "../../state/runState";
import { useSourcesStatus } from "./sourceHooks";

/**
 * The In progress tab's empty state: pick job sources when every board is off, otherwise
 * why the last search added nothing (lists failed, found nothing, filters removed
 * everything, or nothing new; `lib/searchOutcome.ts`), with Find jobs now and a link to
 * the finished applications. While the applying half of setup is unfinished, it also
 * offers "Set up applying". Both views show the reason: it explains an empty page.
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
  const { settings } = useRunState();
  const status = useSourcesStatus(lastChecked);
  const copy = outcomeCopy(searchOutcome(settings.apply.sources, status));
  // Failed, empty or filtered searches are fixed on Job sources; nothing new is not.
  const fixOnSources = copy !== null && copy.title !== "No new postings";
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
  // When the lists last ran (Find jobs included), the run the reason above describes;
  // the nightly run's start only when there is no source status yet.
  const checkedAt = status?.last_run_at ?? lastChecked;
  const when = checkedAt
    ? new Date(checkedAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : null;
  return (
    <EmptyState
      title={copy?.title ?? "No new postings"}
      action={
        <div className="flex flex-wrap justify-center gap-2">
          {/* One solid button: the fix when the lists or filters are the problem. */}
          {fixOnSources && (
            <Button variant="primary" onClick={() => navigate(SOURCES_PATH)}>
              Check job sources
            </Button>
          )}
          <Button variant={fixOnSources ? "plain" : "primary"} disabled={finding} onClick={onFind}>
            Find jobs now
          </Button>
          {setUp}
        </div>
      }
    >
      {copy && <>{copy.detail} </>}
      {when ? `Last checked ${when}.` : "Nothing has been searched yet."}
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
