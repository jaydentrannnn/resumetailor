import { describe, expect, it } from "vitest";
import type { TemplateUnmappedLine } from "../api";
import { choiceFor, keyFor, labelFor, withChoice } from "./unmappedLines";

const street: TemplateUnmappedLine = {
  paragraph_id: 1,
  text: "123 Example St.",
  suggestion: "field",
  suggested_key: "street_address",
  suggested_label: "Street address",
};
const tagline: TemplateUnmappedLine = {
  paragraph_id: 4,
  text: "Builder of things",
  suggestion: "field",
  suggested_key: "line_2",
  suggested_label: "Line 2",
};

describe("unmapped line choices", () => {
  it("reads a line with no slot and no drop as kept as-is", () => {
    expect(choiceFor({}, street)).toBe("static");
  });

  it("moves a line between field, removed and as-is", () => {
    const asField = withChoice({}, street, "field");
    expect(choiceFor(asField, street)).toBe("field");
    expect(asField.custom_fields).toEqual([
      { key: "street_address", label: "Street address", paragraph_id: 1, text: "123 Example St." },
    ]);
    const dropped = withChoice(asField, street, "drop");
    expect(choiceFor(dropped, street)).toBe("drop");
    expect(dropped.custom_fields).toEqual([]);
    expect(choiceFor(withChoice(dropped, street, "static"), street)).toBe("static");
  });

  it("renames a field and keeps keys unique", () => {
    let profile = withChoice({}, street, "field", "Home");
    profile = withChoice(profile, tagline, "field", "Home");
    expect(labelFor(profile, street)).toBe("Home");
    const keys = (profile.custom_fields as { key: string }[]).map((f) => f.key);
    expect(keys).toEqual(["home", "home_2"]);
  });

  it("slugs labels into valid keys", () => {
    expect(keyFor("Street address")).toBe("street_address");
    expect(keyFor("2nd line!")).toBe("line_2nd_line");
    expect(keyFor("  ")).toBe("line");
  });
});
