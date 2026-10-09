import { useEffect, useState } from "react";
import { fetchUsage, type UsageModel, type UsageSummary } from "../../api";
import { Card } from "../../components/ui";

const DAYS = 30;

function money(usd: number): string {
  if (usd === 0) return "$0.00";
  return usd < 0.01 ? "under $0.01" : `$${usd.toFixed(2)}`;
}

function tokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

function cost(row: UsageModel): string {
  if (row.billing === "no_per_token") return "No per-token charge";
  return row.usd === null ? "Price unknown" : money(row.usd);
}

/** Tokens and estimated spend from the runs this computer actually made. */
export function UsageCard() {
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    fetchUsage(DAYS)
      .then(setUsage)
      .catch(() => setFailed(true));
  }, []);

  let body;
  if (failed) body = <p className="text-sm text-ink-muted">Usage could not be loaded.</p>;
  else if (!usage) body = <p className="text-sm text-ink-muted">Loading…</p>;
  else if (usage.runs === 0)
    body = <p className="text-sm text-ink-muted">No tailoring runs in the last {DAYS} days.</p>;
  else
    body = (
      <>
        <p className="text-sm text-ink">
          <span className="font-semibold">{usage.runs}</span> run{usage.runs === 1 ? "" : "s"}
          {usage.usd !== null && (
            <>
              {" · about "}
              <span className="font-semibold">{money(usage.usd)}</span> at list prices
            </>
          )}
        </p>
        <ul className="mt-3 divide-y divide-line text-sm">
          {usage.models.map((row) => (
            <li
              key={`${row.origin}|${row.model}`}
              className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2"
            >
              <span className="min-w-0 break-all font-mono text-xs text-ink">
                {row.model || row.origin}
              </span>
              <span className="text-xs tabular-nums text-ink-muted">
                {tokens(row.input_tokens + row.output_tokens)} tokens · {cost(row)}
              </span>
            </li>
          ))}
        </ul>
        {!usage.complete && (
          <p className="mt-2 text-xs text-ink-muted">
            Some requests did not report usage or use a model without a known price, so the real
            total may be higher.
          </p>
        )}
      </>
    );
  return (
    <Card
      title="Usage"
      description={`What tailoring runs used in the last ${DAYS} days, across every profile. Check your provider's billing page for exact charges.`}
    >
      {body}
    </Card>
  );
}
