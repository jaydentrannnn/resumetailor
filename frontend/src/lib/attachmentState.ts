import type { ApplyAttachment } from "../api";

/** How a document came to be on the form, as the review panel says it. A file the fill
 * found already attached is never called verified: it may be the applicant's own. */
export function attachmentStateLabel(upload: ApplyAttachment): string {
  const kept =
    upload.state === "preserved" || (!upload.state && upload.verified && upload.preserved);
  if (upload.state === "kept_existing" || (kept && !upload.uploaded_by_app))
    return "kept the file already attached";
  if (kept) return "uploaded by an earlier fill";
  if (upload.state === "verified" || (!upload.state && upload.verified))
    return "uploaded and verified";
  return upload.state?.replaceAll("_", " ") || "unverified";
}
