import type { RunReport } from "../../api";

export function ReportCard({ report }: { report: RunReport }) {
  /** End-of-run summary cards mirroring the CLI report. */
  const diagnosis = report.extraction_diagnosis;
  const pct =
    diagnosis == null && report.coverage_total > 0
      ? Math.round((100 * report.coverage_matched) / report.coverage_total)
      : null;
  const mustHaveValue = diagnosis ? "inconclusive" : pct != null ? `${pct}%` : "n/a";
  const mustHaveSub = diagnosis
    ? diagnosis.replaceAll("_", " ")
    : `${report.coverage_matched}/${report.coverage_total}`;

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div>
        <h2 className="font-display text-xl font-semibold">{report.title}</h2>
        <p className="text-sm text-ink-muted">{report.seniority}</p>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm tabular-nums sm:grid-cols-5">
        <Stat label="Must-haves" value={mustHaveValue} sub={mustHaveSub} />
        <Stat
          label="Pages"
          value={String(report.pages)}
          sub={report.pages_are_estimated ? "estimated" : `${report.iterations} iter`}
        />
        <Stat
          label="Bullets"
          value={`${report.bullets_selected}`}
          sub={`of ${report.bullets_total}`}
        />
        <Stat
          label="Widows"
          value={String(report.widows_remaining)}
          sub={report.widows_repaired ? `${report.widows_repaired} fixed` : "none fixed"}
        />
        <Stat
          label="Verb repeats"
          value={String(report.verb_collisions_remaining)}
          sub={report.verbs_diversified ? `${report.verbs_diversified} fixed` : "none fixed"}
        />
      </dl>

      {(() => {
        const bandRank: Record<string, number> = {
          critical: 4,
          high: 3,
          meaningful: 2,
          preferred: 1,
          low_signal: 0,
        };
        const byBand = (a: (typeof report.gaps)[number], b: (typeof report.gaps)[number]) =>
          (bandRank[b.band ?? "meaningful"] ?? 0) - (bandRank[a.band ?? "meaningful"] ?? 0);
        const annotate = (g: (typeof report.gaps)[number]) =>
          g.band
            ? `${g.phrase} (${g.band}${g.evidence_tier ? `, ${g.evidence_tier}` : ""})`
            : g.phrase;
        const noEvidence = report.gaps
          .filter((g) => g.reason === "no_evidence")
          .slice()
          .sort(byBand);
        const otherGaps = report.gaps
          .filter((g) => g.reason !== "no_evidence")
          .slice()
          .sort(byBand);
        const gapCount =
          (report.missing_must_haves.length > 0 ? 1 : 0) +
          (report.unmatched_canonicals.length > 0 ? 1 : 0) +
          noEvidence.length +
          otherGaps.length;
        if (gapCount === 0) return null;
        return (
          <details className="mt-3 rounded-md border border-line/80 bg-paper/40 open:pb-2">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">
              Coverage gaps ({gapCount})
            </summary>
            <div className="space-y-2 px-3 pb-1 text-sm">
              {report.missing_must_haves.length > 0 && (
                <p className="rounded-md bg-warn-soft px-3 py-2 text-warn">
                  Not supported by master resume: {report.missing_must_haves.join(", ")}
                </p>
              )}
              {report.unmatched_canonicals.length > 0 && (
                <p className="text-ink-muted">
                  Matched no tag: {report.unmatched_canonicals.map(([c]) => c).join(", ")}
                </p>
              )}
              {noEvidence.length > 0 && (
                <p className="rounded-md bg-warn-soft px-3 py-2 text-warn">
                  No evidence in the master resume: {noEvidence.map(annotate).join(", ")}
                </p>
              )}
              {otherGaps.map((g) => (
                <p key={g.canonical} className="text-ink-muted">
                  {g.reason === "untagged_evidence"
                    ? `${annotate(g)}: evidence exists but no bullet is tagged for it (${g.evidence.join("; ")})`
                    : `${annotate(g)}: tagged under a different name (${g.evidence.join("; ")})`}
                </p>
              ))}
            </div>
          </details>
        );
      })()}

      <div className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <EntryList title="Experience" entries={report.experience} />
        <EntryList title="Projects" entries={report.projects} />
      </div>

      {(() => {
        const warnCount =
          report.dropped.length + report.warnings.length + (report.calibration_rejection ? 1 : 0);
        if (warnCount === 0) return null;
        return (
          <details className="mt-3 rounded-md border border-line/80 bg-paper/40 open:pb-2">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">
              Run warnings ({warnCount})
            </summary>
            <div className="space-y-2 px-3 pb-1 text-sm">
              {report.dropped.length > 0 && (
                <p className="text-ink-muted">Dropped: {report.dropped.join(", ")}</p>
              )}
              {report.warnings.map((w) => (
                <p key={w} className="rounded-md bg-warn-soft px-3 py-2 text-warn">
                  {w}
                </p>
              ))}
              {report.calibration_rejection && (
                <p className="rounded-md bg-warn-soft px-3 py-2 text-warn">
                  {report.calibration_rejection}
                </p>
              )}
            </div>
          </details>
        );
      })()}

      <p className="mt-3 text-xs text-ink-muted">
        Model: {report.model} · ranking:{" "}
        {report.semantic_used ? "keyword + semantic" : "keyword only"} · PDF: {report.pdf_backend}
        {report.calibration_source === "fallback" ? " (fallback calibration)" : ""}
      </p>
    </section>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg bg-paper/60 px-3 py-2">
      <dt className="text-xs uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="font-display text-2xl font-semibold">{value}</dd>
      <dd className="text-xs text-ink-muted">{sub}</dd>
    </div>
  );
}

function EntryList({
  title,
  entries,
}: {
  title: string;
  entries: { label: string; kept: number; total: number; rewritten: number }[];
}) {
  if (!entries.length) return null;
  return (
    <div>
      <h3 className="font-medium">{title}</h3>
      <ul className="mt-1 space-y-1 text-ink-muted">
        {entries.map((e) => (
          <li key={e.label}>
            {e.label}: {e.kept}/{e.total}, {e.rewritten} rewritten
          </li>
        ))}
      </ul>
    </div>
  );
}
