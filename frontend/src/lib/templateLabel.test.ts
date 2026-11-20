import { describe, expect, it } from "vitest";
import { labelFromFilename, uniqueLabel } from "./templateLabel";

describe("labelFromFilename", () => {
  it.each([
    ["Maya_Lin  Resume.docx", "Maya Lin Resume"],
    ["old resume.DOC", "old resume"],
    ["export.odt", "export"],
    [".docx", "Untitled"],
  ])("%s → %s", (name, expected) => {
    expect(labelFromFilename(name)).toBe(expected);
  });
});

describe("uniqueLabel", () => {
  it("keeps a name nothing else uses", () => {
    expect(uniqueLabel("Resume", ["Other"])).toBe("Resume");
  });

  it("numbers a name already saved, whatever its case", () => {
    expect(uniqueLabel("Resume", ["resume"])).toBe("Resume 2");
    expect(uniqueLabel("Resume", ["Resume", "RESUME 2"])).toBe("Resume 3");
  });

  it("stays within the label length", () => {
    const long = "x".repeat(80);
    const label = uniqueLabel(long, [long]);
    expect(label).toHaveLength(80);
    expect(label.endsWith(" 2")).toBe(true);
  });
});
