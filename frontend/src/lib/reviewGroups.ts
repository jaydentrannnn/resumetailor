import type { ApplyFieldOutcome, ApplyReviewField } from "../api";

export type ReviewGroup = "attention" | "optional" | "generated" | "verified" | "unknown";
export function reviewGroup(field?: ApplyReviewField, outcome?: ApplyFieldOutcome): ReviewGroup {
  const state = outcome?.state;
  if (state === "manual_review" || state === "ambiguous" || state === "invalid_existing" || state === "failed") return "attention";
  if (state === "verified_filled" || state === "preserved") return outcome?.answer_source === "generated" ? "generated" : "verified";
  if (state === "unanswered") {
    const required = field?.required ?? outcome?.required;
    return required === true ? "attention" : required === false ? "optional" : "unknown";
  }
  const answer = outcome?.observed_value || outcome?.value || field?.current_value;
  if (answer?.trim()) return "unknown";
  return "unknown";
}
