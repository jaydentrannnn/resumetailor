import { DataList } from "../../../components/ui";
import { SKIP_WARNINGS, contentComplete, reviewResume } from "../../../lib/onboarding";
import { useEditorState } from "../../../state/editorState";
import { EditorPage } from "../../editor/EditorPage";
import { StepFrame, type StepNav } from "../StepFrame";
import { completenessErrors } from "../../../lib/resumeEdit";
import { contactErrors } from "../../../lib/onboardingContact";

/** Step 3: what was imported, what is worth fixing, and the full editor to fix it in.
 * What application forms ask for (the profile-gap list) belongs to stage 2, not here. */
export function ContentStep({ nav }: { nav: StepNav }) {
  const editor = useEditorState();
  const review = reviewResume(editor.resume);
  const invalidContact = Object.values(contactErrors(editor.resume?.contact));

  return (
    <StepFrame
      title="Check your resume content"
      intro="Everything tailored later comes from here: your jobs, projects and their bullets. Fix anything the import missed."
      nav={nav}
      complete={contentComplete(review) && invalidContact.length === 0}
      onSave={(mode) =>
        mode === "leave" &&
        editor.resume &&
        (completenessErrors(editor.resume).length || invalidContact.length)
          ? Promise.resolve(true)
          : editor.dirty
            ? editor.save()
            : Promise.resolve(true)
      }
      skipWarning={SKIP_WARNINGS.content}
      error={
        invalidContact.length
          ? "Fix your contact details in the editor above: " + invalidContact.join(" ")
          : editor.dirty && editor.errors.length
            ? editor.errors[0]
            : null
      }
    >
      {review.entries > 0 && (
        <DataList
          items={[
            { label: "Entries", value: review.entries },
            { label: "Bullet points", value: review.bullets },
            ...review.sections.map((section) => ({ label: section.title, value: section.count })),
          ]}
          mono
        />
      )}
      {review.bullets === 0 && (
        <p className="text-sm text-attn">
          Add at least one job, project or activity with a bullet point below.
        </p>
      )}
      {review.warnings.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-attn">
          {review.warnings.slice(0, 8).map((w) => (
            <li key={w}>{w}</li>
          ))}
          {review.warnings.length > 8 && <li>…and {review.warnings.length - 8} more.</li>}
        </ul>
      )}
      <div className="border-t border-line pt-4">
        {/* The contact block stays: a missing name blocks tailoring, and this is the
            only stage-1 step where it can be fixed. */}
        <EditorPage embedded />
      </div>
    </StepFrame>
  );
}
