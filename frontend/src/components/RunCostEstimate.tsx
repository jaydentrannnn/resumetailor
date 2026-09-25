import { useEffect, useState } from "react";
import { estimateJob, type JobSettings, type RunEstimate } from "../api";
import { describeEstimate } from "../lib/runEstimate";

/** Debounced usage and cost preview, shown for every backend (`lib/runEstimate.ts`). */
export function RunCostEstimate({
  jdText,
  settings,
  enabled,
}: {
  jdText: string;
  settings: JobSettings;
  enabled: boolean;
}) {
  const [estimate, setEstimate] = useState<RunEstimate | null>(null);
  useEffect(() => {
    if (!enabled || !jdText.trim()) {
      setEstimate(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      estimateJob(jdText, settings)
        .then((result) => {
          if (!cancelled) setEstimate(result);
        })
        .catch(() => {
          if (!cancelled) setEstimate(null); // advisory only: never block a run
        });
    }, 800);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jdText, settings, enabled]);
  const text = describeEstimate(estimate);
  if (!text) return null;
  return <p className="mt-2 text-center text-xs text-ink-muted">{text}</p>;
}
