import { Link } from "react-router-dom";
import type { RunReport } from "../../api";
import { InlineHelp } from "../../components/ui";
import { GLOSSARY, type GlossaryKey } from "../../lib/glossary";
import { gapGroups, reportHeadline } from "../../lib/reportSummary";

/**
 * End-of-run summary: one headline, a few plain-language numbers, the skills the
 * resume could not show (as a to-do list, never filled in for the student), and the
 * run's internals folded under "Technical details".
 */
export function ReportCard({ report }: { report: RunReport }) {
  const diagnosis = report.extraction_diagnosis;
  const pct =
    diagnosis == null && report.coverage_total > 0
      ? Math.round((100 * report.coverage_matched) / report.coverage_total)
      : null;
  const gaps = gapGroups(report);
  const warnCount =
    report.dropped.length + report.warnings.length + (report.calibration_rejection ? 1 : 0);

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div>
        <h2 className="font-display text-xl font-semibold">{report.title}</h2>
        {report.seniority && <p className="text-sm text-ink-muted">{report.seniority}</p>}
        <p className="mt-2 text-base font-medium text-ink">{reportHeadline(report)}</p>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm tabular-nums sm:grid-cols-4">
        <Stat
          term="mustHaves"
          value={diagnosis ? "—" : pct != null ? `${pct}%` : "n/a"}
          sub={
            diagnosis
              ? "couldn't be measured"
              : `${report.coverage_matched} of ${report.coverage_total}`
          }
        />
        <Stat
          label="Bullets used"
          value={String(report.bullets_selected)}
          sub={`of ${report.bullets_total} in your resume`}
        />
        <Stat
          term="widows"
          value={String(report.widows_remaining)}
          sub={report.widows_repaired ? `${report.widows_repaired} fixed` : "none fixed"}
        />
        <Stat
          term="verbRepeats"
          value={String(report.verb_collisions_remaining)}
          sub={report.verbs_diversified ? `${report.verbs_diversified} fixed` : "none fixed"}
        />
      </dl>

      {gaps.missing.length > 0 && (
        <GapList
          title="Missing from your resume"
          note="Nothing in your master resume shows these, so they were not added. If you have real experience with one, add a bullet for it."
          action={<Link to="/profile/resume">Open resume editor</Link>}
          items={gaps.missing.map((g) => ({
            key: g.phrase,
            text: g.phrase,
            sub: g.band === "critical" || g.band === "high" ? "required" : undefined,
          }))}
          tone="warn"
        />
      )}
      {gaps.untagged.length > 0 && (
        <GapList
          title="In your resume, but not on a bullet"
          note="Tag a bullet that shows this skill so future runs can pick it."
          action={<Link to="/profile/resume">Add tags in the editor</Link>}
          items={gaps.untagged.map((g) => ({
            key: g.phrase,
            text: g.phrase,
            sub: g.where.join("; "),
          }))}
        />
      )}
      {gaps.renamed.length > 0 && (
        <GapList
          title="Named differently"
          note="Your resume uses another name for these. Teach ResumeTailor that the names mean the same thing."
          action={<Link to="/vocabulary">Open vocabulary</Link>}
          items={gaps.renamed.map((g) => ({
            key: g.phrase,
            text: g.phrase,
            sub: g.where.join("; "),
          }))}
        />
      )}

      <div className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <EntryList title="Experience" entries={report.experience} />
        <EntryList title="Projects" entries={report.projects} />
      </div>

      {warnCount > 0 && (
        <details className="mt-3 rounded-md border border-line/80 bg-paper/40 open:pb-2">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">
            Things to check ({warnCount})
          </summary>
          <div className="space-y-2 px-3 pb-1 text-sm">
            {report.dropped.length > 0 && (
              <p className="text-ink-muted">Left out: {report.dropped.join(", ")}</p>
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
      )}

      <details className="mt-3 text-xs text-ink-muted">
        <summary className="cursor-pointer font-medium">Technical details</summary>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt>Model</dt>
          <dd>{report.model}</dd>
          <dt>Ranking</dt>
          <dd>{report.semantic_used ? GLOSSARY.semantic.label : "Keyword match only"}</dd>
          <dt>PDF engine</dt>
          <dd>{report.pdf_backend}</dd>
          <dt>Page fit</dt>
          <dd>
            {report.calibration_source === "fallback"
              ? "estimated (not tuned for this template)"
              : GLOSSARY.calibrated.label.toLowerCase()}
            {report.pages_are_estimated ? " · page count estimated" : ""}
          </dd>
          <dt>Fit passes</dt>
          <dd>{report.iterations}</dd>
          {diagnosis && (
            <>
              <dt>Skill match</dt>
              <dd>{diagnosis.replaceAll("_", " ")}</dd>
            </>
          )}
        </dl>
      </details>
    </section>
  );
}

function Stat({
  term,
  label,
  value,
  sub,
}: {
  term?: GlossaryKey;
  label?: string;
  value: string;
  sub: string;
}) {
  const entry = term ? GLOSSARY[term] : null;
  return (
    <div className="rounded-lg bg-paper/60 px-3 py-2">
      <dt className="flex items-center gap-1 text-xs text-ink-muted">
        {entry?.label ?? label}
        {entry && <InlineHelp label={entry.label}>{entry.help}</InlineHelp>}
      </dt>
      <dd className="font-display text-2xl font-semibold">{value}</dd>
      <dd className="text-xs text-ink-muted">{sub}</dd>
    </div>
  );
}

function GapList({
  title,
  note,
  action,
  items,
  tone,
}: {
  title: string;
  note: string;
  action: React.ReactNode;
  items: { key: string; text: string; sub?: string }[];
  tone?: "warn";
}) {
  return (
    <div
      className={`mt-4 rounded-lg border p-3 text-sm ${tone === "warn" ? "border-warn/40 bg-warn-soft/30" : "border-line"}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-medium text-ink">
          {title} ({items.length})
        </h3>
        <span className="text-xs font-medium text-accent underline">{action}</span>
      </div>
      <p className="mt-1 text-xs text-ink-muted">{note}</p>
      <ul className="mt-2 space-y-1">
        {items.map((item) => (
          <li key={item.key} className="flex gap-2">
            <span aria-hidden className="text-ink-muted">
              ☐
            </span>
            <span>
              <span className="text-ink">{item.text}</span>
              {item.sub && <span className="text-ink-muted"> · {item.sub}</span>}
            </span>
          </li>
        ))}
      </ul>
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
            {e.label}: {e.kept} of {e.total} bullets, {e.rewritten} reworded
          </li>
        ))}
      </ul>
    </div>
  );
}
