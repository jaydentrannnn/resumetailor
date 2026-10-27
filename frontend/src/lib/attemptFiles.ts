/** One file of a "What was sent" copy, served read-only (`?download=1` saves it). */
export function attemptFileUrl(sourceJobId: string, attempt: number, name: string): string {
  const path = name.split("/").map(encodeURIComponent).join("/");
  return `/api/applications/${encodeURIComponent(sourceJobId)}/attempts/${attempt}/files/${path}`;
}

/** A copied file's name as shown: an attached file says what it was for
 * (`attached/<purpose>/<file>`; two attachments can share a file name). */
export function attemptFileLabel(name: string): string {
  const parts = name.split("/");
  const file = parts.pop() ?? name;
  return parts.length === 2 && parts[0] === "attached"
    ? `${file} (${parts[1].replace(/_/g, " ")})`
    : file;
}
