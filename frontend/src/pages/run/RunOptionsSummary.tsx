import type { AppConfig, JobSettings } from "../../api";
import { DataList } from "../../components/ui";
import { runOptionsSummary } from "../../lib/runOptionsSummary";

/** The collapsed Options tile: pages, cover letter, model (tag in mono) and page fit. */
export function RunOptionsSummary({
  config,
  settings,
}: {
  config: AppConfig | null;
  settings: JobSettings;
}) {
  const summary = runOptionsSummary(settings, config);
  return (
    <DataList
      className="gap-x-12"
      items={[
        { label: "Pages", value: summary.pages },
        { label: "Cover letter", value: summary.coverLetter },
        {
          label: "Model",
          value: (
            <>
              {summary.provider}
              {summary.modelName && (
                <span className="ml-1.5 font-mono text-xs font-normal text-ink-muted">
                  {summary.modelName}
                </span>
              )}
            </>
          ),
        },
        ...(summary.pageFit ? [{ label: "Page fit", value: summary.pageFit }] : []),
      ]}
    />
  );
}
