import type { EvidenceSource } from "../../../api";
import { Button, StatusChip } from "../../../components/ui";
import { SOURCE_KIND_LABELS, attributionChip, sourceStatus } from "../../../lib/evidence";

/** Every source with whose work it is, its scan state, Scan and Remove. */
export function SourceList({
  sources,
  busy,
  onScan,
  onRemove,
}: {
  sources: EvidenceSource[];
  busy: string | null;
  onScan: (source: EvidenceSource) => void;
  onRemove: (source: EvidenceSource) => void;
}) {
  if (!sources.length) {
    return (
      <p className="text-sm text-ink-muted">No sources yet. Add your GitHub or a document above.</p>
    );
  }
  return (
    <ul className="divide-y divide-line">
      {sources.map((source) => {
        const chip = attributionChip(source);
        const fork = source.attribution === "fork";
        return (
          <li key={source.id} className="space-y-1.5 py-3 first:pt-0">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">
                  {source.url ? (
                    <a className="rt-link" href={source.url} target="_blank" rel="noreferrer">
                      {source.title}
                    </a>
                  ) : (
                    source.title
                  )}
                </p>
                <p className="text-xs text-ink-muted">
                  {SOURCE_KIND_LABELS[source.kind]}
                  {source.languages.length ? ` · ${source.languages.slice(0, 4).join(", ")}` : ""}
                </p>
              </div>
              {!fork && (
                <Button
                  size="sm"
                  variant={source.scanned_at ? "plain" : "secondary"}
                  loading={busy === source.id}
                  disabled={busy !== null}
                  onClick={() => onScan(source)}
                >
                  {source.scanned_at ? "Scan again" : "Scan"}
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                disabled={busy !== null}
                aria-label={`Remove ${source.title}`}
                onClick={() => onRemove(source)}
              >
                Remove
              </Button>
            </div>
            {chip && <StatusChip tone={chip.tone}>{chip.label}</StatusChip>}
            <p className="text-xs text-ink-muted">{sourceStatus(source)}</p>
            {source.flags.map((flag) => (
              <p key={flag} className="text-xs text-attn">
                {flag}
              </p>
            ))}
          </li>
        );
      })}
    </ul>
  );
}
