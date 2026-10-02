import { describe, expect, it } from "vitest";
import { unansweredQuestions } from "./askQuestions";

const review = (field_id: string, control_kind: string) =>
  ({ field_id, control_kind, label: "", current_value: "", required: false }) as never;

describe("unansweredQuestions", () => {
  it("keeps open text questions and drops answered, choice and duplicate fields", () => {
    const fill = {
      field_outcomes: [
        { field_id: "a", label: "Why do you want to work here?", state: "unanswered" as const },
        { field_id: "b", label: "Gender", state: "unanswered" as const },
        { field_id: "c", label: "Describe a project", state: "verified_filled" as const },
        { field_id: "d", label: "Why do you want to work here?", state: "manual_review" as const },
        { label: "What motivates you?", state: "unanswered" as const },
        { label: "City", state: "unanswered" as const },
      ],
      review_fields: [review("a", "textarea"), review("b", "select")],
    };
    expect(unansweredQuestions(fill)).toEqual([
      "Why do you want to work here?",
      "What motivates you?",
    ]);
  });

  it("handles a missing fill", () => {
    expect(unansweredQuestions(null)).toEqual([]);
  });
});
