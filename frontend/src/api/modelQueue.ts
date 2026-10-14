import { request } from "./core";

export interface ModelQueueLimits {
  local_concurrency: number;
  cloud_concurrency: number;
  endpoint_limits: Record<string, number>;
}
export interface ModelQueueSettings extends ModelQueueLimits {
  custom_mode?: boolean;
  custom_settings?: ModelQueueLimits | null;
}
export interface ModelQueueStatus {
  settings: ModelQueueSettings;
  /** The server each saved task model sends its requests to. */
  roles?: Partial<Record<"light" | "heavy", string>>;
  endpoints: {
    endpoint: string;
    local: boolean;
    limit: number;
    /** Lower than `limit` for a while after the provider said "too many requests". */
    limit_effective?: number;
    active: number;
    waiting: number;
    cooldown_seconds: number;
    /** Seconds until a used-up quota should work again; 0 when it does. */
    exhausted_seconds?: number;
    rate_limited_today?: number;
    quota?: string;
  }[];
}
export const fetchModelQueue = () => request<ModelQueueStatus>("/api/model-queue");
export const saveModelQueue = (settings: ModelQueueSettings) =>
  request<ModelQueueStatus>("/api/model-queue", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
