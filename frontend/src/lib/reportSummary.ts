import type { KeywordGap, RunReport } from "../api";

/** "Matched 8 of 10 required skills · 1 page", or the reason matching can't be read. */
export function reportHeadline(report: RunReport): string {
  const pages = `${report.pages} page${report.pages === 1 ? "" : "s"}${report.pages_are_estimated ? " (estimated)" : ""}`;
  if (report.extraction_diagnosis)
    return `Skill match couldn't be measured for this posting · ${pages}`;
  if (report.coverage_total === 0) return `No required skills were listed · ${pages}`;
  return `Matched ${report.coverage_matched} of ${report.coverage_total} required skills · ${pages}`;
}

/** "1 required and 9 nice-to-have skills aren't on your resume", or null when none. */
export function missingSummary(groups: GapGroups): string | null {
  const required = groups.missing.filter((m) => m.required).length;
  const optional = groups.missing.length - required;
  if (!required && !optional) return null;
  const parts = [
    required ? `${required} required` : "",
    optional ? `${optional} nice-to-have` : "",
  ].filter(Boolean);
  const total = required + optional;
  return `${parts.join(" and ")} skill${total === 1 ? "" : "s"} ${total === 1 ? "isn't" : "aren't"} on your resume`;
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
  if (m) return `a bullet shows "${m[1]}"`;
  return raw;
}

export interface GapGroups {
  /** Nothing in the master resume supports these. Never added for you. `required` is
   * the posting's must-have list (what "Required skills covered" counts), not `band`. */
  missing: { phrase: string; band?: string; required: boolean }[];
  /** The resume lists them (skills, tech, coursework), but no bullet shows them. */
  untagged: { phrase: string; where: string[] }[];
  /** A bullet uses a different name for the same thing. */
  renamed: { phrase: string; where: string[] }[];
}

export function gapGroups(report: RunReport): GapGroups {
  const gaps = [...report.gaps].sort(byBand);
  const missing: GapGroups["missing"] = gaps
    .filter((g) => g.reason === "no_evidence")
    .map((g) => ({ phrase: g.phrase, band: g.band, required: g.importance === "must_have" }));
  // Every diagnosed gap, whatever its group: a must-have the resume lists off-bullet
  // belongs under "not on a bullet", not a second time under "missing".
  const seen = new Set(gaps.map((g) => g.phrase.toLowerCase()));
  for (const phrase of report.missing_must_haves) {
    if (!seen.has(phrase.toLowerCase())) missing.push({ phrase, band: "critical", required: true });
  }
  // Stable: band order is kept within each group.
  missing.sort((a, b) => Number(b.required) - Number(a.required));
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
