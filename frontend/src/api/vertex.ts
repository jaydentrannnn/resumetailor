import { request } from "./core";

export type VertexConnection = {
  configured: boolean;
  connected: boolean;
  email: string | null;
  revision: string;
};
export type VertexModel = {
  id: string;
  name?: string;
  publisher?: string;
  reasoning: boolean;
  locations: string[];
};
export type VertexProject = { id: string; name: string };
export type VertexAuthStatus = {
  status: "pending" | "connected" | "cancelled" | "expired" | "failed";
  detail: string;
};

export const fetchVertexConnection = () => request<VertexConnection>("/api/vertex/connection");
export const disconnectVertex = () =>
  request<VertexConnection>("/api/vertex/connection", { method: "DELETE" });
export const startVertexAuth = () =>
  request<{ flow_id: string; authorization_url: string }>("/api/vertex/auth", { method: "POST" });
export const fetchVertexAuth = (id: string) =>
  request<VertexAuthStatus>(`/api/vertex/auth/${encodeURIComponent(id)}`);
export const cancelVertexAuth = (id: string) =>
  request<VertexAuthStatus>(`/api/vertex/auth/${encodeURIComponent(id)}`, { method: "DELETE" });
export const fetchVertexModels = () => request<{ models: VertexModel[] }>("/api/vertex/models");
export const fetchVertexProjects = (page = "") =>
  request<{ projects: VertexProject[]; next_page_token: string }>(
    `/api/vertex/projects?page_token=${encodeURIComponent(page)}`,
  );
