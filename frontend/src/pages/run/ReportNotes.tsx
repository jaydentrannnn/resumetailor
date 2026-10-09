import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { RunReport } from "../../api";
import { StatusChip, StatusMark } from "../../components/ui";
import { GLOSSARY } from "../../lib/glossary";
import { gapGroups } from "../../lib/reportSummary";

/**
 * Everything in the report that is words, not figures: things to check, the skills the
 * resume could not show (a to-do list, never filled in for the student), what each
 * entry kept, and the run's internals folded under "Technical details". Sections are
 * separated by one hairline each, never boxed.
 */
export function ReportNotes({ report }: { report: RunReport }) {
  const gaps = gapGroups(report);
  const missingRequired = gaps.missing.filter((g) => g.required);
  const missingOptional = gaps.missing.filter((g) => !g.required);
  const editor = <Link to="/profile/resume">Open resume editor</Link>;

  return (
    <div className="space-y-5">
      <CheckNotes report={report} />
      {missingRequired.length > 0 && (
        <GapList
          title="Required by the posting, missing from your resume"
          note="The posting lists these as requirements and nothing in your master resume shows them, so they were not added. If you have real experience with one, add a bullet for it."
          action={editor}
          items={missingRequired.map((g) => ({ key: g.phrase, text: g.phrase }))}
          attention
        />
      )}
      {missingOptional.length > 0 && (
        <GapList
          title="Nice to have, missing from your resume"
          note="Mentioned in the posting but not required. Worth adding only if you really have them."
          action={editor}
          items={missingOptional.map((g) => ({ key: g.phrase, text: g.phrase }))}
          collapsed={missingOptional.length > 5}
        />
      )}
      {gaps.untagged.length > 0 && (
        <GapList
          title="In your resume, but not on a bullet"
          note="Mention it in a bullet that shows it (or add it to that bullet's Extra skills) so future runs can pick it."
          action={<Link to="/profile/resume">Open the editor</Link>}
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
      {(report.experience.length > 0 || report.projects.length > 0) && (
        <div className="grid grid-cols-1 gap-4 border-t border-line pt-4 text-sm sm:grid-cols-2">
          <EntryList title="Experience" entries={report.experience} />
          <EntryList title="Projects" entries={report.projects} />
        </div>
      )}
      <TechnicalDetails report={report} />
    </div>
  );
}

/** Dropped entries, run warnings and a rejected calibration, each with a status chip. */
function CheckNotes({ report }: { report: RunReport }) {
  const notes: { key: string; chip: ReactNode; text: string }[] = [
    ...report.warnings.map((w) => ({
      key: w,
      chip: <StatusChip tone="attention">Check</StatusChip>,
      text: w,
    })),
    ...(report.calibration_rejection
      ? [
          {
            key: "calibration",
            chip: <StatusChip tone="attention">Page fit</StatusChip>,
            text: report.calibration_rejection,
          },
        ]
      : []),
    ...(report.dropped.length
      ? [
          {
            key: "dropped",
            chip: <StatusChip tone="neutral">Left out</StatusChip>,
            text: report.dropped.join(", "),
          },
        ]
      : []),
  ];
  if (!notes.length) return null;
  return (
    <div>
      <h4 className="text-[13px] font-semibold text-ink">Things to check ({notes.length})</h4>
      <ul className="mt-2.5 grid gap-2.5">
        {notes.map((note) => (
          <li
            key={note.key}
            className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] text-ink-2"
          >
            {note.chip}
            <span className="min-w-0 flex-1">{note.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type GapItem = { key: string; text: string; sub?: string };

function GapList({
  title,
  note,
  action,
  items,
  attention,
  collapsed,
}: {
  title: string;
  note: string;
  action: ReactNode;
  items: GapItem[];
  /** Required gaps: the "needs you" ring beside the title. */
  attention?: boolean;
  /** Long secondary lists start folded so the required ones stay in view. */
  collapsed?: boolean;
}) {
  const heading = (
    <span className="inline-flex items-center gap-2">
      {attention && <StatusMark tone="attention" className="text-attn" />}
      {title} <span className="font-mono text-xs font-normal text-ink-muted">{items.length}</span>
    </span>
  );
  const link = <span className="rt-link text-xs font-medium">{action}</span>;
  const body = (
    <>
      <p className="mt-1 text-xs text-ink-muted">{note}</p>
      <GapItems items={items} />
    </>
  );
  const className = "border-t border-line pt-4 text-sm";
  if (collapsed) {
    return (
      <details className={className}>
        <summary className="cursor-pointer font-medium text-ink">{heading}</summary>
        <div className="mt-1">{link}</div>
        {body}
      </details>
    );
  }
  return (
    <div className={className}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-medium text-ink">{heading}</h4>
        {link}
      </div>
      {body}
    </div>
  );
}

function GapItems({ items }: { items: GapItem[] }) {
  return (
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
      <h4 className="font-medium text-ink">{title}</h4>
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

function TechnicalDetails({ report }: { report: RunReport }) {
  const diagnosis = report.extraction_diagnosis;
  return (
    <details className="border-t border-line pt-4 text-xs text-ink-muted">
      <summary className="cursor-pointer font-medium">Technical details</summary>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt>Model</dt>
        <dd className="font-mono">{report.model}</dd>
        <dt>Ranking</dt>
        <dd>{report.semantic_used ? GLOSSARY.semantic.label : "Keyword match only"}</dd>
        <dt>PDF engine</dt>
        <dd className="font-mono">{report.pdf_backend}</dd>
        <dt>Page fit</dt>
        <dd>
          {report.calibration_source === "fallback"
            ? "estimated (not tuned for this template)"
            : GLOSSARY.calibrated.label.toLowerCase()}
          {report.pages_are_estimated ? " · page count estimated" : ""}
        </dd>
        <dt>Fit passes</dt>
        <dd className="font-mono">{report.iterations}</dd>
        {diagnosis && (
          <>
            <dt>Skill match</dt>
            <dd>{diagnosis.replaceAll("_", " ")}</dd>
          </>
        )}
      </dl>
    </details>
  );
}
