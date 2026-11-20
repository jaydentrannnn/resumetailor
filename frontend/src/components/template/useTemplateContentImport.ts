import { createElement, useState } from "react";
import {
  importMasterResumeContent,
  mergeMasterResume,
  previewMasterResumeMerge,
  type MergePlan,
} from "../../api";
import { changedPicks, type MergePicks } from "../../lib/mergeReview";
import type { MasterResume } from "../../lib/resumeEdit";
import { MergeReview } from "../MergeReview";
import {
  MERGE_CHOICE_MESSAGE,
  MERGE_CHOICE_OPTIONS,
  MERGE_CHOICE_TITLE,
  UNSAVED_EDITS_NOTE,
  resumeIsEmpty,
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

/** Where the import was started, for the editor's status line. */
const MESSAGES = {
  template: {
    merged: "Your resume was filled in from the uploaded file.",
    draft: "Loaded from the uploaded file. Check it on the Resume page and save to keep it.",
  },
  resume: {
    merged: "Your resume was updated from the uploaded file.",
    draft: "Loaded from the uploaded file. Check it below and save to keep it.",
  },
} as const;

/**
 * Import a file's words into the master resume: the one path behind the template
 * wizard's "also import content", first-run setup's upload and the Resume page's import
 * panel. With entries in the saved resume, or unsaved edits on the Resume page, the user
 * chooses merge or draft; an empty saved resume with nothing unsaved has nothing to merge
 * into, so the words are saved without asking. The merge carries the preview's revision,
 * so a resume changed during the review is refused (409) rather than merged blind.
 *
 * `defaultOn` is the wizard's "also import content" switch: on for first-run setup (the
 * student uploaded a resume, not a design), off when replacing a template later.
 */
export function useTemplateContentImport({
  defaultOn = false,
  from = "template",
}: { defaultOn?: boolean; from?: keyof typeof MESSAGES } = {}) {
  const { resume, dirty, loadDraft, syncFromDisk } = useEditorState();
  const { choice } = useConfirm();
  // Content import is a separate action from the template install (it hits a
  // different endpoint), but the wizard offers it as "one upload does both".
  const [alsoImportContent, setAlsoImportContent] = useState(defaultOn);
  const [importBusy, setImportBusy] = useState(false);
  const [importOutcome, setImportOutcome] = useState<ImportOutcome | null>(null);

  /** Import `file`'s words; resolves to what happened, or null when the user cancelled. */
  const importContent = async (
    file: File,
    options?: { useModel?: boolean },
  ): Promise<ImportOutcome | null> => {
    setImportOutcome(null);
    setImportBusy(true);
    let outcome: ImportOutcome | null = null;
    try {
      const result = await importMasterResumeContent(file, options);
      // The preview is made against the saved resume, which is what a merge changes, so
      // it also says whether that resume is empty. If it cannot be fetched, the editor's
      // copy decides, and the question is still asked unless that copy is saved and empty.
      const plan: MergePlan | null = await previewMasterResumeMerge(result.resume).catch(
        () => null,
      );
      const savedEmpty = plan ? plan.existing_empty === true : !dirty && resumeIsEmpty(resume);
      // With entries in the resume, or unsaved edits the import would replace, the
      // question comes with the list of jobs and projects and what each would join.
      let picks: MergePicks | null = null;
      let picked: string | null = "merge";
      if (dirty || !savedEmpty) {
        picked = await choice({
          title: MERGE_CHOICE_TITLE,
          message: dirty
            ? `${UNSAVED_EDITS_NOTE}\n\n${MERGE_CHOICE_MESSAGE}`
            : MERGE_CHOICE_MESSAGE,
          body: plan?.pairs.length
            ? createElement(MergeReview, { plan, onChange: (next) => (picks = next) })
            : undefined,
          options: [...MERGE_CHOICE_OPTIONS],
        });
      }
      if (picked === "merge") {
        const merged = await mergeMasterResume(
          result.resume,
          plan && picks ? changedPicks(plan.pairs, picks) : {},
          plan?.revision ?? "",
        );
        syncFromDisk(merged.resume as MasterResume, MESSAGES[from].merged);
        outcome = {
          kind: "merged",
          updated: merged.updated,
          added: merged.added,
          addedSections: merged.added_sections,
          warnings: merged.warnings,
          backup: merged.backup,
        };
      } else if (picked === "draft") {
        loadDraft(result.resume as MasterResume, MESSAGES[from].draft);
        outcome = { kind: "draft", warnings: result.warnings };
      }
      // picked === null: the user cancelled; the editor is left as it was.
    } catch (err) {
      outcome = { kind: "error", error: err instanceof Error ? err.message : String(err) };
    } finally {
      setImportBusy(false);
    }
    setImportOutcome(outcome);
    return outcome;
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
