import type { DailyStatus } from "../../api";
import { Meter } from "../../components/ui";
import { runProgressPercent } from "../../lib/applicationStatus";
import { AttentionList } from "./AttentionList";

const finished = (at: string) =>
  new Date(at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/**
 * The nightly run on one line: its progress while it runs, then when it finished and,
 * folded, what it left for the user. Renders nothing once a finished run left nothing
 * to review, and nothing for a Find jobs, which runs through the same pass with
 * `fetch_only` and shows its own progress in the operation banner.
 */
export function NightlyRunStrip({ daily }: { daily: DailyStatus | null }) {
  if (!daily?.summary || daily.fetch_only || !(daily.running || daily.finished_at)) return null;
  const items = daily.summary.attention ?? [];
  if (!daily.running && !items.length) return null;
  const progress = `${daily.processed} of ${daily.total} processed${daily.current ? ` · ${daily.current}` : ""}`;
  return (
    <section
      aria-label="Nightly run"
      aria-live="polite"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line pb-3 text-sm"
    >
      <span className="font-medium text-ink">
        {daily.running ? "Nightly run in progress" : "Nightly run"}
      </span>
      {daily.running ? (
        <>
          <Meter
            className="w-40"
            label="Nightly run progress"
            value={runProgressPercent(daily.processed, daily.total)}
            valueText={progress}
          />
          <span className="min-w-0 truncate font-mono text-xs text-ink-muted">{progress}</span>
        </>
      ) : (
        <span className="text-ink-muted">Finished {finished(daily.finished_at)}</span>
      )}
      <div className="w-full min-w-0 sm:w-auto sm:flex-1">
        <AttentionList items={items} collapsible />
      </div>
    </section>
  );
}
