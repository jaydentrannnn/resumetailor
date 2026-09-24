import { describe, expect, it } from "vitest";
import { observedFieldValue } from "./FieldCorrectionRow";
import type { ApplyReviewField } from "../api";

describe("observedFieldValue", () => {
  it("does not present typed combobox search text as a selected answer", () => {
    const field = {
      field_id: "degree",
      frame_id: "0",
      label: "Degree",
      control_kind: "combobox",
      current_value: "bachelor",
      selection_state: "unselected",
      options: [],
    } as ApplyReviewField;
    expect(observedFieldValue(field)).toContain("no option selected");
  });
});
