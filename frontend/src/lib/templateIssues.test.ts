import { describe, expect, it } from "vitest";
import codes from "./templateIssueCodes.json";
import { TEMPLATE_ISSUES, issueHelp } from "./templateIssues";

describe("template issue explanations", () => {
  it("explain every analyzer code", () => {
    const missing = codes.filter((code) => !(code in TEMPLATE_ISSUES));
    expect(missing).toEqual([]);
  });

  it("give every blocking layout problem a way forward", () => {
    for (const [code, help] of Object.entries(TEMPLATE_ISSUES)) {
      expect(help.title, code).toBeTruthy();
      expect(help.why, code).toBeTruthy();
    }
    expect(TEMPLATE_ISSUES.textboxes.word).toBeTruthy();
  });

  it("falls back for an unknown code", () => {
    expect(issueHelp("brand_new_code").title).toBe("Template issue");
  });
});
