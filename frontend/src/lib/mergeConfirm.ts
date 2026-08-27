/**
 * Shared copy for the master-resume merge vs. draft choice after a .docx import.
 * Used by both the Master resume Import panel and the Template wizard's content-merge
 * checkbox — keep the wording identical so both paths feel like the same decision.
 */
export const MERGE_CHOICE_TITLE = "How should this content be applied?";

export const MERGE_CHOICE_MESSAGE =
  "Entries are matched by company/school/project name: matching entries are updated " +
  "(their bullets refreshed), new ones are added, and everything else in your master " +
  "resume is left as-is. The current file is backed up before a merge.\n\n" +
  "Choose Merge to write immediately, or Review as draft to load the import into the " +
  "editor without saving until you click Save.";

export const MERGE_CHOICE_OPTIONS = [
  { id: "merge", label: "Merge into master resume" },
  { id: "draft", label: "Review as draft" },
] as const;
