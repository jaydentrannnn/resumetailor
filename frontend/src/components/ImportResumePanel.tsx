import { StatusMark, Tile } from "./ui";
import { useState } from "react";
import { UploadDropzone } from "./template/UploadDropzone";
import { useTemplateContentImport } from "./template/useTemplateContentImport";

/**
 * Standalone import entry point for the Master resume tab. Previously the only path
 * to `POST /api/master-resume/import` was a checkbox buried inside the Template tab's
 * *Replace template* wizard — a new user landing here on a placeholder resume had no
 * way to import one at all. Shares the wizard's import path
 * (`useTemplateContentImport`), standalone since this page has no wizard step machine
 * to hang off of.
 */
export function ImportResumePanel({
  title = "Import from a document",
  intro,
  embedded = false,
}: {
  title?: string;
  intro?: string;
  embedded?: boolean;
} = {}) {
  const [useModel, setUseModel] = useState(false);
  const {
    importBusy: busy,
    importOutcome: outcome,
    importContent,
  } = useTemplateContentImport({ from: "resume" });
  const handleFile = (file: File) => importContent(file, { useModel });

  return (
    <Tile title={title} className={embedded ? "border-0 bg-transparent p-0 sm:px-0" : ""}>
      <p className="mt-1 text-sm text-ink-muted">
        {intro ??
          "Upload a Word or PDF resume to add its content to the resume below. Matching entries are updated, new ones are added, and nothing else changes."}
      </p>

      <UploadDropzone allowPdf disabled={busy} onFile={(file) => void handleFile(file)} />

      <label className="mt-3 flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={useModel}
          disabled={busy}
          onChange={(e) => setUseModel(e.target.checked)}
        />
        <span>
          <span className="font-medium text-ink">Let the AI model sort a PDF into sections</span>
          <span className="block text-xs text-ink-muted">
            Helps with unusual layouts. Every name, title and date it picks is checked against the
            PDF's own text, and the built-in reader is used if the model can't be reached.
          </span>
        </span>
      </label>

      {outcome?.kind === "error" && (
        <p className="mt-4 flex items-center gap-2 text-sm text-danger">
          <StatusMark tone="failed" /> Import failed: {outcome.error}
        </p>
      )}
      {outcome?.kind === "draft" && (
        <div className="mt-4 border-t border-line pt-4 text-sm text-ink">
          <p>The content is loaded but not saved. Check it below and press Save to keep it.</p>
          {outcome.warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs text-ink-muted">
              {outcome.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {outcome?.kind === "merged" && (
        <div className="mt-4 border-t border-line pt-4 text-sm text-ink">
          <p>
            Your resume was updated: {outcome.updated.length} changed, {outcome.added.length} added
            {outcome.addedSections.length > 0
              ? ` (${outcome.addedSections.length} new section${
                  outcome.addedSections.length === 1 ? "" : "s"
                })`
              : ""}
            .{outcome.backup ? ` Previous file backed up as ${outcome.backup}.` : ""}
          </p>
          {outcome.updated.length > 0 && (
            <p className="mt-1 text-xs text-ink-muted">Updated: {outcome.updated.join(", ")}</p>
          )}
          {outcome.added.length > 0 && (
            <p className="mt-1 text-xs text-ink-muted">Added: {outcome.added.join(", ")}</p>
          )}
          {outcome.warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs text-ink-muted">
              {outcome.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Tile>
  );
}
