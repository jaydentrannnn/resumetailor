import type { DailyStatus } from "../../api";
import { Meter, Tile } from "../../components/ui";
import { runProgressPercent } from "../../lib/applicationStatus";
import { AttentionList } from "./AttentionList";

/**
 * The nightly run: its progress while it runs, then "Needs your review" listing what it
 * left for the user. Renders nothing once a finished run left nothing to review, and
 * nothing for a Find jobs, which runs through the same pass with `fetch_only` and shows
 * its own progress in the operation banner.
 */
export function NightlyRunTile({ daily }: { daily: DailyStatus | null }) {
  if (!daily?.summary || daily.fetch_only || !(daily.running || daily.finished_at)) return null;
  const items = daily.summary.attention ?? [];
  if (!daily.running && !items.length) return null;
  const progress = `${daily.processed} of ${daily.total} processed${daily.current ? ` · ${daily.current}` : ""}`;
  return (
    <Tile
      title={
        daily.running ? (
          "Nightly run in progress"
        ) : (
          <>
            Needs your review
            <span className="ml-2 font-mono text-xs font-normal text-ink-muted">
              {items.length}
            </span>
          </>
        )
      }
      meta={daily.running ? <span className="font-mono">{progress}</span> : "From the nightly run"}
      aria-live="polite"
    >
      {daily.running && (
        <Meter
          className={items.length ? "mb-4" : ""}
          label="Nightly run progress"
          value={runProgressPercent(daily.processed, daily.total)}
          valueText={progress}
        />
      )}
      <AttentionList items={items} />
    </Tile>
  );
}
