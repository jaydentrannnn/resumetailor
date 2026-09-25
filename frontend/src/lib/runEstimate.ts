import type { RunEstimate } from "../api";

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
