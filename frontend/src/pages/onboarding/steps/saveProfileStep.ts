import { contactErrors } from "../../../lib/onboardingContact";
import type { useEditorState } from "../../../state/editorState";
import type { useProfileFields } from "../../profile/useProfileFields";

/**
 * Save a profile step: the applicant profile and, when its contact block changed, the
 * master resume. Forward moves validate; leaving retains invalid drafts for correction.
 */
export async function saveProfileStep(
  fields: ReturnType<typeof useProfileFields>,
  editor: ReturnType<typeof useEditorState>,
  setError: (message: string | null) => void,
  mode: "forward" | "leave" = "forward",
): Promise<boolean> {
  setError(null);
  const invalid = Object.keys({ ...fields.allErrors, ...contactErrors(editor.resume?.contact) });
  if (mode === "leave" && invalid.length) return true; // retain the draft in its provider
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
