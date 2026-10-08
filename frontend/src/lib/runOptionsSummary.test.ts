import { describe, expect, it } from "vitest";
import type { AppConfig } from "../api";
import { DEFAULT_SETTINGS } from "../state/runDefaults";
import { runOptionsSummary } from "./runOptionsSummary";

const config = {
  calibration_source: "word",
  ollama_profiles: ["ollama"],
  gemini_profiles: [],
  ollama_model: "gemma4:cloud",
  gemini_model: "gemini-flash",
} as unknown as AppConfig;

describe("runOptionsSummary", () => {
  it("summarises pages, cover letter, model and page fit", () => {
    const summary = runOptionsSummary(
      { ...DEFAULT_SETTINGS, model: "ollama", model_name: "", pages: 1, cover_letter: false },
      config,
    );
    expect(summary).toEqual({
      pages: "1 page",
      coverLetter: "Off",
      provider: "Ollama",
      modelName: "gemma4:cloud",
      pageFit: "Measured",
    });
  });

  it("names the cover letter tone and an estimated page fit", () => {
    const summary = runOptionsSummary(
      {
        ...DEFAULT_SETTINGS,
        pages: 2,
        cover_letter: true,
        no_cover_letter: false,
        cover_angles: { ...DEFAULT_SETTINGS.cover_angles, tone: "direct" },
        model_name: "my-model",
      },
      { ...config, calibration_source: "fallback" } as AppConfig,
    );
    expect(summary.pages).toBe("2 pages");
    expect(summary.coverLetter).toBe("On · Direct");
    expect(summary.modelName).toBe("my-model");
    expect(summary.pageFit).toBe("Estimated");
  });

  it("hides the placeholder model and page fit before the config loads", () => {
    const summary = runOptionsSummary({ ...DEFAULT_SETTINGS, model_name: "" }, null);
    expect(summary.modelName).toBeNull();
    expect(summary.pageFit).toBeNull();
    expect(
      runOptionsSummary({ ...DEFAULT_SETTINGS, cover_letter: true, no_cover_letter: true }, null)
        .coverLetter,
    ).toBe("Off");
  });
});
