import type { ImportOutcome } from "./useTemplateContentImport";
export function TemplateContentResult({ importOutcome }: { importOutcome: ImportOutcome | null }) {
  return (
    <>
      {" "}
      {importOutcome?.kind === "error" ? (
        <p className="mt-4 border-t border-line pt-4 text-sm text-danger">
          Content import failed: {importOutcome.error}
        </p>
      ) : null}
      {importOutcome?.kind === "draft" ? (
        <div className="mt-4 border-t border-line pt-4 text-sm text-accent">
          <p>Content imported — open the Master Resume tab to review and save it.</p>
          {importOutcome.warnings.length > 0 ? (
            <ul className="mt-1 list-disc pl-5 text-xs text-ink-muted">
              {importOutcome.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {importOutcome?.kind === "merged" ? (
        <div className="mt-4 border-t border-line pt-4 text-sm text-accent">
          <p>
            Master resume merged — {importOutcome.updated.length} updated,{" "}
            {importOutcome.added.length} added
            {importOutcome.addedSections.length > 0
              ? ` (${importOutcome.addedSections.length} new section${
                  importOutcome.addedSections.length === 1 ? "" : "s"
                })`
              : ""}
            .{importOutcome.backup ? ` Previous file backed up as ${importOutcome.backup}.` : ""}
          </p>
          {importOutcome.updated.length > 0 ? (
            <p className="mt-1 text-xs text-ink-muted">
              Updated: {importOutcome.updated.join(", ")}
            </p>
          ) : null}
          {importOutcome.added.length > 0 ? (
            <p className="mt-1 text-xs text-ink-muted">Added: {importOutcome.added.join(", ")}</p>
          ) : null}
          {importOutcome.warnings.length > 0 ? (
            <ul className="mt-1 list-disc pl-5 text-xs text-ink-muted">
              {importOutcome.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
