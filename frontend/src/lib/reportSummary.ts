import type { KeywordGap, RunReport } from "../api";

/** "Matched 8 of 10 required skills · 1 page", or the reason matching can't be read. */
export function reportHeadline(report: RunReport): string {
  const pages = `${report.pages} page${report.pages === 1 ? "" : "s"}${report.pages_are_estimated ? " (estimated)" : ""}`;
  if (report.extraction_diagnosis)
    return `Skill match couldn't be measured for this posting · ${pages}`;
  if (report.coverage_total === 0) return `No required skills were listed · ${pages}`;
  return `Matched ${report.coverage_matched} of ${report.coverage_total} required skills · ${pages}`;
}

const BAND_RANK: Record<string, number> = {
  critical: 4,
  high: 3,
  meaningful: 2,
  preferred: 1,
  low_signal: 0,
};

const byBand = (a: KeywordGap, b: KeywordGap) =>
  (BAND_RANK[b.band ?? "meaningful"] ?? 0) - (BAND_RANK[a.band ?? "meaningful"] ?? 0);

/** One evidence snippet from `report.diagnose_gaps`, in words. */
export function describeEvidence(raw: string): string {
  let m = raw.match(/^project tech '([^']*)': "(.*)"$/);
  if (m) return `listed as "${m[2]}" in a project's tech`;
  m = raw.match(/^skills '([^']*)': "(.*)"$/);
  if (m) return `listed as "${m[2]}" under ${m[1]} skills`;
  m = raw.match(/^coursework: "(.*)"$/);
  if (m) return `in your coursework as "${m[1]}"`;
  m = raw.match(/^bullet tag: "(.*)"$/);
  if (m) return `a bullet is tagged "${m[1]}"`;
  return raw;
}

export interface GapGroups {
  /** Nothing in the master resume supports these. Never added for you. */
  missing: { phrase: string; band?: string }[];
  /** The resume mentions them, but no bullet is tagged with them. */
  untagged: { phrase: string; where: string[] }[];
  /** A bullet uses a different name for the same thing. */
  renamed: { phrase: string; where: string[] }[];
}

export function gapGroups(report: RunReport): GapGroups {
  const gaps = [...report.gaps].sort(byBand);
  const missing: GapGroups["missing"] = gaps
    .filter((g) => g.reason === "no_evidence")
    .map((g) => ({ phrase: g.phrase, band: g.band }));
  const seen = new Set(missing.map((m) => m.phrase.toLowerCase()));
  for (const phrase of report.missing_must_haves) {
    if (!seen.has(phrase.toLowerCase())) missing.push({ phrase, band: "critical" });
  }
  return {
    missing,
    untagged: gaps
      .filter((g) => g.reason === "untagged_evidence")
      .map((g) => ({ phrase: g.phrase, where: g.evidence.map(describeEvidence) })),
    renamed: gaps
      .filter((g) => g.reason === "near_miss")
      .map((g) => ({ phrase: g.phrase, where: g.evidence.map(describeEvidence) })),
  };
}
