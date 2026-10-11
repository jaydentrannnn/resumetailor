/** Edit layout in Word (desktop only): the session behind the Template page's card. */

import { apiError, request } from "./core";
import type { TemplateAnalyzeResponse } from "./templates";

export type TemplateEditStatus = {
  active: boolean;
  /** Saved since the app wrote the file. */
  changed: boolean;
  saved_at: string | null;
  /** Word or LibreOffice still has the file open. */
  editor_open: boolean;
  started_at: string | null;
  path: string | null;
};

const BASE = "/api/template/edit-session";

export function fetchEditSession(): Promise<TemplateEditStatus> {
  return request<TemplateEditStatus>(BASE);
}

export function startEditSession(): Promise<TemplateEditStatus> {
  return request<TemplateEditStatus>(BASE, { method: "POST" });
}

export function reopenEditSession(): Promise<TemplateEditStatus> {
  return request<TemplateEditStatus>(`${BASE}/open`, { method: "POST" });
}

/** Read the saved layout file back as an analysis; nothing is applied. */
export function importEditSession(): Promise<TemplateAnalyzeResponse> {
  return request<TemplateAnalyzeResponse>(`${BASE}/import`, { method: "POST" });
}

/** The read-back file, as the upload the template wizard installs. */
export async function fetchEditedLayout(sha: string): Promise<File> {
  const res = await fetch(`${BASE}/file/${encodeURIComponent(sha)}`);
  if (!res.ok) throw await apiError(res);
  return new File([await res.blob()], "layout.docx", {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
}

export async function endEditSession(): Promise<void> {
  const res = await fetch(BASE, { method: "DELETE" });
  if (!res.ok) throw await apiError(res);
}
