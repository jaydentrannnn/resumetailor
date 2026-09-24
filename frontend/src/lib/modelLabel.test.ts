import { describe, expect, it } from "vitest";
import type { AppConfig } from "../api";
import { profileDefaultModel, tailorModelLabel } from "./modelLabel";

const config = {
  ollama_profiles: ["ollama"],
  ollama_model: "gemma4:cloud",
  gemini_profiles: ["gemini"],
  gemini_model: "gemini-flash",
} as unknown as AppConfig;

describe("tailorModelLabel", () => {
  it("uses the profile's default model when no model name is set", () => {
    expect(tailorModelLabel({ model: "ollama", model_name: null }, config)).toBe(
      "ollama · gemma4:cloud",
    );
  });

  it("prefers an explicit model name override", () => {
    expect(tailorModelLabel({ model: "ollama", model_name: "qwen3:cloud" }, config)).toBe(
      "ollama · qwen3:cloud",
    );
  });

  it("falls back to the bare profile before config loads", () => {
    expect(tailorModelLabel({ model: "ollama", model_name: null }, null)).toBe("ollama");
  });
});

describe("profileDefaultModel", () => {
  it("maps gemini profiles to the gemini default", () => {
    expect(profileDefaultModel({ model: "gemini" }, config)).toBe("gemini-flash");
  });
});
