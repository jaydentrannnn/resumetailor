import { describe, expect, it } from "vitest";
import { customLineRows, withCustomValue, withoutCustomValue } from "./customLines";
import type { MasterResume } from "./resumeEdit";

const resume: MasterResume = { contact: { name: "A", email: "a@x.io" }, sections: [] };
const slots = [{ key: "street_address", label: "Street address", text: "123 Example St." }];

describe("custom line rows", () => {
  it("shows the template text until the resume has its own value", () => {
    expect(customLineRows(resume, slots)).toEqual([
      {
        key: "street_address",
        label: "Street address",
        value: "123 Example St.",
        templateText: "123 Example St.",
        edited: false,
      },
    ]);
  });

  it("uses the resume's value, including an empty one, and resets", () => {
    const cleared = withCustomValue(resume, "street_address", "Street address", "");
    expect(customLineRows(cleared, slots)[0]).toMatchObject({ value: "", edited: true });
    const edited = withCustomValue(cleared, "street_address", "Street address", "9 New Rd");
    expect(edited.custom_fields).toEqual([
      { key: "street_address", label: "Street address", value: "9 New Rd" },
    ]);
    expect(customLineRows(withoutCustomValue(edited, "street_address"), slots)[0].edited).toBe(
      false,
    );
  });
});
