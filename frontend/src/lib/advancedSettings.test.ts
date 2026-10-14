import { describe, expect, it } from "vitest";
import { DEFAULT_SETTINGS } from "../state/runDefaults";
import { withAdvanced, withEffortMode } from "./advancedSettings";

describe("saved AI tuning", () => {
  it("uses defaults while disabled and restores the saved draft after reload", () => {
    const custom = {
      ...DEFAULT_SETTINGS,
      ai_advanced_enabled: true,
      effort: "high" as const,
      extract_runs: 5,
      max_concurrent_jobs: 7,
    };
    const off = withAdvanced(custom, false);
    expect([off.effort, off.extract_runs, off.max_concurrent_jobs]).toEqual([null, 0, 2]);
    const restored = withAdvanced(JSON.parse(JSON.stringify(off)), true);
    expect([restored.effort, restored.extract_runs, restored.max_concurrent_jobs]).toEqual([
      "high",
      5,
      7,
    ]);
    expect(custom.effort).toBe("high");
  });

  it("remembers custom effort through Recommended and Advanced off", () => {
    const custom = {
      ...DEFAULT_SETTINGS,
      effort: { rewrite: "high" as const, answer: "medium" as const },
    };
    const recommended = withEffortMode(custom, false, "low");
    expect(recommended.effort).toBeNull();
    const reloaded = JSON.parse(
      JSON.stringify(withAdvanced(withAdvanced(recommended, false), true)),
    );
    expect(withEffortMode(reloaded, true, "low").effort).toEqual(custom.effort);
  });
});
