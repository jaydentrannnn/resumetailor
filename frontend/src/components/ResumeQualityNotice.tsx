import { qualityWarnings, type ResumeQuality } from "../lib/resumeQuality";

export function ResumeQualityNotice({ quality }: { quality?: ResumeQuality | null }) {
  const warnings = qualityWarnings(quality);
  if (!warnings.length) return null;
  return (
    <div
      role="alert"
      className="my-3 rounded-md border border-warn bg-warn-soft p-3 text-sm text-warn"
    >
      <p className="font-medium">Check this resume before applying</p>
      {warnings.map((message) => (
        <p key={message} className="mt-1">
          {message}
        </p>
      ))}
      <p className="mt-2">
        Review the preview, choose a template that supports these sections, or adjust your selected
        content and tailor again.
      </p>
    </div>
  );
}
