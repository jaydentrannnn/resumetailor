import { useState } from "react";
import { importMasterResumeContent, mergeMasterResume } from "../api";
import type { MasterResume } from "../lib/resumeEdit";
import { useEditorState } from "../state/editorState";
import { UploadDropzone } from "./template/UploadDropzone";

type Outcome =
  | {
      kind: "merged";
      updated: string[];
      added: string[];
      addedSections: string[];
      warnings: string[];
      backup: string | null;
    }
  | { kind: "draft"; warnings: string[]; untagged: number }
  | { kind: "error"; error: string };

const MERGE_CONFIRM_MESSAGE =
  "Merge this file's content into the master resume?\n\n" +
  "Entries are matched by company/school/project name: matching entries are updated " +
  "(their bullets refreshed), new ones are added, and everything else in your master " +
  "resume is left as-is. The current file is backed up first.";

/**
 * Standalone import entry point for the Master resume tab. Previously the only path
 * to `POST /api/master-resume/import` was a checkbox buried inside the Template tab's
 * *Replace template* wizard — a new user landing here on a placeholder resume had no
 * way to import one at all. Mirrors that wizard's confirm-merge-or-load-draft flow
 * (see `TemplateImportWizard.tsx`) but standalone, since this page has no wizard step
 * machine to hang off of.
 */
export function ImportResumePanel() {
  const { loadDraft, syncFromDisk } = useEditorState();
  const [suggestTags, setSuggestTags] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  async function handleFile(file: File) {
    setBusy(true);
    setOutcome(null);
    try {
      const result = await importMasterResumeContent(file, { suggestTags });
      if (window.confirm(MERGE_CONFIRM_MESSAGE)) {
        const merged = await mergeMasterResume(result.resume);
        syncFromDisk(
          merged.resume as MasterResume,
          "Master resume merged from the uploaded document.",
        );
        setOutcome({
          kind: "merged",
          updated: merged.updated,
          added: merged.added,
          addedSections: merged.added_sections,
          warnings: merged.warnings,
          backup: merged.backup,
        });
      } else {
        loadDraft(
          result.resume as MasterResume,
          "Imported from the uploaded document — review below and save to keep it.",
        );
        setOutcome({
          kind: "draft",
          warnings: result.warnings,
          untagged: result.untagged_bullet_count,
        });
      }
    } catch (err) {
      setOutcome({ kind: "error", error: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <h2 className="font-display text-lg font-semibold">Import from a document</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Upload a .docx resume to fold its content into the master resume below —
        matching entries are updated, new ones are added, nothing else changes.
      </p>

      <UploadDropzone disabled={busy} onFile={(file) => void handleFile(file)} />

      <label className="mt-3 flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={suggestTags}
          disabled={busy}
          onChange={(e) => setSuggestTags(e.target.checked)}
        />
        <span>
          <span className="font-medium text-ink">Suggest tags for untagged bullets</span>
          <span className="block text-xs text-ink-muted">
            Uses an LLM call to propose tags for bullets the deterministic import
            could not match on its own. Never blocks the import if it fails.
          </span>
        </span>
      </label>

      {outcome?.kind === "error" && (
        <p className="mt-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          Import failed: {outcome.error}
        </p>
      )}
      {outcome?.kind === "draft" && (
        <div className="mt-4 rounded-md bg-accent-soft px-3 py-2 text-sm text-accent">
          <p>
            Content imported as an unsaved draft — review below and Save to keep it.
            {outcome.untagged > 0 ? ` ${outcome.untagged} bullet(s) need a tag.` : null}
          </p>
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
        <div className="mt-4 rounded-md bg-accent-soft px-3 py-2 text-sm text-accent">
          <p>
            Master resume merged — {outcome.updated.length} updated, {outcome.added.length}{" "}
            added
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
    </section>
  );
}
