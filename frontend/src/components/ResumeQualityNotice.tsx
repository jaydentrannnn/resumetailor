import { qualityWarnings, type ResumeQuality } from "../lib/resumeQuality";
import { StatusMark } from "./ui";

export function ResumeQualityNotice({ quality }: { quality?: ResumeQuality | null }) {
  const warnings = qualityWarnings(quality);
  if (!warnings.length) return null;
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
      <p className="mt-2">
        Review the preview, choose a template that supports these sections, or adjust your selected
        content and tailor again.
      </p>
    </div>
  );
}
