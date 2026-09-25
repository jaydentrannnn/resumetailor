import { useEffect, useState } from "react";
import { estimateJob, type JobSettings, type RunEstimate } from "../api";

/** Formats an estimate for the line under "Tailor resume"; null when nothing to show. */
export function describeEstimate(estimate: RunEstimate | null): string | null {
  if (!estimate || estimate.local) return null;
  const calls = `${estimate.calls} model call${estimate.calls === 1 ? "" : "s"}`;
  if (estimate.usd === null) {
    const tokens = Math.round((estimate.input_tokens + estimate.output_tokens) / 1000);
    return `About ${calls}, ~${tokens}k tokens (price unknown for this model)`;
  }
  const usd = estimate.usd < 0.01 ? "under $0.01" : `about $${estimate.usd.toFixed(2)}`;
  return `About ${calls}, ${usd} on your API key. Repeat runs of a posting cost less.`;
}

/** Debounced cost preview for paid backends; renders nothing for local models. */
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
