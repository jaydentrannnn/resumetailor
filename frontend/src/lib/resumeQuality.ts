/** The exported PDF's text read back (`document/pdf_text_check.py`). */
export type PdfTextCheck = {
  status: "verified" | "issues" | "unverified";
  /** Need review before Fill; also counted in `qualityWarnings`. */
  issues: string[];
  /** Informational only, e.g. the PDF could not be read. */
  advisories: string[];
  checked_items?: number;
};

export type ResumeQuality = {
  fill_ratio: number | null;
  fill_target: number | null;
  /** Fraction under `fill_target` that still counts as met (one line of the page). */
  fill_tolerance?: number;
  estimated: boolean;
  verified: boolean;
  missing_sections: { id: string; title: string; reason: string }[];
  /** Absent on runs from before the check and when the page count was estimated. */
  pdf_text?: PdfTextCheck | null;
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
  if (quality.estimated)
    warnings.push(
      "Page count is estimated (PDF measurement was unavailable), so the page fit isn't verified.",
    );
  warnings.push(...quality.missing_sections.map((s) => `${s.title} is missing: ${s.reason}.`));
  warnings.push(...(quality.pdf_text?.issues ?? []));
  return warnings;
}
