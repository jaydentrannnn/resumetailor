export type ResumeQuality = {
  fill_ratio: number | null;
  fill_target: number | null;
  /** Fraction under `fill_target` that still counts as met (one line of the page). */
  fill_tolerance?: number;
  estimated: boolean;
  verified: boolean;
  missing_sections: { id: string; title: string; reason: string }[];
};

export function qualityWarnings(quality?: ResumeQuality | null): string[] {
  if (!quality) return [];
  const warnings: string[] = [];
  if (!quality.verified)
    warnings.push("Resume quality could not be verified. Prepare again before Fill.");
  if (
    quality.fill_ratio != null &&
    quality.fill_target != null &&
    quality.fill_ratio < quality.fill_target - (quality.fill_tolerance ?? 0) - 1e-9
  ) {
    warnings.push(
      `${quality.estimated ? "Estimated page fill" : "Page fill"} is ${Math.round(quality.fill_ratio * 100)}%; target is ${Math.round(quality.fill_target * 100)}%.`,
    );
  }
  warnings.push(...quality.missing_sections.map((s) => `${s.title} is missing: ${s.reason}.`));
  return warnings;
}
