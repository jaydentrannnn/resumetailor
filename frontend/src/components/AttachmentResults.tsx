import type { ApplyAttachment } from "../api";

export function AttachmentResults({ uploads }: { uploads: ApplyAttachment[] }) {
  if (uploads.length === 0) return null;
  return <section className="mt-3">
    <h4 className="mb-1 text-xs font-semibold text-ink">Documents</h4>
    <ul className="space-y-1 text-xs text-ink-muted">{uploads.map((upload, index) => {
      const state = upload.state?.replaceAll("_", " ") || (upload.verified ? "verified" : "unverified");
      const filename = upload.observed_filename || upload.expected_filename || upload.filename;
      return <li key={`${upload.purpose}-${index}`}>
        {upload.purpose || "Document"}: {filename ? `${filename} — ` : ""}{state}
        {(upload.reason || upload.error) && <span> · {upload.reason || upload.error}</span>}
      </li>;
    })}</ul>
  </section>;
}
