/** Which kinds of resume file an upload box takes. */

export const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/** Word-processor formats the server converts to .docx with LibreOffice. */
export const CONVERTIBLE = [".doc", ".odt", ".rtf"];

export function isDocx(file: File): boolean {
  return file.name.toLowerCase().endsWith(".docx") || file.type === DOCX_MIME;
}

/** A PDF gives a resume's words only: it has no editable layout to keep. */
export function isPdf(file: File): boolean {
  return file.name.toLowerCase().endsWith(".pdf") || file.type === "application/pdf";
}

export function isConvertible(file: File): boolean {
  const name = file.name.toLowerCase();
  return CONVERTIBLE.some((suffix) => name.endsWith(suffix));
}
