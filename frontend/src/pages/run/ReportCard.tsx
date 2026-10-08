import { ResumeQualityNotice } from "../../components/ResumeQualityNotice";
import type { RunReport } from "../../api";
import { gapGroups, missingSummary, reportHeadline } from "../../lib/reportSummary";
import { ReportFigures } from "./ReportFigures";
import { ReportNotes } from "./ReportNotes";
import { ResultFrame } from "./ResultFrame";

/**
 * End-of-run summary: one headline, the run's figures (`ReportFigures`), then notes,
 * skill gaps and internals (`ReportNotes`). `embedded` drops the tile and the title for
 * the Tailor page's "Last result" tile, which already names the run.
 */
export function ReportCard({
  report,
  embedded = false,
}: {
  report: RunReport;
  embedded?: boolean;
}) {
  const missingLine = missingSummary(gapGroups(report));
  return (
    <ResultFrame
      embedded={embedded}
      title={embedded ? undefined : report.title}
      description={embedded ? undefined : report.seniority || undefined}
    >
      <ResumeQualityNotice quality={report.quality} />
      <div className="mb-5">
        <p className="text-[15px] font-medium text-ink">{reportHeadline(report)}</p>
        {missingLine && <p className="text-sm text-ink-muted">{missingLine}</p>}
      </div>
      <ReportFigures report={report} />
      <div className="mt-6">
        <ReportNotes report={report} />
      </div>
    </ResultFrame>
  );
}
