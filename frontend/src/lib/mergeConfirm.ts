/**
 * Shared copy for the master-resume merge vs. draft choice after a .docx import.
 * Used by both the Master resume Import panel and the Template wizard's content-merge
 * checkbox — keep the wording identical so both paths feel like the same decision.
 */
export const MERGE_CHOICE_TITLE = "Add this to your resume?";

export const MERGE_CHOICE_MESSAGE =
  "Entries that match one you already have are updated, new ones are added, and the " +
  "rest of your resume stays as it is. Your current resume is backed up first.\n\n" +
  "Add it now, or check it first: that loads it into the editor and nothing is saved " +
  "until you press Save.";

/** Put before the message when the Resume page has unsaved edits. */
export const UNSAVED_EDITS_NOTE =
  "You have unsaved changes on the Resume page. Either choice replaces them, so save " +
  "them first if you want to keep them.";

export const MERGE_CHOICE_OPTIONS = [
  { id: "merge", label: "Add to my resume" },
  { id: "draft", label: "Check it first" },
] as const;

/**
 * Whether the master resume is loaded and has no entry yet. An import then has nothing
 * to merge into, so the merge-or-draft question is skipped and the words are saved
 * directly. A resume that has not loaded is not known to be empty, so the question is
 * still asked.
 */
export function resumeIsEmpty(
  resume: { sections: { entries: unknown[] }[] } | null | undefined,
): boolean {
  return !!resume && !resume.sections.some((section) => section.entries.length > 0);
}
