import { useEffect, useState } from "react";
import { type ResumeOutline, fetchResumeOutline } from "../api";

let inFlight: Promise<ResumeOutline> | null = null;

/** One request shared by every caller mounting at once; a later mount fetches afresh. */
function loadOutline(): Promise<ResumeOutline> {
  if (!inFlight) {
    inFlight = fetchResumeOutline().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

/**
 * The master resume's outline, refetched on every mount so an edit made on the Master
 * resume tab shows up the next time Tailor is visited. Components mounted together
 * (Include and Section balance) share one request.
 */
export function useResumeOutline(): { outline: ResumeOutline | null; error: string | null } {
  const [outline, setOutline] = useState<ResumeOutline | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadOutline()
      .then((o) => {
        if (!cancelled) setOutline(o);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return { outline, error };
}
