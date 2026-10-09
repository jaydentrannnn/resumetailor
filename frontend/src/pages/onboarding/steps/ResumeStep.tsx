import { useState } from "react";
import { ImportResumePanel } from "../../../components/ImportResumePanel";
import { TemplateImportWizard } from "../../../components/template/TemplateImportWizard";
import { StarterTemplatesPanel } from "../../../components/template/StarterTemplatesPanel";
import { SKIP_WARNINGS } from "../../../lib/onboarding";
import { useEditorState } from "../../../state/editorState";
import { useTemplateState } from "../../../state/templateState";
import { StepFrame, type StepNav } from "../StepFrame";

/** Step 3: upload the .docx; its design becomes the template and its words the content.
 * A PDF gives the content only, so a starter template supplies the design. */
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
  const editor = useEditorState();
  const { info } = useTemplateState();
  const hasContent = !!editor.resume?.sections.some((s) => s.entries.length > 0);
  const complete = fromScratch || !!info?.tagged.exists || hasContent;

  return (
    <StepFrame
      title="Add your resume"
      intro="Upload your resume as a Word (.docx) file. ResumeTailor keeps its exact look and only changes the words."
      nav={nav}
      complete={complete}
      onSave={() => (editor.dirty ? editor.save() : Promise.resolve(true))}
      skipWarning={SKIP_WARNINGS.resume}
      error={editor.dirty ? editor.errors[0] : null}
    >
      <TemplateImportWizard embedded title="Upload your resume" />
      {pdf ? (
        <ImportResumePanel
          embedded
          title="Import the content of a PDF"
          intro="A PDF can't become your template, but its words can fill your master resume. Import them here, then pick a starter template below for the design."
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
      <p className="text-sm text-ink-muted">
        No Word file?{" "}
        <button type="button" onClick={onScratch} className="rt-link font-semibold">
          Start from scratch
        </button>{" "}
        and add your experience in the Resume content step; you can upload a template later on the
        Template page.
      </p>
      <StarterTemplatesPanel embedded />
    </StepFrame>
  );
}
