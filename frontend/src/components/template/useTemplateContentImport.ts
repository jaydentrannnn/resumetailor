import { useState } from "react";
import { importMasterResumeContent, mergeMasterResume } from "../../api";
import type { MasterResume } from "../../lib/resumeEdit";
import {
  MERGE_CHOICE_MESSAGE,
  MERGE_CHOICE_OPTIONS,
  MERGE_CHOICE_TITLE,
} from "../../lib/mergeConfirm";
import { useConfirm } from "../../state/confirmState";
import { useEditorState } from "../../state/editorState";
export type ImportOutcome =
  | {
      kind: "merged";
      updated: string[];
      added: string[];
      addedSections: string[];
      warnings: string[];
      backup: string | null;
    }
  | { kind: "draft"; warnings: string[] }
  | { kind: "error"; error: string };

export function useTemplateContentImport() {
  const { loadDraft, syncFromDisk } = useEditorState();
  const { choice } = useConfirm();
  // Content import is a separate action from the template install (it hits a
  // different endpoint), but the wizard offers it as "one upload does both" — checked
  // here, run right after a successful install below.
  const [alsoImportContent, setAlsoImportContent] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importOutcome, setImportOutcome] = useState<ImportOutcome | null>(null);

  /** Import the file's words into the master resume (merge or draft, the user's
   * choice). Used after an install, or on its own when the layout can't be a template. */
  const importContent = async (file: File) => {
    setImportOutcome(null);
    setImportBusy(true);
    try {
      const result = await importMasterResumeContent(file);
      const picked = await choice({
        title: MERGE_CHOICE_TITLE,
        message: MERGE_CHOICE_MESSAGE,
        options: [...MERGE_CHOICE_OPTIONS],
      });
      if (picked === "merge") {
        const merged = await mergeMasterResume(result.resume);
        syncFromDisk(
          merged.resume as MasterResume,
          "Master resume merged from the template upload.",
        );
        setImportOutcome({
          kind: "merged",
          updated: merged.updated,
          added: merged.added,
          addedSections: merged.added_sections,
          warnings: merged.warnings,
          backup: merged.backup,
        });
      } else if (picked === "draft") {
        loadDraft(
          result.resume as MasterResume,
          "Imported from the template upload — review on the Master Resume tab and save to keep it.",
        );
        setImportOutcome({ kind: "draft", warnings: result.warnings });
      }
    } catch (err) {
      setImportOutcome({ kind: "error", error: err instanceof Error ? err.message : String(err) });
    } finally {
      setImportBusy(false);
    }
  };

  return {
    alsoImportContent,
    setAlsoImportContent,
    importBusy,
    importOutcome,
    setImportOutcome,
    importContent,
  };
}
