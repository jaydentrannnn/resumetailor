/** Cover-letter layout settings (Template page › Cover letter) and their preview image. */

import { apiError, request } from "./core";

export type CoverBlockName = "date" | "recipient" | "subject" | "salutation" | "closing" | "signature";

export type CoverLetterSettings = {
  /** `same_as_resume`: the resume header's fields and lines; `custom`: `letterhead_fields`. */
  letterhead: "same_as_resume" | "custom";
  /** Contact field names and `custom:<key>` entries. */
  letterhead_fields: string[];
  blocks: Record<CoverBlockName, boolean>;
  /** `{job_title}` and `{company}` are filled from the posting. */
  subject_format: string;
  closing_text: string;
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
