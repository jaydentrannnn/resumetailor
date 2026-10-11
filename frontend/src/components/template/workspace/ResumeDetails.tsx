import type { TemplateInfo } from "../../../api";
import { formatBytes, formatWhen } from "../../../lib/formatFile";
import { DataList } from "../../ui";

/** The Resume view's collapsed footnotes: file details and the profile's warnings. */
export function ResumeDetails({ info }: { info: TemplateInfo }) {
  const warnings = info.profile?.warnings ?? [];
  return (
    <>
      <details className="border-t border-line pt-4">
        <summary className="cursor-pointer text-sm font-medium">Technical details</summary>
        <DataList
          className="mt-4"
          mono
          items={[
            { label: "Active label", value: info.active_label || "—" },
            {
              label: "Tagged template",
              value: info.tagged.exists
                ? `${formatBytes(info.tagged.size_bytes)} · ${formatWhen(info.tagged.modified_at)}`
                : "Missing — upload a baseline below",
            },
            {
              label: "Baseline export",
              value: info.baseline.exists
                ? `${formatBytes(info.baseline.size_bytes)} · ${formatWhen(info.baseline.modified_at)}`
                : "Missing",
            },
            {
              label: "Profile",
              value: info.profile?.exists
                ? `v${info.profile.schema_version ?? "?"} · ${
                    Object.entries(info.profile.enabled ?? {})
                      .filter(([, on]) => on)
                      .map(([k]) => k)
                      .join(", ") || "experience"
                  }`
                : "Legacy (no profile file)",
            },
          ]}
        />
      </details>
      {warnings.length > 0 && (
        <details className="border-t border-line pt-4 text-sm text-attn">
          <summary className="cursor-pointer">Warnings ({warnings.length})</summary>
          {warnings.map((warning, index) => (
            <p key={index} className="mt-2">
              {warning}
            </p>
          ))}
        </details>
      )}
    </>
  );
}
