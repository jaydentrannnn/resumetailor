/** One file of a "What was sent" copy, served read-only (`?download=1` saves it). */
export function attemptFileUrl(sourceJobId: string, attempt: number, name: string): string {
  const path = name.split("/").map(encodeURIComponent).join("/");
  return `/api/applications/${encodeURIComponent(sourceJobId)}/attempts/${attempt}/files/${path}`;
}
