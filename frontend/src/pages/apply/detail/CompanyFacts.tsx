import type { CompanyResearch } from "../../../api";
import { Button } from "../../../components/ui";
import {
  FACT_KIND_LABELS,
  formatDay,
  researchNotes,
  sourceLabel,
} from "../../../lib/companyResearch";

/** Each fact with the words that state it, its source and date; Remove hides it for good. */
export function CompanyFacts({
  research,
  busy,
  onRemove,
}: {
  research: CompanyResearch;
  busy: boolean;
  onRemove: (factId: string) => void;
}) {
  const sources = new Map(research.sources.map((source) => [source.id, source]));
  const notes = researchNotes(research);
  return (
    <div className="space-y-3">
      {research.facts.length ? (
        <ul className="divide-y divide-line">
          {research.facts.map((fact) => {
            const source = sources.get(fact.source_id);
            return (
              <li key={fact.id} className="flex items-start gap-3 py-2.5 first:pt-0">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-sm text-ink">{fact.text}</p>
                  <p className="text-xs text-ink-muted">
                    <span className="italic">“{fact.excerpt}”</span>
                  </p>
                  <p className="text-xs text-ink-muted">
                    {FACT_KIND_LABELS[fact.kind]} ·{" "}
                    {source?.url ? (
                      <a className="rt-link" href={source.url} target="_blank" rel="noreferrer">
                        {sourceLabel(source)}
                      </a>
                    ) : (
                      sourceLabel(source)
                    )}
                    {fact.as_of ? ` · ${formatDay(fact.as_of)}` : ""}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  aria-label={`Remove: ${fact.text}`}
                  onClick={() => onRemove(fact.id)}
                >
                  Remove
                </Button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-ink-muted">
          No fact could be quoted from these sources. Add the company&apos;s about page or a note.
        </p>
      )}
      {notes.length > 0 && (
        <ul className="space-y-0.5 text-xs text-ink-muted">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
      <details className="text-xs text-ink-muted">
        <summary className="cursor-pointer select-none">
          Sources ({research.sources.length})
        </summary>
        <ul className="mt-1.5 space-y-1">
          {research.sources.map((source) => (
            <li key={source.id}>
              {source.url ? (
                <a className="rt-link" href={source.url} target="_blank" rel="noreferrer">
                  {source.title || sourceLabel(source)}
                </a>
              ) : (
                sourceLabel(source)
              )}
              {source.flags.length > 0 && ` · ${source.flags.join(" ")}`}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
