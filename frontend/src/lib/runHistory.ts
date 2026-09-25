import type { JobBullet, RunHistoryEntry } from "../api";

/** Case-insensitive match of every word in `query` against the run's role and company. */
export function matchesRunQuery(run: RunHistoryEntry, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = `${run.title} ${run.company ?? ""}`.toLowerCase();
  return words.every((w) => haystack.includes(w));
}

export type RunSort = "started" | "title" | "company" | "status" | "coverage" | "pages";
export type RunStatusFilter = "" | "succeeded" | "failed" | "cancelled" | "active";

function coverageRatio(run: RunHistoryEntry): number {
  return run.coverage_total ? (run.coverage_matched ?? 0) / run.coverage_total : -1;
}

/** Runs matching the search words and the status filter ("active" = queued or running). */
export function filterRuns(
  runs: RunHistoryEntry[],
  query: string,
  status: RunStatusFilter,
): RunHistoryEntry[] {
  return runs.filter(
    (run) =>
      matchesRunQuery(run, query) &&
      (!status ||
        (status === "active"
          ? run.status === "queued" || run.status === "running"
          : run.status === status)),
  );
}

/** A sorted copy; ties fall back to newest first so the order never jumps. */
export function sortRuns(
  runs: RunHistoryEntry[],
  sort: RunSort,
  direction: "asc" | "desc",
): RunHistoryEntry[] {
  const sign = direction === "asc" ? 1 : -1;
  const key = (a: RunHistoryEntry, b: RunHistoryEntry): number => {
    switch (sort) {
      case "title":
        return a.title.localeCompare(b.title);
      case "company":
        return (a.company ?? "").localeCompare(b.company ?? "");
      case "status":
        return a.status.localeCompare(b.status);
      case "coverage":
        return coverageRatio(a) - coverageRatio(b);
      case "pages":
        return (a.pages ?? -1) - (b.pages ?? -1);
      default:
        return a.created_at.localeCompare(b.created_at);
    }
  };
  return [...runs].sort((a, b) => sign * key(a, b) || b.created_at.localeCompare(a.created_at));
}

export type CompareKind = "same" | "changed" | "only_a" | "only_b";

export interface CompareRow {
  bulletId: string;
  a: string | null;
  b: string | null;
  kind: CompareKind;
}

export interface CompareGroup {
  key: string;
  entry: string;
  section: string;
  rows: CompareRow[];
}

/**
 * Two runs' bullet sets side by side, grouped by entry in the first run's order (then
 * entries only the second run used). A bullet counts as present when the run's final
 * document shows it.
 */
export function compareRuns(a: JobBullet[], b: JobBullet[]): CompareGroup[] {
  const textOf = (row: JobBullet | undefined) => (row ? row.current_text : null);
  const byIdB = new Map(b.map((row) => [row.bullet_id, row]));
  const groups = new Map<string, CompareGroup>();
  const group = (row: JobBullet) => {
    const key = `${row.section_title}\u0000${row.entry_label}`;
    let g = groups.get(key);
    if (!g) {
      g = { key, entry: row.entry_label, section: row.section_title, rows: [] };
      groups.set(key, g);
    }
    return g;
  };
  const seen = new Set<string>();
  for (const row of [...a, ...b]) {
    if (seen.has(row.bullet_id)) continue;
    seen.add(row.bullet_id);
    const left = textOf(a.find((r) => r.bullet_id === row.bullet_id));
    const right = textOf(byIdB.get(row.bullet_id));
    if (left == null && right == null) continue;
    const kind: CompareKind =
      left == null ? "only_b" : right == null ? "only_a" : left === right ? "same" : "changed";
    group(row).rows.push({ bulletId: row.bullet_id, a: left, b: right, kind });
  }
  return [...groups.values()].filter((g) => g.rows.length > 0);
}

/** Counts for the compare dialog's summary line. */
export function compareCounts(groups: CompareGroup[]): Record<CompareKind, number> {
  const counts: Record<CompareKind, number> = { same: 0, changed: 0, only_a: 0, only_b: 0 };
  for (const g of groups) for (const r of g.rows) counts[r.kind] += 1;
  return counts;
}
