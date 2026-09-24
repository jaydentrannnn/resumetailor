import type { DailyStatus } from "../api";

/** Percent of a daily pass processed, clamped to 0–100. */
export function runProgressPercent(processed: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0;
  const pct = Math.round((processed / total) * 100);
  return Math.max(0, Math.min(100, pct));
}

/** Human-readable one-liner for the current phase of a daily pass. */
export function describePhase(status: DailyStatus | null): string {
  if (!status) return "";
  if (status.running) {
    if (status.phase === "discovering") {
      return status.source_id ? `Fetching source ${status.source_id}…` : "Fetching sources…";
    }
    if (status.phase === "processing") {
      const position = Math.min(status.processed + 1, Math.max(status.total, 1));
      const action = status.fetch_only ? "Recording" : "Processing";
      return status.current
        ? `${action} ${position}/${status.total}: ${status.current}`
        : `${action} ${position}/${status.total}…`;
    }
    return "Starting…";
  }
  if (status.phase === "done") {
    const reason = (status.summary?.reason as string) || "";
    if (reason) return `Last run skipped: ${reason}`;
    const modeDesc = status.fetch_only ? " (fetch only)" : status.dry_run ? " (dry run)" : "";
    return `Last run finished${modeDesc}`;
  }
  return "Idle";
}

/** Total across status-chip counts. */
export function sumStatusCounts(counts: Record<string, number>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0);
}
