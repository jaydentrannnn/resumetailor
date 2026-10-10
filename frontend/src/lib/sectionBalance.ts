import type { IncludeOptions, ResumeOutline } from "../api";
import { effectiveSectionOrder } from "./sectionOrder";

/** Divider step and the smallest segment, in percent. */
export const STEP = 5;
const UNITS = 100 / STEP;

export type BalanceSection = { id: string; title: string; kind: string };

/**
 * The sections the balance bar splits: experience/project sections in the run's section
 * order that are ticked in Include, keep at least one included entry with bullets, and
 * (for projects) are enabled in the template. Same rules as `IncludePanel`.
 */
export function activeSections(outline: ResumeOutline, include: IncludeOptions): BalanceSection[] {
  const excludedSections = new Set(include.exclude_sections);
  const excludedEntries = new Set(include.exclude_entries);
  const projectsEnabled = outline.sections_enabled.projects !== false;
  const byId = new Map(outline.sections.map((s) => [s.id, s]));
  return effectiveSectionOrder(include.section_order, outline.sections)
    .map((id) => byId.get(id))
    .filter((s): s is ResumeOutline["sections"][number] => Boolean(s))
    .filter((s) => s.kind === "experience" || (s.kind === "project" && projectsEnabled))
    .filter((s) => !excludedSections.has(s.id))
    .filter((s) => s.entries.some((e) => e.bullets > 0 && !excludedEntries.has(e.id)))
    .map(({ id, title, kind }) => ({ id, title, kind }));
}

/** Raw relative weights for `active`: stored, else the legacy experience share, else even. */
function rawWeights(
  active: BalanceSection[],
  weights: Record<string, number> | null,
  legacyShare: number | null,
): number[] {
  if (weights) {
    const known = active.map((s) => weights[s.id]).filter((w): w is number => w !== undefined);
    const fallback = known.length ? known.reduce((a, b) => a + b, 0) / known.length : 1;
    return active.map((s) => Math.max(0, weights[s.id] ?? fallback));
  }
  const experience = active.filter((s) => s.kind === "experience").length;
  const projects = active.length - experience;
  if (legacyShare !== null && experience && projects) {
    return active.map((s) =>
      s.kind === "experience" ? legacyShare / experience : (1 - legacyShare) / projects,
    );
  }
  return active.map(() => 1);
}

/**
 * Integer percents for each active section, in `STEP` steps, each at least `STEP`,
 * summing to 100 (largest-remainder rounding). A section missing from `weights` gets
 * the mean of the known ones; with no weights, the legacy two-group share converts.
 */
export function toShares(
  active: BalanceSection[],
  weights: Record<string, number> | null,
  legacyShare: number | null = null,
): number[] {
  const n = active.length;
  if (n === 0) return [];
  let raw = rawWeights(active, weights, legacyShare);
  const total = raw.reduce((a, b) => a + b, 0);
  if (total <= 0) raw = raw.map(() => 1);
  const sum = raw.reduce((a, b) => a + b, 0);
  const quota = raw.map((w) => (w / sum) * UNITS);
  const units = quota.map((q) => Math.max(1, Math.floor(q)));
  let given = units.reduce((a, b) => a + b, 0);
  while (given < UNITS) {
    let best = 0;
    for (let i = 1; i < n; i++) if (quota[i] - units[i] > quota[best] - units[best]) best = i;
    units[best]++;
    given++;
  }
  while (given > UNITS) {
    let best = -1;
    for (let i = 0; i < n; i++) if (units[i] > 1 && (best < 0 || units[i] > units[best])) best = i;
    if (best < 0) break;
    units[best]--;
    given--;
  }
  return units.map((u) => u * STEP);
}

/**
 * Move divider `i` (between `shares[i]` and `shares[i + 1]`) by `delta` percent, snapped
 * to `STEP`. Only those two neighbours change; each stays at least `STEP`.
 */
export function moveDivider(shares: number[], i: number, delta: number): number[] {
  if (i < 0 || i >= shares.length - 1) return shares;
  const snapped = Math.round(delta / STEP) * STEP;
  const clamped = Math.max(STEP - shares[i], Math.min(shares[i + 1] - STEP, snapped));
  if (clamped === 0) return shares;
  const next = [...shares];
  next[i] += clamped;
  next[i + 1] -= clamped;
  return next;
}

/** Put divider `i` at `position` percent from the bar's left edge (pointer drags). */
export function setDivider(shares: number[], i: number, position: number): number[] {
  const left = shares.slice(0, i).reduce((a, b) => a + b, 0);
  return moveDivider(shares, i, position - left - shares[i]);
}

/**
 * Merge edited `shares` back into the stored weights. Sections not in `active` keep
 * their stored weight, so re-ticking one restores its share; the active ones are scaled
 * to their previous combined weight so those stored weights keep their meaning.
 */
export function fromShares(
  active: BalanceSection[],
  shares: number[],
  previous: Record<string, number> | null,
): Record<string, number> {
  const prev = previous ?? {};
  const known = active.every((s) => prev[s.id] !== undefined);
  const prevTotal = known ? active.reduce((a, s) => a + prev[s.id], 0) : 0;
  const scale = prevTotal > 0 ? prevTotal / 100 : 1;
  const next = { ...prev };
  active.forEach((s, i) => {
    next[s.id] = Math.round(shares[i] * scale * 10000) / 10000;
  });
  return next;
}

/** Even weights for every active section — what turning the bar on writes. */
export function evenWeights(active: BalanceSection[]): Record<string, number> {
  return Object.fromEntries(active.map((s) => [s.id, 1]));
}
