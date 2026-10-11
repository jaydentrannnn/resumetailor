import { Page, PageHeader } from "../components/ui";
import { SavedTemplatesPanel } from "../components/template/SavedTemplatesPanel";
import { StarterTemplatesPanel } from "../components/template/StarterTemplatesPanel";
import { TemplateImportWizard } from "../components/template/TemplateImportWizard";
import { TemplateWorkspace } from "../components/template/workspace/TemplateWorkspace";
import { WIZARD_ANCHOR } from "../lib/useLayoutEditSession";

/**
 * Template tab: the current template (resume or cover letter) with its tools, then the
 * template library and the importer. Saved and starter templates stay below the views
 * because a template switch changes both documents.
 */
export function TemplatePage() {
  return (
    <Page>
      <PageHeader
        title="Template"
        description="The Word document every tailored resume is poured into. Only the words change; the look stays yours."
      />
      <TemplateWorkspace />
      <SavedTemplatesPanel />
      <StarterTemplatesPanel />
      <div id={WIZARD_ANCHOR} className="scroll-mt-4">
        <TemplateImportWizard />
      </div>
    </Page>
  );
}
