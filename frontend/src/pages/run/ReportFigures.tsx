import type { ReactNode } from "react";
import type { RunReport } from "../../api";
import { DataList, InlineHelp, Stat } from "../../components/ui";
import { GLOSSARY, type GlossaryKey } from "../../lib/glossary";

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
  const pct =
    diagnosis == null && report.coverage_total > 0
      ? Math.round((100 * report.coverage_matched) / report.coverage_total)
      : null;
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
          <span className="block font-mono tabular-nums">
            {diagnosis
              ? "couldn't be measured"
              : `${report.coverage_matched} of ${report.coverage_total}`}
          </span>
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
