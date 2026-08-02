import type { TemplateAnalyzeResponse } from "../../api";

type Props = {
  analysis: TemplateAnalyzeResponse;
};

/**
 * Compatibility summary: blockers, warnings, and detected sections.
 */
export function AnalyzeReport({ analysis }: Props) {
  const blockers = analysis.issues.filter((i) => i.blocking);
  const warnings = analysis.issues.filter((i) => !i.blocking);

  return (
    <div className="mt-4 space-y-3 text-sm">
      <div className="rounded-lg border border-line/80 bg-paper/40 px-3 py-2">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
          Detected sections
        </p>
        {analysis.sections.length === 0 ? (
          <p className="mt-1 text-ink-muted">None</p>
        ) : (
          <ul className="mt-1 space-y-1">
            {analysis.sections.map((s) => (
              <li key={`${s.key}-${s.heading_paragraph_id}`}>
                <span className="font-medium text-ink">{s.key}</span>
                <span className="text-ink-muted">
                  {" "}
                  ← “{s.heading_text}” ({s.entry_count} entries, {s.bullet_count}{" "}
                  bullets, {(s.confidence * 100).toFixed(0)}% conf.)
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {blockers.length > 0 ? (
        <div className="rounded-md bg-danger-soft px-3 py-2 text-danger">
          <p className="font-semibold">Blocking issues</p>
          <ul className="mt-1 list-disc pl-5">
            {blockers.map((i) => (
              <li key={i.code + i.message}>{i.message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {warnings.length > 0 ? (
        <div className="rounded-md bg-warn-soft px-3 py-2 text-warn">
          <p className="font-semibold">Warnings</p>
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((i) => (
              <li key={i.code + i.message}>{i.message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {analysis.ready ? (
        <p className="rounded-md bg-accent-soft px-3 py-2 text-accent">
          Suggested mapping looks installable. Review the toggles below, then install.
        </p>
      ) : (
        <p className="rounded-md bg-danger-soft px-3 py-2 text-danger">
          Cannot install until blocking issues are fixed in the source document (or use
          the legacy path only for the original all-caps layout).
        </p>
      )}
    </div>
  );
}
