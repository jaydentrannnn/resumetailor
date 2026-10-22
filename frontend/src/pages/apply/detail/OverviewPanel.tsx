import type { ApplicationRow, JobStatus } from "../../../api";
import { DataList, StatusChip, Tile } from "../../../components/ui";
import { applicationStatusLabel } from "../../../lib/applicationStatus";
import { ReportCard } from "../../run/ReportCard";
import { siteName } from "../../CapturedStubs";
import { PostedDate } from "../PostedDate";

/** Overview: the application's facts, why it was screened out, and the tailor report. */
export function OverviewPanel({ app, job }: { app: ApplicationRow; job: JobStatus | null }) {
  const screen = app.screen;
  const report = job?.report;
  // The tailored page's figure once there is one (the loaded report is the freshest),
  // the screen's resume figure before tailoring.
  const page = report?.page_coverage_matched ?? screen?.page_coverage_matched;
  const total = page != null && report ? report.coverage_total : screen?.coverage_total;
  const matched = page ?? screen?.coverage_matched ?? 0;
  const coverage = total
    ? `${matched}/${total} (${Math.round((matched / total) * 100)}%) ${page != null ? "on the tailored page" : "in your resume, before tailoring"}`
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
              value: total ? <span className="font-mono text-[13px]">{coverage}</span> : coverage,
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
        <PostingCheck app={app} />
        {app.error && <p className="mt-4 text-sm text-danger">{app.error}</p>}
      </Tile>
      {job?.report && <ReportCard report={job.report} />}
    </div>
  );
}

/**
 * What the posting check flagged: text addressed to AI tools (which holds an automatic
 * submit), invisible characters, look-alike letters. Nothing for a clean posting.
 */
function PostingCheck({ app }: { app: ApplicationRow }) {
  const warnings = app.posting_warnings ?? [];
  if (!warnings.length) return null;
  // The first line is already quoted in its warning; list any others under it.
  const more = app.posting_guard?.instruction_like.slice(1) ?? [];
  return (
    <div className="mt-5 border-t border-line pt-4 text-sm">
      <div className="flex items-center gap-2">
        <p className="font-semibold text-ink">Check this posting</p>
        {app.posting_guard?.instruction_like.length ? (
          <StatusChip tone="attention">Won't auto-submit</StatusChip>
        ) : null}
      </div>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-muted">
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
      {more.map((line) => (
        <blockquote className="mt-2 border-l-2 border-line pl-3 text-ink-muted" key={line}>
          “{line}”
        </blockquote>
      ))}
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
