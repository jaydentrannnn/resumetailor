import { downloadFilename, type JobFileKind } from "../lib/fileActions";
import { apiError, request } from "./core";

/** Save as… in the desktop app: false `saved` when the person cancelled the dialog. */
export type DesktopSaveResult = { saved: boolean; path: string | null };

/**
 * Save a downloadable file where the person chooses (desktop app only).
 *
 * Fetches the same bytes the download link serves, then hands them to the server,
 * which opens the native Save dialog and writes them; the page never picks a path.
 */
export async function saveFileAs(url: string, fallbackName: string): Promise<DesktopSaveResult> {
  const res = await fetch(url);
  if (!res.ok) throw await apiError(res);
  const name = downloadFilename(res.headers.get("Content-Disposition"), fallbackName);
  const body = await res.blob();
  return request<DesktopSaveResult>(`/api/desktop/save-as?name=${encodeURIComponent(name)}`, {
    method: "POST",
    body,
    headers: { "Content-Type": "application/octet-stream" },
  });
}

/**
 * Save this profile's export where the person chooses (desktop app only). The server
 * builds the zip and writes it there itself, so a large export never passes through
 * the page.
 */
export function saveDataExport(includeOutput: boolean): Promise<DesktopSaveResult> {
  return request<DesktopSaveResult>(`/api/data/export/save?include_output=${includeOutput}`, {
    method: "POST",
  });
}

/** Show a run's file selected in Explorer / Finder (desktop app only). */
export function revealJobFile(jobId: string, kind: JobFileKind): Promise<void> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/files/${kind}/reveal`, {
    method: "POST",
  });
}

/** Open a run's file in its program — a .docx in Word (desktop app only). */
export function openJobFile(jobId: string, kind: JobFileKind): Promise<void> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/files/${kind}/open`, { method: "POST" });
}

/** Set the desktop window's title (the page title does not reach it). */
export function setWindowTitle(title: string): Promise<void> {
  return request("/api/desktop/title", { method: "POST", body: JSON.stringify({ title }) });
}
