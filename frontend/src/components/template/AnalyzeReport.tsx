import type { TemplateAnalyzeResponse, TemplateFieldCandidate } from "../../api";
import { IssueList, type IssueActions } from "./IssueList";

type Props = {
  analysis: TemplateAnalyzeResponse;
  actions?: IssueActions;
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
          <li key={field} className={missing ? "text-danger" : "text-ink-muted"}>
            <span className="font-medium">{field}</span>
            {candidate ? (
              <>
                {": "}
                <span className="font-mono">“{candidate.preview || "(empty)"}”</span> (
                {(candidate.confidence * 100).toFixed(0)}% conf.)
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
export function AnalyzeReport({ analysis, actions }: Props) {
  const blockers = analysis.issues.filter((i) => i.blocking);
  const warnings = analysis.issues.filter((i) => !i.blocking);

  return (
    <div className="mt-4 space-y-3 text-sm">
      <div className="border-t border-line pt-4">
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
                  ← “{s.heading_text}” ({s.entry_count} entries, {s.bullet_count} bullets,{" "}
                  {(s.confidence * 100).toFixed(0)}% conf.)
                </span>
                <SectionFieldRows
                  sectionKey={s.key}
                  candidates={(analysis.field_candidates ?? []).filter((c) =>
                    c.section_heading_paragraph_id != null
                      ? c.section_heading_paragraph_id === s.heading_paragraph_id
                      : c.paragraph_id >= s.body_start && c.paragraph_id < s.body_end,
                  )}
                />
              </li>
            ))}
          </ul>
        )}
      </div>

      {blockers.length > 0 ? <IssueList issues={blockers} tone="danger" actions={actions} /> : null}
      {warnings.length > 0 ? <IssueList issues={warnings} tone="warn" actions={actions} /> : null}

      {analysis.ready ? (
        <p className="border-t border-line pt-4 text-accent">
          Suggested mapping looks installable. Review the toggles below, then install.
        </p>
      ) : (
        <p className="border-t border-line pt-4 text-danger">
          Can't install yet. Fix the items above in your document, save it as .docx, and upload it
          again.
        </p>
      )}
    </div>
  );
}
