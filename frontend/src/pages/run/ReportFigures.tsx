import type { ReactNode } from "react";
import type { RunReport } from "../../api";
import { DataList, InlineHelp, Stat } from "../../components/ui";
import { GLOSSARY, type GlossaryKey } from "../../lib/glossary";
import { CoverageBreakdown } from "./CoverageBreakdown";

/** A glossary term as a label, with its "?" explanation. */
function Term({ term }: { term: GlossaryKey }) {
  const entry = GLOSSARY[term];
  return (
    <span className="inline-flex items-center gap-1">
      {entry.label}
      <InlineHelp label={entry.label}>{entry.help}</InlineHelp>
    </span>
  );
}

/**
 * The run's numbers: page count, required-skill coverage and bullets used as big
 * figures, then the two polish counters (short last lines, repeated verbs) as quiet
 * label/value pairs.
 */
export function ReportFigures({ report }: { report: RunReport }) {
  const diagnosis = report.extraction_diagnosis;
  const total = report.coverage_total;
  // The headline is what the tailored page shows; a run saved before that was
  // measured falls back to the resume figure.
  const headline = report.page_coverage_matched ?? report.coverage_matched;
  const pct = diagnosis == null && total > 0 ? Math.round((100 * headline) / total) : null;
  const named = report.coverage_funnel?.in_resume_text;
  const figures: { value: string; label: ReactNode }[] = [
    {
      value: String(report.pages),
      label: `page${report.pages === 1 ? "" : "s"}${report.pages_are_estimated ? " (estimated)" : ""}`,
    },
    {
      value: diagnosis ? "—" : pct != null ? `${pct}%` : "n/a",
      label: (
        <>
          <Term term="mustHaves" />
          {diagnosis ? (
            <span className="block font-mono tabular-nums">couldn't be measured</span>
          ) : (
            <>
              {report.page_coverage_matched != null && (
                <span className="block font-mono tabular-nums">
                  {`${report.page_coverage_matched} of ${total} on this page`}
                </span>
              )}
              <span className="block font-mono tabular-nums">
                {`${report.coverage_matched} of ${total} in your resume`}
              </span>
              {named != null && (
                <span className="block font-mono tabular-nums">
                  {`${named} of ${total} named in your resume`}
                </span>
              )}
            </>
          )}
        </>
      ),
    },
    {
      value: String(report.bullets_selected),
      label: `bullets used, of ${report.bullets_total} in your resume`,
    },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start gap-x-10 gap-y-5 pb-1 sm:gap-x-16">
        {figures.map((figure, index) => (
          <Stat key={index} value={figure.value} label={figure.label} />
        ))}
      </div>
      <DataList
        items={[
          {
            label: <Term term="widows" />,
            value: <Counter value={report.widows_remaining} fixed={report.widows_repaired} />,
          },
          {
            label: <Term term="verbRepeats" />,
            value: (
              <Counter value={report.verb_collisions_remaining} fixed={report.verbs_diversified} />
            ),
          },
        ]}
      />
      {!diagnosis && <CoverageBreakdown funnel={report.coverage_funnel} />}
    </div>
  );
}

function Counter({ value, fixed }: { value: number; fixed: number }) {
  return (
    <>
      <span className="font-mono tabular-nums">{value}</span>
      <span className="ml-2 text-xs font-normal text-ink-muted">
        {fixed ? `${fixed} fixed` : "none fixed"}
      </span>
    </>
  );
}
