import type { ApplicationRow, JobStatus } from "../../../api";
import { fitChecks, pageStrengths } from "../../../lib/fitSummary";

/**
 * Fit: the must-haves the tailored page shows, and what screening flagged without
 * rejecting (languages, years asked for, seniority). Missing skills are in the report
 * below, so they are not repeated here. Nothing when there is neither.
 */
export function FitNotes({ app, job }: { app: ApplicationRow; job: JobStatus | null }) {
  const strengths = pageStrengths(job?.report?.coverage_funnel);
  const checks = fitChecks(app);
  if (!strengths.length && !checks.length) return null;
  return (
    <div className="mt-5 border-t border-line pt-4 text-sm">
      <p className="font-semibold text-ink">Fit</p>
      {strengths.length > 0 && (
        <p className="mt-1 text-ink-2">
          <span className="text-ink-muted">Required skills the page shows: </span>
          {strengths.join(", ")}
        </p>
      )}
      {checks.length > 0 && (
        <>
          <p className="mt-2 text-ink-muted">Worth checking before you apply</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-muted">
            {checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
