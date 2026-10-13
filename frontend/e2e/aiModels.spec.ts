import { expect, test } from "@playwright/test";
import { DEFAULT_SETTINGS } from "../src/state/runDefaults";
import { modelsFor } from "../src/lib/aiModels";
import type { JobSettings } from "../src/api";

test.use({ actionTimeout: 15_000 });

for (const width of [1280, 390]) {
  test(`AI model settings keep roles independent and custom limits tidy at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    let saved: JobSettings = {
      ...structuredClone(DEFAULT_SETTINGS),
      ai_models: modelsFor(DEFAULT_SETTINGS),
    };
    let queue = {
      settings: { local_concurrency: 1, cloud_concurrency: 4, endpoint_limits: {} },
      endpoints: [],
    };
    const checks: string[] = [];
    const keyStates = new Map<string, boolean>();
    await page.route("**/api/settings", async (route) => {
      if (route.request().method() === "PUT") saved = route.request().postDataJSON().settings;
      await route.fulfill({ json: { workspace_id: "default", seeded: false, settings: saved } });
    });
    await page.route("**/api/models/test", async (route) => {
      checks.push(route.request().postDataJSON().target);
      await route.fulfill({ json: { ok: true, model: "test", detail: "Answered." } });
    });
    await page.route("**/api/models/local?*", (route) =>
      route.fulfill({ json: { reachable: true, models: ["writer", "filler"] } }),
    );
    await page.route("**/api/model-queue", async (route) => {
      if (route.request().method() === "PUT")
        queue = { ...queue, settings: route.request().postDataJSON() };
      await route.fulfill({ json: queue });
    });
    await page.route("**/api/secrets", (route) =>
      route.fulfill({ json: { backend: "memory", secrets: [] } }),
    );
    await page.route("**/api/secrets/*", async (route) => {
      const name = route.request().url().split("/").pop()!;
      if (route.request().method() === "PUT") keyStates.set(name, true);
      await route.fulfill({
        json: {
          name,
          set: keyStates.get(name) ?? false,
          source: keyStates.get(name) ? "saved" : null,
        },
      });
    });
    await page.goto("/settings?tab=ai");
    await expect(page.getByRole("tab", { name: "AI model", exact: true })).toBeVisible();
    // Connections live with their model; credentials live in API keys.
    const tile = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "AI models", exact: true }) })
      .last();
    const light = tile.getByRole("group", { name: "Light task model", exact: true });
    const heavy = tile.getByRole("group", { name: "Heavy task model", exact: true });
    const keys = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "API keys", exact: true }) })
      .last();
    await heavy.getByRole("combobox", { name: "Provider", exact: true }).selectOption("custom");
    await heavy.getByLabel("Model", { exact: true }).fill("filler");
    await expect(heavy.getByLabel("Server URL")).toBeVisible();
    await expect(keys.getByLabel("Server URL")).toHaveCount(0);
    await heavy
      .getByRole("combobox", { name: "API format", exact: true })
      .selectOption("anthropic");
    await heavy.getByLabel("Server URL", { exact: true }).fill("https://proxy.example/api");
    const server = keys.getByRole("group", { name: "Custom server (Heavy)", exact: true });
    await expect(server.getByLabel("Server API key (optional)")).toBeVisible();
    await expect.poll(() => saved.ai_models?.heavy.base_url).toBe("https://proxy.example/api");
    expect(saved.ai_models?.light.provider).toBe("ollama");
    await expect.poll(() => checks.includes("heavy")).toBe(true);

    // A key belongs to this endpoint/format/role. A different endpoint gets an empty slot.
    await server.getByLabel("Server API key (optional)").fill("dummy-test-key");
    await server.getByRole("button", { name: "Save", exact: true }).click();
    await expect(server.getByText("Saved", { exact: true })).toBeVisible();
    await heavy.getByLabel("Server URL", { exact: true }).fill("https://other.example/api");
    await expect(server.getByText("Not set", { exact: true })).toBeVisible();

    await light.getByRole("combobox", { name: "Provider", exact: true }).selectOption("openai");
    await light.getByLabel("Model", { exact: true }).fill("reasoner");
    await expect(light.getByText("Needs a key", { exact: true })).toBeVisible();
    await expect(keys.getByLabel("OpenAI API key")).toBeVisible();
    await expect(keys.getByText("Manage other keys")).toHaveCount(0);
    await tile.screenshot({ path: `test-results/ai-models-${width}.png` });
    await keys.screenshot({ path: `test-results/ai-keys-${width}.png` });
    await expect.poll(() => saved.ai_models?.light.model_name).toBe("reasoner");
    expect(saved.ai_models?.heavy.model_name).toBe("filler");

    const advanced = tile;
    const toggle = tile.getByRole("switch", { name: "Advanced", exact: true });
    await expect(toggle).not.toBeChecked();
    await expect(advanced.getByLabel("Request concurrency", { exact: true })).toHaveCount(0);
    await toggle.press("Space");
    await expect(toggle).toBeChecked();
    await advanced
      .getByRole("combobox", { name: "Request concurrency", exact: true })
      .selectOption("custom");
    await expect(advanced.getByLabel("Local requests at once")).toBeVisible();
    await expect(advanced.getByLabel("Cloud requests at once")).toBeVisible();
    await expect(advanced.getByLabel("OpenAI (light) limit")).toBeHidden();
    await advanced.getByText("Per-server overrides", { exact: true }).click();
    await expect(advanced.getByLabel("OpenAI (light) limit")).toHaveValue("");
    await expect(advanced.getByText(/0 running/)).toHaveCount(0);
    await expect(advanced.getByLabel("Custom server (heavy) limit")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    );
    await advanced.screenshot({ path: `test-results/ai-advanced-${width}.png` });
    await toggle.press("Space");
    await expect(toggle).not.toBeChecked();
    await expect(advanced.getByLabel("Request concurrency", { exact: true })).toHaveCount(0);
  });
}
