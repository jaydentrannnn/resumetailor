/** Cover-letter layout settings (Template page › Cover letter) and their preview image. */

import { apiError, request } from "./core";

export type CoverBlockName =
  "date" | "recipient" | "subject" | "salutation" | "closing" | "signature";

export type CoverLetterSettings = {
  /** `same_as_resume`: the resume header's fields and lines; `custom`: `letterhead_fields`. */
  letterhead: "same_as_resume" | "custom";
  /** Contact field names and `custom:<key>` entries. */
  letterhead_fields: string[];
  blocks: Record<CoverBlockName, boolean>;
  /** `{job_title}` and `{company}` are filled from the posting. */
  subject_format: string;
  closing_text: string;
  /** `own`: the uploaded letter (its «fields» decide the letterhead). Default `generated`. */
  design?: "generated" | "own";
};

export type CoverLetterField = {
  id: string;
  label: string;
  /** False when the resume has nothing to print for it. */
  has_value: boolean;
};

export type CoverLetterSettingsResponse = {
  settings: CoverLetterSettings;
  fields: CoverLetterField[];
  /** An own letter is uploaded (whether or not it is in use). */
  own_letter?: boolean;
};

export function fetchCoverLetterSettings(): Promise<CoverLetterSettingsResponse> {
  return request<CoverLetterSettingsResponse>("/api/cover-letter/settings");
}

export function saveCoverLetterSettings(
  settings: CoverLetterSettings,
): Promise<CoverLetterSettingsResponse> {
  return request<CoverLetterSettingsResponse>("/api/cover-letter/settings", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}

/** A PNG of a sample letter under `settings` (saved or not), as a Blob. */
export async function fetchCoverLetterPreview(
  settings: CoverLetterSettings,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await fetch("/api/cover-letter/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
    signal,
  });
  if (!res.ok) throw await apiError(res);
  return res.blob();
}

/** Your current cover letter with «fields» in place of the words (a .docx download). */
export const COVER_STARTER_URL = "/api/cover-letter/starter";

export type OwnLetterUpload =
  { ok: true; response: CoverLetterSettingsResponse } | { ok: false; problems: string[] };

/** Upload your own letter. A letter that can't be used comes back as its problems. */
export async function uploadOwnLetter(file: File): Promise<OwnLetterUpload> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/cover-letter/own", { method: "POST", body: form });
  if (res.status === 422) {
    const body = await res.json().catch(() => ({}));
    const problems = body?.detail?.problems;
    if (Array.isArray(problems)) return { ok: false, problems };
  }
  if (!res.ok) throw await apiError(res);
  return { ok: true, response: (await res.json()) as CoverLetterSettingsResponse };
}

export function removeOwnLetter(): Promise<CoverLetterSettingsResponse> {
  return request<CoverLetterSettingsResponse>("/api/cover-letter/own", { method: "DELETE" });
}
