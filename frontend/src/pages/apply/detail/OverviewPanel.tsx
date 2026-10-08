import type { ApplicationRow, JobStatus } from "../../../api";
import { DataList, Tile } from "../../../components/ui";
import { applicationStatusLabel } from "../../../lib/applicationStatus";
import { ReportCard } from "../../run/ReportCard";
import { siteName } from "../../CapturedStubs";
import { PostedDate } from "../PostedDate";

/** Overview: the application's facts, why it was screened out, and the tailor report. */
export function OverviewPanel({ app, job }: { app: ApplicationRow; job: JobStatus | null }) {
  const screen = app.screen;
  const coverage = screen?.coverage_total
    ? `${screen.coverage_matched}/${screen.coverage_total} (${Math.round((screen.coverage_matched / screen.coverage_total) * 100)}%)`
    : "Not assessed";
  const sources = [...new Set(app.sources)];
  return (
    <div className="space-y-4">
      <Tile title="Overview">
        <DataList
          items={[
            {
              label: "Status",
              value: app.capture_stub ? "Needs description" : applicationStatusLabel(app.status),
            },
            {
              label: "Coverage",
              value: <span className="font-mono text-[13px]">{coverage}</span>,
            },
            ...(app.ats ? [{ label: "Platform", value: siteName(app.ats) }] : []),
            {
              label: "Posted",
              value: (
                <span className="font-mono text-[13px]">
                  <PostedDate row={app} />
                </span>
              ),
            },
            ...(sources.length ? [{ label: "Found by", value: sources.join(", ") }] : []),
          ]}
        />
        {app.status === "screened_out" && screen && (
          <div className="mt-5 border-t border-line pt-4 text-sm">
            <p className="font-semibold text-ink">
              Screened out: {app.screen_label ?? "see reasons"}
            </p>
            <ul className="mt-1 list-disc pl-5 text-ink-muted">
              {screen.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            {screen.evidence?.map((quote, index) => (
              <blockquote className="mt-2 border-l-2 border-line pl-3 text-ink-muted" key={index}>
                “{quote}”
              </blockquote>
            ))}
          </div>
        )}
        {app.error && <p className="mt-4 text-sm text-danger">{app.error}</p>}
      </Tile>
      {job?.report && <ReportCard report={job.report} />}
    </div>
  );
}

/** Job description: the posting text saved with the application. */
export function JobDescriptionPanel({ text }: { text: string | null | undefined }) {
  return (
    <Tile title="Job description">
      {text ? (
        <p className="max-w-[80ch] whitespace-pre-wrap text-sm text-ink-2">{text}</p>
      ) : (
        <p className="text-sm text-ink-muted">
          The job description was not saved for this application.
        </p>
      )}
    </Tile>
  );
}
