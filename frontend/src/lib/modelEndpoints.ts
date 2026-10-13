import type { AppConfig, JobSettings, ModelQueueStatus } from "../api";
import { modelsFor, selectionProvider, type ModelSelection } from "./aiModels";

export function endpointKey(value: string): string {
  const url = new URL(value);
  if (["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) url.hostname = "localhost";
  return `${url.origin}${url.pathname.replace(/\/+$/, "")}`;
}

export function selectionEndpoint(
  selection: ModelSelection,
  config: AppConfig | null,
): string | null {
  if (selection.provider === "vertex_ai") {
    const region = selection.vertex_location?.trim();
    const project = selection.vertex_project?.trim();
    if (!region || !project) return null;
    const host = ["us", "eu"].includes(region)
      ? `aiplatform.${region}.rep.googleapis.com`
      : region === "global"
        ? "aiplatform.googleapis.com"
        : `${region}-aiplatform.googleapis.com`;
    return `https://${host}/v1/projects/${project}/locations/${region}`;
  }
  const bases: Record<string, string> = {
    ollama: config?.ollama_base_url ?? "http://localhost:11434/v1",
    "ollama-cloud": "https://ollama.com/v1",
    lmstudio: "http://localhost:1234/v1",
    gemini: config?.gemini_base_url ?? "https://generativelanguage.googleapis.com/v1beta/openai",
    anthropic: "https://api.anthropic.com",
    openai: "https://api.openai.com/v1",
  };
  const base =
    selection.base_url ||
    config?.model_base_urls?.[selection.provider] ||
    bases[selection.provider];
  if (!base) return null;
  try {
    // Anthropic's scheduled transport groups requests by origin.
    const anthropic =
      selection.provider === "anthropic" ||
      (selection.provider === "custom" && selection.api_format === "anthropic");
    return endpointKey(anthropic ? new URL(base).origin : base);
  } catch {
    return null;
  }
}

export function queueEndpoints(
  settings: JobSettings,
  config: AppConfig | null,
  status: ModelQueueStatus,
) {
  const names = new Map<string, string[]>();
  const models = modelsFor(settings);
  for (const role of ["light", "heavy"] as const) {
    const endpoint = selectionEndpoint(models[role], config);
    if (!endpoint) continue;
    const label = `${selectionProvider(models[role])?.name ?? models[role].provider} (${role})`;
    names.set(endpoint, [...(names.get(endpoint) ?? []), label]);
  }
  const urls = new Set([
    ...names.keys(),
    ...Object.keys(status.settings.endpoint_limits),
    ...status.endpoints.map((e) => e.endpoint),
  ]);
  return [...urls].sort().map((endpoint) => {
    const live = status.endpoints.find((e) => e.endpoint === endpoint);
    const hostname = new URL(endpoint).hostname;
    const known = hostname.includes("generativelanguage.googleapis.com")
      ? "Google Gemini"
      : hostname === "ollama.com"
        ? "Ollama Cloud"
        : hostname === "api.openai.com"
          ? "OpenAI"
          : hostname === "api.anthropic.com"
            ? "Anthropic"
            : hostname;
    const local =
      live?.local ??
      (hostname === "host.docker.internal" ||
        hostname.endsWith(".local") ||
        /^(localhost|127\.|\[::1\]|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(hostname));
    const inherited = local ? status.settings.local_concurrency : status.settings.cloud_concurrency;
    return { endpoint, label: names.get(endpoint)?.join(" / ") ?? known, inherited, live };
  });
}
