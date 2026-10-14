import { describe, expect, it } from "vitest";
import { DEFAULT_SETTINGS } from "../state/runDefaults";
import {
  customCredentialName,
  modelsFor,
  selectionReady,
  withSelection,
  withProvider,
  type ModelProvider,
} from "./aiModels";
import { endpointKey, queueEndpoints, selectionEndpoint } from "./modelEndpoints";

describe("shared model settings", () => {
  it("restores each provider's full draft per role, including after reload", () => {
    const providers: ModelProvider[] = [
      "anthropic",
      "gemini",
      "openai",
      "vertex_ai",
      "custom",
      "ollama",
      "ollama-cloud",
      "lmstudio",
    ];
    let settings = { ...DEFAULT_SETTINGS };
    for (const role of ["light", "heavy"] as const) {
      for (const provider of providers) {
        settings = withProvider(settings, role, provider);
        settings = withSelection(settings, role, {
          provider,
          model_name: `${role}-${provider}`,
          api_format: "anthropic",
          base_url: "https://proxy.example/api",
          plan: "subscription",
          vertex_project: `${role}-project`,
          vertex_location: "global",
        });
      }
    }
    settings = JSON.parse(JSON.stringify(settings));
    for (const role of ["light", "heavy"] as const) {
      for (const provider of providers) {
        settings = withProvider(settings, role, provider);
        expect(modelsFor(settings)[role]).toEqual({
          provider,
          model_name: `${role}-${provider}`,
          api_format: "anthropic",
          base_url: "https://proxy.example/api",
          plan: "subscription",
          vertex_project: `${role}-project`,
          vertex_location: "global",
        });
      }
    }
  });
  it("requires a Vertex model, project and location and derives its endpoint", () => {
    const pick = {
      provider: "vertex_ai" as const,
      model_name: "vertex_ai/claude-sonnet-5-5",
      api_format: "openai" as const,
      base_url: "",
      vertex_project: "test-project",
      vertex_location: "global",
    };
    expect(selectionReady(pick)).toBe(true);
    expect(selectionReady({ ...pick, vertex_project: "" })).toBe(false);
    expect(selectionReady({ ...pick, vertex_location: "" })).toBe(false);
    expect(selectionReady({ ...pick, model_name: "" })).toBe(false);
    expect(selectionReady({ ...pick, vertex_location: "evil.example" })).toBe(false);
    expect(selectionEndpoint(pick, null)).toBe(
      "https://aiplatform.googleapis.com/v1/projects/test-project/locations/global",
    );
    expect(selectionEndpoint({ ...pick, vertex_location: "us-east5" }, null)).toContain(
      "us-east5-aiplatform.googleapis.com",
    );
    for (const region of ["us", "eu"]) {
      const selection = { ...pick, vertex_location: region };
      expect(selectionReady(selection)).toBe(true);
      expect(selectionEndpoint(selection, null)).toBe(
        `https://aiplatform.${region}.rep.googleapis.com/v1/projects/test-project/locations/${region}`,
      );
    }
  });
  it("keeps role selections independent and clears migrated overrides only after a light edit", () => {
    const initial = {
      ...DEFAULT_SETTINGS,
      ai_models: {
        ...modelsFor(DEFAULT_SETTINGS),
        legacy_light_overrides: { skills: "ollama:selector" },
      },
    };
    const heavy = {
      provider: "custom" as const,
      model_name: "filler",
      api_format: "anthropic" as const,
      base_url: "http://localhost:8888",
    };
    const next = withSelection(initial, "heavy", heavy);
    expect(next.ai_models!.light).toEqual(initial.ai_models.light);
    expect(next.ai_models!.legacy_light_overrides).toEqual(
      initial.ai_models.legacy_light_overrides,
    );
    expect(next.apply.model_selection).toEqual(heavy);
    expect(
      withSelection(next, "light", next.ai_models!.light).ai_models!.legacy_light_overrides,
    ).toEqual({});
  });

  it("does not treat partial custom connection drafts as ready", () => {
    const selection = {
      provider: "custom" as const,
      model_name: "",
      api_format: "openai" as const,
      base_url: "http://localhost:8888/v1",
    };
    expect(selectionReady(selection)).toBe(false);
    expect(selectionReady({ ...selection, model_name: "m" })).toBe(true);
    expect(
      selectionReady({
        ...selection,
        model_name: "m",
        base_url: "https://user:password@server/v1",
      }),
    ).toBe(false);
  });

  it("binds credentials to role, API format and endpoint, matching the server hash", async () => {
    const selection = {
      provider: "custom" as const,
      model_name: "m",
      api_format: "openai" as const,
      base_url: "http://localhost:9876/v1/",
    };
    const light = await customCredentialName("light", selection);
    expect(light).toMatch(/^CUSTOM_LIGHT_[a-f0-9]{24}$/);
    expect(
      await customCredentialName("light", {
        ...selection,
        base_url: selection.base_url.slice(0, -1),
      }),
    ).toBe(light);
    expect(await customCredentialName("heavy", selection)).not.toBe(light);
    expect(await customCredentialName("light", { ...selection, api_format: "anthropic" })).not.toBe(
      light,
    );
  });
});

describe("per-server concurrency", () => {
  it("normalizes local aliases and keeps configured servers before any model request", () => {
    expect(endpointKey("http://127.0.0.1:1234/v1/")).toBe("http://localhost:1234/v1");
    const status = {
      settings: { local_concurrency: 1, cloud_concurrency: 4, endpoint_limits: {} },
      endpoints: [],
    };
    const endpoints = queueEndpoints(DEFAULT_SETTINGS, null, status);
    expect(endpoints).toHaveLength(1);
    expect(endpoints[0].label).toContain("light");
    expect(endpoints[0].label).toContain("heavy");
    expect(endpoints[0].inherited).toBe(1);
  });

  it("retains unused overrides and friendly provider labels without queue activity", () => {
    const url = "https://generativelanguage.googleapis.com/v1beta/openai";
    const endpoints = queueEndpoints(DEFAULT_SETTINGS, null, {
      settings: { local_concurrency: 1, cloud_concurrency: 4, endpoint_limits: { [url]: 2 } },
      endpoints: [],
    });
    const gemini = endpoints.find((e) => e.endpoint === url)!;
    expect(gemini.label).toBe("Google Gemini");
    expect(gemini.inherited).toBe(4);
    expect(gemini.live).toBeUndefined();
  });
});
