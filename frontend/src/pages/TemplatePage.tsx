import { Page, PageHeader } from "../components/ui";
import { PageFitCard } from "../components/template/PageFitCard";
import { SavedTemplatesPanel } from "../components/template/SavedTemplatesPanel";
import { StarterTemplatesPanel } from "../components/template/StarterTemplatesPanel";
import { TemplateImportWizard } from "../components/template/TemplateImportWizard";
import { TemplateWorkspace } from "../components/template/workspace/TemplateWorkspace";
import { WIZARD_ANCHOR } from "../lib/useLayoutEditSession";
import { useTemplateState } from "../state/templateState";

/**
 * Template tab: the current template (resume or cover letter) with its tools, then the
 * template library and the importer. Saved and starter templates stay below the views
 * because a template switch changes both documents.
 */
export function TemplatePage() {
  const { info } = useTemplateState();
  return (
    <Page>
      <PageHeader
        title="Template"
        description="The Word document every tailored resume is poured into. Only the words change; the look stays yours."
      />
      <TemplateWorkspace />
      {info?.tagged.exists && <PageFitCard calibration={info.calibration} />}
      <SavedTemplatesPanel />
      <StarterTemplatesPanel />
      <div id={WIZARD_ANCHOR} className="scroll-mt-4">
        <TemplateImportWizard />
      </div>
    </Page>
  );
}
