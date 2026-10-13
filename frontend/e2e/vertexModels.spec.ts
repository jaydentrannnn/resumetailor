import { expect, test } from "@playwright/test";
import { DEFAULT_SETTINGS } from "../src/state/runDefaults";
import { modelsFor } from "../src/lib/aiModels";
import type { JobSettings } from "../src/api";

for (const width of [1280, 390]) {
  test(`Vertex model and location dropdowns preserve manual entries at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    let saved: JobSettings = {
      ...structuredClone(DEFAULT_SETTINGS),
      ai_models: modelsFor(DEFAULT_SETTINGS),
    };
    saved.ai_models!.light = {
      provider: "vertex_ai",
      model_name: "vertex_ai/claude-sonnet-5-5",
      api_format: "openai",
      base_url: "",
      plan: null,
      vertex_project: "test-project",
      vertex_location: "global",
    };
    await page.route("**/api/settings", async (route) => {
      if (route.request().method() === "PUT") saved = route.request().postDataJSON().settings;
      await route.fulfill({ json: { workspace_id: "default", seeded: false, settings: saved } });
    });
    await page.route("**/api/vertex/connection", (route) =>
      route.fulfill({
        json: {
          configured: false,
          connected: false,
          email: null,
          revision: "",
        },
      }),
    );
    await page.route("**/api/vertex/models", (route) =>
      route.fulfill({
        json: {
          models: [
            {
              id: "claude-sonnet-5-5",
              name: "Claude Sonnet 5.5",
              publisher: "Anthropic",
              reasoning: true,
              locations: ["global", "us", "eu"],
            },
            {
              id: "zai-org/glm-5.2-maas",
              name: "GLM 5.2 API Service",
              publisher: "Zai-org",
              reasoning: false,
              locations: ["global"],
            },
          ],
        },
      }),
    );
    await page.goto("/settings?tab=ai");
    const light = page.getByRole("group", { name: "Light task model", exact: true });
    const model = light.getByRole("combobox", { name: "Model", exact: true });
    const location = light.getByRole("combobox", { name: "Vertex location", exact: true });
    await expect(model).toHaveValue("claude-sonnet-5-5");
    await expect(location).toHaveValue("global");
    await location.selectOption("eu");
    await expect.poll(() => saved.ai_models?.light.vertex_location).toBe("eu");
    await model.selectOption({ label: "GLM 5.2 API Service" });
    await expect.poll(() => saved.ai_models?.light.model_name).toBe("zai-org/glm-5.2-maas");
    // A model change must not silently substitute a saved location.
    await expect(light.getByLabel("Custom location", { exact: true })).toHaveValue("eu");
    await location.selectOption("global");
    await light.screenshot({ path: `test-results/vertex-dropdowns-${width}.png` });
    await model.selectOption("__custom__");
    await light.getByLabel("Custom model ID", { exact: true }).fill("new-managed-model");
    await expect.poll(() => saved.ai_models?.light.model_name).toBe("new-managed-model");
    await page.reload();
    await expect(light.getByLabel("Custom model ID", { exact: true })).toHaveValue(
      "new-managed-model",
    );
    expect(saved.ai_models?.heavy.provider).toBe("ollama");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    );
  });
}
