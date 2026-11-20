/** The test search the Connect dialog runs right after a search engine's keys are saved. */
import type { SourceConfig, SourceTestResult } from "../api";
import { PROVIDER_LABELS, type SearchProvider } from "./sources";

/** One broad, unsaved search on `provider`: enough to show the keys are accepted. */
export function connectionProbe(provider: SearchProvider): SourceConfig {
  return {
    id: `connect-test-${provider}`,
    kind: "job_search",
    provider,
    query: "intern",
    url: "",
    categories: [],
    enabled: true,
    max_age_days: 30,
  };
}

/** Null when the test search ran; otherwise what to tell the student. */
export function keyTestProblem(provider: SearchProvider, result: SourceTestResult): string | null {
  if (!result.errors.length) return null;
  return (
    `The keys are saved, but a test search on ${PROVIDER_LABELS[provider]} failed: ` +
    `${result.errors[0]}. Check the keys and save again.`
  );
}
