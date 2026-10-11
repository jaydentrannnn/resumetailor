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
  /** The editor had the file open this session and has closed it since. */
  editor_closed?: boolean;
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

/** A read-back file (Word edit or quick adjustments), as the upload the wizard installs. */
export async function fetchEditedLayout(sha: string): Promise<File> {
  const res = await fetch(`/api/template/drafts/${encodeURIComponent(sha)}`);
  if (!res.ok) throw await apiError(res);
  return new File([await res.blob()], "layout.docx", {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
}

export async function endEditSession(): Promise<void> {
  const res = await fetch(BASE, { method: "DELETE" });
  if (!res.ok) throw await apiError(res);
}

// -- Quick adjustments (`document/template_adjust.py`) ----------------------------------

export type Margins = { top: number; bottom: number; left: number; right: number };
export type FieldEmphasis = { label: string; bold: boolean; italic: boolean; underline: boolean };
/** Separator rows (`document/adjust_separators.py` ROWS). */
export type SeparatorRow =
  | "contact"
  | "project_tech"
  | "tech_items"
  | "project_link"
  | "skills_items"
  | "coursework"
  | "dates";
/** A marker glyph, or "keep" / "none_indent" / "none_flush" (`template_style.Bullets`). */
export type BulletStyle = { list: string; skills: string };
export type LinkLook = { color: "blue" | "text"; underline: boolean };
export type CurrentLayout = {
  margins: Margins;
  font_family: string;
  /** Other fonts the text uses (a name or headings font); a font change leaves them. */
  other_fonts: string[];
  font_size: number;
  fields: FieldEmphasis[];
  /** Only the rows this template prints, with their current values. */
  separators: Partial<Record<SeparatorRow, string>>;
  bullets: BulletStyle;
  /** null when the template prints no links. */
  links: LinkLook | null;
};
export type TemplateAdjustmentsResponse = { current: CurrentLayout; table_layout: boolean };
export type TemplateAdjustments = {
  margins?: Margins;
  font_family?: string;
  font_size?: number;
  fields?: Partial<FieldEmphasis>[];
  separators?: Partial<Record<SeparatorRow, string>>;
  bullets?: BulletStyle;
  links?: LinkLook;
};
export type TemplateFonts = { families: string[]; common: string[] };
export type AdjustPreview = { key: string; pages: number };

/** Font families installed where PDFs are made. */
export function fetchTemplateFonts(): Promise<TemplateFonts> {
  return request<TemplateFonts>("/api/template/fonts");
}

/** Render the resume through the adjusted template (nothing installed). A 409 means a
 * newer preview request superseded this one. */
export function fetchAdjustPreview(
  adj: TemplateAdjustments,
  signal?: AbortSignal,
): Promise<AdjustPreview> {
  return request<AdjustPreview>("/api/template/adjustments/preview", {
    method: "POST",
    body: JSON.stringify(adj),
    signal,
  });
}

export function adjustPreviewPageUrl(key: string, page: number): string {
  return `/api/template/adjustments/preview/${key}/${page}.png`;
}

export function fetchTemplateAdjustments(): Promise<TemplateAdjustmentsResponse> {
  return request<TemplateAdjustmentsResponse>("/api/template/adjustments");
}

/** Apply adjustments to the layout file and read it back; nothing is installed. */
export function adjustTemplate(adj: TemplateAdjustments): Promise<TemplateAnalyzeResponse> {
  return request<TemplateAnalyzeResponse>("/api/template/adjustments", {
    method: "POST",
    body: JSON.stringify(adj),
  });
}
