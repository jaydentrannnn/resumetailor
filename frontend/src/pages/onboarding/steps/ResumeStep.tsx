import { useState } from "react";
import { ImportResumePanel } from "../../../components/ImportResumePanel";
import { SimpleResumeImport } from "../../../components/template/SimpleResumeImport";
import { TemplateImportWizard } from "../../../components/template/TemplateImportWizard";
import { StarterTemplatesPanel } from "../../../components/template/StarterTemplatesPanel";
import { SKIP_WARNINGS } from "../../../lib/onboarding";
import { useEditorState } from "../../../state/editorState";
import { useTemplateState } from "../../../state/templateState";
import { StepFrame, type StepNav } from "../StepFrame";
import { completenessErrors } from "../../../lib/resumeEdit";
import { contactErrors } from "../../../lib/onboardingContact";
import { useUiMode } from "../../../lib/uiMode";

/** Step 2: upload the resume; a Word file's design becomes the template and its words
 * the content. A PDF gives the content only, so a starter template supplies the design.
 * Simple view shows one upload box and one decision (`SimpleResumeImport`); Full view
 * keeps the template wizard with every mapping control open. */
export function ResumeStep({
  nav,
  fromScratch,
  onScratch,
}: {
  nav: StepNav;
  fromScratch: boolean;
  onScratch: () => void;
}) {
  const [pdf, setPdf] = useState(false);
  const { simple } = useUiMode();
  const editor = useEditorState();
  const { info } = useTemplateState();
  const hasContent = !!editor.resume?.sections.some((s) => s.entries.length > 0);
  const complete = fromScratch || !!info?.tagged.exists || hasContent;
  const invalidContact = Object.values(contactErrors(editor.resume?.contact));

  return (
    <StepFrame
      title="Add your resume"
      intro="Upload the resume you already have. ResumeTailor keeps its look and only changes the words."
      nav={nav}
      // A bad contact field never holds this step: nothing here can edit it. The next
      // step shows the field with its error and will not let a bad one through.
      complete={complete}
      onSave={(mode) =>
        editor.resume &&
        (invalidContact.length || (mode === "leave" && completenessErrors(editor.resume).length))
          ? Promise.resolve(true)
          : editor.dirty
            ? editor.save()
            : Promise.resolve(true)
      }
      skipWarning={SKIP_WARNINGS.resume}
      error={editor.dirty ? editor.errors[0] : null}
    >
      {simple ? (
        <SimpleResumeImport />
      ) : (
        <>
          <TemplateImportWizard embedded title="Upload your resume" />
          {pdf ? (
            <ImportResumePanel
              embedded
              title="Import the content of a PDF"
              intro="A PDF can't become your template, but its words can fill your resume. Import them here, then pick a starter template below for the design."
            />
          ) : (
            <p className="text-sm text-ink-muted">
              Only have a PDF?{" "}
              <button type="button" onClick={() => setPdf(true)} className="rt-link font-semibold">
                Import its content
              </button>
              .
            </p>
          )}
        </>
      )}
      <p className="text-sm text-ink-muted">
        No resume yet?{" "}
        <button type="button" onClick={onScratch} className="rt-link font-semibold">
          Start from scratch
        </button>{" "}
        and type your experience in the next step.
      </p>
      <StarterTemplatesPanel embedded />
    </StepFrame>
  );
}
