import { expect, it } from "vitest";
import { canFillAfterReview } from "./applicationRows";
import { qualityWarnings } from "./resumeQuality";

it("shows underfill and missing sections with estimated measurements identified", () => {
  expect(
    qualityWarnings({
      fill_ratio: 0.81,
      fill_target: 0.93,
      estimated: true,
      verified: true,
      missing_sections: [
        { id: "projects", title: "Projects", reason: "template does not support it" },
      ],
    }),
  ).toEqual([
    "Estimated page fill is 81%; target is 93%.",
    "Page count is estimated (PDF measurement was unavailable), so the page fit isn't verified.",
    "Projects is missing: template does not support it.",
  ]);
});
it("flags an estimated page count even when fill meets the target", () => {
  const base = { fill_ratio: 0.95, fill_target: 0.93, verified: true, missing_sections: [] };
  expect(qualityWarnings({ ...base, estimated: false })).toEqual([]);
  expect(qualityWarnings({ ...base, estimated: true })).toEqual([
    "Page count is estimated (PDF measurement was unavailable), so the page fit isn't verified.",
  ]);
});
it("allows the review dialog only when acknowledgement is the only blocker", () => {
  expect(
    canFillAfterReview({
      preparation_eligible: false,
      preparation_reasons: ["resume_quality_ack_required"],
    }),
  ).toBe(true);
  expect(
    canFillAfterReview({
      preparation_eligible: false,
      preparation_reasons: ["resume_quality_ack_required", "missing_resume"],
    }),
  ).toBe(false);
  expect(
    canFillAfterReview({
      preparation_eligible: false,
      preparation_reasons: ["resume_quality_unverified"],
    }),
  ).toBe(false);
});
