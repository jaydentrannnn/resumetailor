import { describe, expect, it } from "vitest";
import { connectionProbe, keyTestProblem } from "./connectTest";

describe("connect key test", () => {
  it("probes the chosen engine with an unsaved keyword search", () => {
    expect(connectionProbe("adzuna")).toMatchObject({ kind: "job_search", provider: "adzuna" });
  });

  it("reports the first error and nothing when the search ran", () => {
    const ran = { rows_total: 0, rows_kept: 0, sample: [], errors: [] };
    expect(keyTestProblem("adzuna", ran)).toBeNull();
    const failed = { ...ran, errors: ["api.adzuna.com answered HTTP 401", "second"] };
    expect(keyTestProblem("adzuna", failed)).toContain("answered HTTP 401. Check the keys");
  });
});
