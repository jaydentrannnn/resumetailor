import { qualityWarnings, type ResumeQuality } from "../lib/resumeQuality";
import { StatusMark } from "./ui";

export function ResumeQualityNotice({ quality }: { quality?: ResumeQuality | null }) {
  const warnings = qualityWarnings(quality);
  const pdfIssues = quality?.pdf_text?.issues.length ?? 0;
  const advisories = quality?.pdf_text?.advisories ?? [];
  if (!warnings.length)
    return advisories.length ? (
      <p className="my-3 text-sm text-ink-muted">{advisories.join(" ")}</p>
    ) : null;
  return (
    <div role="alert" className="my-3 rounded-sm bg-attn-soft p-3 text-sm text-ink-2">
      <p className="flex items-center gap-2 font-medium text-attn">
        <StatusMark tone="attention" />
        Check this resume before applying
      </p>
      {warnings.map((message) => (
        <p key={message} className="mt-1">
          {message}
        </p>
      ))}
      {warnings.length > pdfIssues && (
        <p className="mt-2">
          Review the preview, choose a template that supports these sections, or adjust your
          selected content and tailor again.
        </p>
      )}
      {pdfIssues > 0 && (
        <p className="mt-2">
          Open the PDF and copy its text to see what an application site reads. If this template
          loses text in its PDF, try another template, or upload the .docx where a form accepts it.
        </p>
      )}
      {advisories.map((message) => (
        <p key={message} className="mt-1 text-ink-muted">
          {message}
        </p>
      ))}
    </div>
  );
}
