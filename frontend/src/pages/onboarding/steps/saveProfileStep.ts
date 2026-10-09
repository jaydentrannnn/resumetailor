import type { useEditorState } from "../../../state/editorState";
import type { useProfileFields } from "../../profile/useProfileFields";

/**
 * Save a profile step: the applicant profile and, when its contact block changed, the
 * master resume. A malformed field blocks the move and shows every problem instead of
 * dropping the input.
 */
export async function saveProfileStep(
  fields: ReturnType<typeof useProfileFields>,
  editor: ReturnType<typeof useEditorState>,
  setError: (message: string | null) => void,
): Promise<boolean> {
  setError(null);
  const invalid = Object.keys(fields.allErrors);
  if (invalid.length) {
    fields.setAttempted(true);
    setError(
      `${invalid.length} field${invalid.length === 1 ? " needs" : "s need"} fixing before you move on.`,
    );
    return false;
  }
  if (editor.dirty && !(await editor.save())) {
    setError(`Resume not saved${editor.errors[0] ? `: ${editor.errors[0]}` : "."}`);
    return false;
  }
  if (fields.applicant.dirty && !(await fields.applicant.save())) {
    setError(`Not saved: ${fields.applicant.error ?? "try again."}`);
    return false;
  }
  fields.reset();
  return true;
}
