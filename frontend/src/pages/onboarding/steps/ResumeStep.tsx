import { useState } from "react";
import { ImportResumePanel } from "../../../components/ImportResumePanel";
import { TemplateImportWizard } from "../../../components/template/TemplateImportWizard";
import { StarterTemplatesPanel } from "../../../components/template/StarterTemplatesPanel";
/** Step 3: upload the .docx; its design becomes the template and its words the content.
 * A PDF gives the content only, so a starter template supplies the design. */
export function ResumeStep({ onScratch }: { onScratch: () => void }) {
  const [pdf, setPdf] = useState(false);
  return (
    <div className="space-y-4">
      <TemplateImportWizard title="Upload your resume" />
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
        and add your experience in the editor; you can upload a template later on the Template page.
      </p>
      <StarterTemplatesPanel />
    </div>
  );
}
