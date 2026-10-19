/**
 * Files the app hands to the person: plain downloads in the browser build, Save as… /
 * Show in folder / Open in the desktop app (`api/desktop.ts`, `components/FileActions`).
 */

/** A run's deliverables, as the desktop file routes name them. */
export type JobFileKind = "resume-pdf" | "resume-docx" | "cover-pdf" | "cover-docx";

/** The file name a download response suggests (`Content-Disposition`), else `fallback`. */
export function downloadFilename(contentDisposition: string | null, fallback: string): string {
  const header = contentDisposition ?? "";
  const encoded = /filename\*\s*=\s*(?:UTF-8'[^']*')?([^;]+)/i.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim().replace(/^"|"$/g, ""));
    } catch {
      // fall through to the plain parameter
    }
  }
  const plain = /filename\s*=\s*("([^"]*)"|[^;]+)/i.exec(header);
  const name = plain ? (plain[2] ?? plain[1]).trim() : "";
  return name || fallback;
}

/** Labels for a file action button, by host. */
export function saveLabel(what: string, desktop: boolean): string {
  return desktop ? `Save ${what}…` : `Download ${what}`;
}

/** "Open" for a PDF (the OS PDF reader), "Open in Word" for a .docx. */
export function openLabel(kind: JobFileKind): string {
  return kind.endsWith("docx") ? "Open in Word" : "Open";
}
