import type { RunEstimate } from "../api";

/**
 * Formats an estimate for the line under "Tailor resume"; null only when there is no
 * estimate. Always shows the model work (calls, tokens); dollars only where the backend
 * bills per token. Local models and Ollama Cloud have no per-token price.
 */
export function describeEstimate(estimate: RunEstimate | null): string | null {
  if (!estimate) return null;
  const calls = `${estimate.calls} model call${estimate.calls === 1 ? "" : "s"}`;
  const tokens = `~${Math.max(1, Math.round((estimate.input_tokens + estimate.output_tokens) / 1000))}k tokens`;
  const billing = estimate.billing ?? (estimate.local ? "local" : "per_token");
  if (billing === "local")
    return `About ${calls}, ${tokens}. No per-token charge: it runs on your computer.`;
  if (billing === "subscription")
    return `About ${calls}, ${tokens}. No per-token charge: it counts against your Ollama Cloud plan.`;
  if (estimate.usd === null) return `About ${calls}, ${tokens} (price unknown for this model)`;
  const usd = estimate.usd < 0.01 ? "under $0.01" : `about $${estimate.usd.toFixed(2)}`;
  return `About ${calls}, ${usd} on your API key. Repeat runs of a posting cost less.`;
}
