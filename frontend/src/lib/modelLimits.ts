import type { ModelQueueStatus } from "../api";
import type { ModelPlan, ModelRole } from "./aiModels";

/** Plan choices for a task model; "" lets the app guess from the provider. */
export const PLAN_OPTIONS: { value: ModelPlan | ""; label: string }[] = [
  { value: "", label: "Automatic" },
  { value: "free", label: "Free tier" },
  { value: "paid", label: "Pay as you go" },
  { value: "subscription", label: "API subscription" },
  { value: "local", label: "On this computer" },
];

/** The app's retry pause for a role's server, or null; this is not a credit balance. */
export function limitLabel(
  status: ModelQueueStatus | null,
  role: ModelRole,
  now = new Date(),
): string | null {
  const key = status?.roles?.[role];
  const endpoint = key ? status?.endpoints.find((e) => e.endpoint === key) : undefined;
  if (!endpoint) return null;
  const at = (seconds: number) =>
    new Date(now.getTime() + seconds * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  if ((endpoint.exhausted_seconds ?? 0) > 0)
    return endpoint.exhausted_seconds! > 3600
      ? "Requests paused for now"
      : `Requests paused, retry at ${at(endpoint.exhausted_seconds!)}`;
  if (endpoint.cooldown_seconds > 0) return `At limit, resumes ${at(endpoint.cooldown_seconds)}`;
  return null;
}
