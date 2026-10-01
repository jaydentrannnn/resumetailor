/** The master resume: outline, read/write/import/merge, versions, tag suggestions. */

import { request, templateErrorDetail } from "./core";

export type ResumeOutlineEntry = {
  id: string;
  label: string;
  bullets: number;
};

/** One resume section (any kind, any count), as the include tile lists it. */
export type ResumeOutlineSection = {
  id: string;
  title: string;
  kind: string;
  entries: ResumeOutlineEntry[];
};

export type ResumeOutline = {
  /** Which of location/email/phone/linkedin/github are non-empty in the master resume. */
  available_contact_fields: string[];
  /** The active template profile's order, used when `include.contact_fields` is null. */
  default_contact_order: string[];
  has_gpa: boolean;
  /** Whether GPA is currently shown for any entry — seeds the tile from the resume's
   * existing behaviour rather than silently flipping it on the next run. */
  gpa_currently_shown: boolean;
  has_coursework: boolean;
  experience: ResumeOutlineEntry[];
  projects: ResumeOutlineEntry[];
  /** Every entry section (any kind, any count), in resume order — the general form of
   * `experience`/`projects` above, which group same-kind sections into one flat list. */
  sections: ResumeOutlineSection[];
  /** A template with no Projects section should not offer project checkboxes or the
   * link toggle. */
  sections_enabled: Record<string, boolean>;
  /** `"fixed"` templates bake section order into the tagged XML, so `section_order` has
   * no visible effect until the template is rebuilt in generic mode. */
  section_mode: string;
};

export type ValidateResponse = {
  ok: boolean;
  errors: string[];
  summary: Record<string, unknown> | null;
};

export function fetchResumeOutline(): Promise<ResumeOutline> {
  /** Load the master-resume shape the include tile needs — refetched on every mount
   * so an edit made on the Master resume tab shows up the next time Tailor is visited. */
  return request<ResumeOutline>("/api/resume-outline");
}

export function fetchMasterResume(): Promise<Record<string, unknown>> {
  /** Load the master resume for the editor. */
  return request("/api/master-resume");
}

export type MasterResumeImportResponse = {
  resume: Record<string, unknown>;
  warnings: string[];
  untagged_bullet_count: number;
};

/**
 * Parse an uploaded .docx or PDF into a `MasterResume` draft — content, not just layout.
 * Writes nothing; the caller loads the result as unsaved editor state and saves
 * through `saveMasterResume` when ready. `suggestTags` additionally runs an opt-in LLM
 * pass for whatever the deterministic import left untagged; `useModel` lets the model
 * sort a PDF's lines into sections (every field is checked against the PDF's text).
 */
export async function importMasterResumeContent(
  file: File,
  options?: { suggestTags?: boolean; useModel?: boolean },
): Promise<MasterResumeImportResponse> {
  const form = new FormData();
  form.append("file", file);
  if (options?.suggestTags) {
    form.append("suggest_tags", "true");
  }
  if (options?.useModel) {
    form.append("use_model", "true");
  }
  const res = await fetch("/api/master-resume/import", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  return res.json() as Promise<MasterResumeImportResponse>;
}

export function saveMasterResume(body: Record<string, unknown>): Promise<ValidateResponse> {
  /** Validate and persist the master resume (with a backup of the previous file). */
  return request("/api/master-resume", { method: "PUT", body: JSON.stringify(body) });
}

export type MasterResumeMergeResponse = {
  resume: Record<string, unknown>;
  updated: string[];
  added: string[];
  added_sections: string[];
  warnings: string[];
  backup: string | null;
};

/**
 * Fold an already-parsed draft (typically `MasterResumeImportResponse.resume`) into
 * the current master resume and save the result — matching entries updated in place,
 * new ones added, everything else left untouched. Unlike `saveMasterResume`, this
 * writes unconditionally (no separate confirm step server-side); the caller is
 * responsible for confirming with the user first.
 */
export function mergeMasterResume(
  resume: Record<string, unknown>,
): Promise<MasterResumeMergeResponse> {
  return request("/api/master-resume/merge", { method: "POST", body: JSON.stringify(resume) });
}

export function validateMasterResume(body: Record<string, unknown>): Promise<ValidateResponse> {
  /** Dry-run validation without writing. */
  return request("/api/master-resume/validate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface ResumeVersion {
  version: number;
  saved_at: string;
  note: string;
  name: string;
  bullets: number;
  sections: number;
  current: boolean;
}

export type TagSuggestion = { tag: string; matched: string };

export function suggestTags(
  text: string,
  tags: string[],
  vocabulary: string[],
): Promise<{ suggestions: TagSuggestion[] }> {
  /** Known skills (resume vocabulary + pack aliases) the text names but the tags lack. */
  return request("/api/master-resume/suggest-tags", {
    method: "POST",
    body: JSON.stringify({ text, tags, vocabulary }),
  });
}

export function listResumeVersions(): Promise<{ versions: ResumeVersion[]; keep: number }> {
  /** Saved master-resume versions, newest first. */
  return request("/api/master-resume/versions");
}

export function restoreResumeVersion(
  version: number,
): Promise<{ resume: Record<string, unknown>; restored: number }> {
  /** Write an earlier version back as the current master resume. */
  return request(`/api/master-resume/restore/${version}`, { method: "POST" });
}
