import { request } from "./core";

export interface ModelQueueSettings {
  local_concurrency: number;
  cloud_concurrency: number;
  endpoint_limits: Record<string, number>;
}
export interface ModelQueueStatus {
  settings: ModelQueueSettings;
  endpoints: {
    endpoint: string;
    local: boolean;
    limit: number;
    active: number;
    waiting: number;
    cooldown_seconds: number;
  }[];
}
export const fetchModelQueue = () => request<ModelQueueStatus>("/api/model-queue");
export const saveModelQueue = (settings: ModelQueueSettings) =>
  request<ModelQueueStatus>("/api/model-queue", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
