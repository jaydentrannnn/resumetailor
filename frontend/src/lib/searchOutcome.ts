/** Why the In progress list is empty after a search, from each source's last run. */
import type { SourceConfig, SourcesStatus } from "../api";
import { countLabel } from "./countLabel";

export type SearchOutcome =
  /** No switched-on list has run yet, or the status could not be read. */
  | { kind: "unknown" }
  /** Every list that ran failed; `error` is the first reason. */
  | { kind: "failed"; lists: number; error: string }
  /** The lists ran and returned no postings. */
  | { kind: "empty"; lists: number; failed: number }
  /** Postings came back and the filters removed all of them. */
  | { kind: "filtered"; found: number; failed: number }
  /** Some postings passed the filters, and every one was already tracked. */
  | { kind: "nothing_new"; kept: number; failed: number };

/** The status the server records for a list that ran and returned nothing
 * (`daily_batch._source_status_entry`): an empty list, not a failure. */
export const NO_POSTINGS = "No postings found";

/**
 * Classifies the last search over the switched-on lists. A list counts as failed only when
 * it returned nothing and has a real error: the same field carries `NO_POSTINGS`.
 */
export function searchOutcome(
  sources: SourceConfig[],
  status: SourcesStatus | null | undefined,
): SearchOutcome {
  const runs = sources
    .filter((source) => source.enabled)
    .map((source) => status?.sources[source.id])
    .filter((run) => run !== undefined);
  if (!runs.length) return { kind: "unknown" };
  const failedRuns = runs.filter(
    (run) => run.error && run.error !== NO_POSTINGS && run.found === 0,
  );
  const failed = failedRuns.length;
  const found = runs.reduce((sum, run) => sum + run.found, 0);
  const kept = runs.reduce((sum, run) => sum + run.kept, 0);
  if (failed === runs.length)
    return { kind: "failed", lists: runs.length, error: failedRuns[0].error ?? "" };
  if (found === 0) return { kind: "empty", lists: runs.length, failed };
  if (kept === 0) return { kind: "filtered", found, failed };
  return { kind: "nothing_new", kept, failed };
}

/** The empty state's title and sentence for an outcome; null keeps the plain wording. */
export function outcomeCopy(outcome: SearchOutcome): { title: string; detail: string } | null {
  const alsoFailed = (n: number) =>
    n ? ` ${countLabel(n, "list")} also failed to load; see Job sources.` : "";
  switch (outcome.kind) {
    case "failed":
      return {
        title: "The job lists didn't load",
        detail:
          outcome.lists === 1
            ? `The list failed on the last search: ${outcome.error}.`
            : `All ${outcome.lists} lists failed on the last search. First problem: ${outcome.error}.`,
      };
    case "empty":
      return {
        title: "No postings found",
        detail:
          "The last search found no postings. Try adding lists or wider search words." +
          alsoFailed(outcome.failed),
      };
    case "filtered":
      return {
        title: "Your filters removed every posting",
        detail:
          `The last search found ${countLabel(outcome.found, "posting")}, and the filters ` +
          "(posting age, location, title words, eligibility) removed all of them." +
          alsoFailed(outcome.failed),
      };
    case "nothing_new":
      return {
        title: "No new postings",
        detail:
          `${countLabel(outcome.kept, "posting")} passed your filters, but you already have ` +
          "every one of them: each is finished, skipped or archived." +
          alsoFailed(outcome.failed),
      };
    default:
      return null;
  }
}
