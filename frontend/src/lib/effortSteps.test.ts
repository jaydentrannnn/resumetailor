import { describe, expect, it } from "vitest";
import type { AppConfig } from "../api";
import type { ModelSelection } from "./aiModels";
import { customLevels, receivesEffort, recommendedEffort } from "./effortSteps";

const pick = (
  provider: ModelSelection["provider"],
  api_format: "openai" | "anthropic" = "openai",
) => ({ provider, model_name: "m", api_format, base_url: "" }) as ModelSelection;

const config = {
  recommended_effort: {
    expand: { anthropic: "low", openai: "low", gemini: "low", other: "medium" },
  },
} as unknown as AppConfig;

describe("effortSteps", () => {
  it("only offers Vertex effort for a model with known capability", () => {
    const selection = { ...pick("vertex_ai"), model_name: "vertex_ai/claude-sonnet-5-5" };
    expect(receivesEffort(selection)).toBe(false);
    expect(
      receivesEffort(selection, [{ id: "claude-sonnet-5-5", reasoning: true, locations: [] }]),
    ).toBe(true);
    expect(
      receivesEffort(selection, [{ id: "claude-sonnet-5-5", reasoning: false, locations: [] }]),
    ).toBe(false);
  });
  it("knows which providers receive effort", () => {
    expect(receivesEffort(pick("anthropic"))).toBe(true);
    expect(receivesEffort(pick("gemini"))).toBe(true);
    expect(receivesEffort(pick("ollama"))).toBe(false);
    expect(receivesEffort(pick("custom"))).toBe(false);
    expect(receivesEffort(pick("custom", "anthropic"))).toBe(true);
  });

  it("reads the recommended effort for the provider", () => {
    expect(recommendedEffort(config, "expand", pick("anthropic"))).toBe("low");
    expect(recommendedEffort(config, "expand", pick("ollama-cloud"))).toBe("medium");
    expect(recommendedEffort(null, "analysis", pick("anthropic"))).toBe("low");
  });

  it("expands a single level or a partial map to every step", () => {
    const fallback = () => "medium" as const;
    expect(Object.values(customLevels("high", fallback))).toEqual(Array(5).fill("high"));
    const levels = customLevels({ rewrite: "low" }, fallback);
    expect(levels.rewrite).toBe("low");
    expect(levels.cover).toBe("medium");
  });
});
