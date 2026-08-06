import type { TemplateAnalyzeResponse, TemplateFieldCandidate } from "../../api";

type Props = {
  analysis: TemplateAnalyzeResponse;
};

//: Fields the wizard cares about seeing even when nothing was detected for them —
//: a missing "dates" row is exactly the finding that motivated exposing this at all.
const REQUIRED_FIELDS_BY_KEY: Record<string, string[]> = {
  experience: ["company", "dates"],
  projects: ["name", "date"],
  education: ["school", "dates"],
};

/** Per-field detection rows for one section: confidence, preview text, and a red row
 * for any required field the analyzer found nothing for. */
function SectionFieldRows({
  sectionKey,
  candidates,
}: {
  sectionKey: string;
  candidates: TemplateFieldCandidate[];
}) {
  const required = REQUIRED_FIELDS_BY_KEY[sectionKey] ?? [];
  const byField = new Map<string, TemplateFieldCandidate>();
  for (const c of candidates) {
    // Keep the highest-confidence candidate per field when more than one was proposed.
    const existing = byField.get(c.field);
    if (!existing || c.confidence > existing.confidence) byField.set(c.field, c);
  }
  const fields = new Set([...required, ...byField.keys()]);
  if (fields.size === 0) return null;

  return (
    <ul className="mt-1 space-y-0.5 pl-3 text-xs">
      {[...fields].map((field) => {
        const candidate = byField.get(field);
        const missing = !candidate && required.includes(field);
        return (
          <li
            key={field}
            className={missing ? "text-danger" : "text-ink-muted"}
          >
            <span className="font-medium">{field}</span>
            {candidate ? (
              <>
                {": "}
                <span className="font-mono">
                  “{candidate.preview || "(empty)"}”
                </span>{" "}
                ({(candidate.confidence * 100).toFixed(0)}% conf.)
              </>
            ) : (
              " — not detected"
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Compatibility summary: blockers, warnings, detected sections, and per-field spans.
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
          <ul className="mt-1 space-y-2">
            {analysis.sections.map((s) => (
              <li key={`${s.key}-${s.heading_paragraph_id}`}>
                <span className="font-medium text-ink">{s.key}</span>
                <span className="text-ink-muted">
                  {" "}
                  ← “{s.heading_text}” ({s.entry_count} entries, {s.bullet_count}{" "}
                  bullets, {(s.confidence * 100).toFixed(0)}% conf.)
                </span>
                <SectionFieldRows
                  sectionKey={s.key}
                  candidates={(analysis.field_candidates ?? []).filter(
                    (c) => c.paragraph_id >= s.body_start && c.paragraph_id < s.body_end,
                  )}
                />
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
