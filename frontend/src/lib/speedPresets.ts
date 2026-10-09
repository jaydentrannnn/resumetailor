import type { ModelQueueSettings } from "../api";

/** Named model-request limits; anything else (or a per-server limit) is "custom". */
export const SPEED_PRESETS = [
  {
    id: "gentle",
    label: "Fewer rate-limit errors",
    help: "One request at a time everywhere. Slowest, but kindest to free tiers.",
    local: 1,
    cloud: 1,
  },
  {
    id: "balanced",
    label: "Balanced (recommended)",
    help: "One request at a time to a model on this computer, three to cloud providers.",
    local: 1,
    cloud: 3,
  },
  {
    id: "fast",
    label: "Faster",
    help: "More requests at once. Paid plans handle it; free tiers may hit rate limits.",
    local: 2,
    cloud: 6,
  },
] as const;

export type SpeedPresetId = (typeof SPEED_PRESETS)[number]["id"] | "custom";

export function presetFor(settings: ModelQueueSettings): SpeedPresetId {
  if (Object.keys(settings.endpoint_limits).length) return "custom";
  const match = SPEED_PRESETS.find(
    (p) => p.local === settings.local_concurrency && p.cloud === settings.cloud_concurrency,
  );
  return match?.id ?? "custom";
}

export function settingsFor(id: Exclude<SpeedPresetId, "custom">): ModelQueueSettings {
  const preset = SPEED_PRESETS.find((p) => p.id === id)!;
  return { local_concurrency: preset.local, cloud_concurrency: preset.cloud, endpoint_limits: {} };
}
