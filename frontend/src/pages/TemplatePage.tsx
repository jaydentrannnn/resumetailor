import { Page } from "../components/ui";
import { SavedTemplatesPanel } from "../components/template/SavedTemplatesPanel";
import { StarterTemplatesPanel } from "../components/template/StarterTemplatesPanel";
import { TemplateImportWizard } from "../components/template/TemplateImportWizard";
import { TemplateWorkspace } from "../components/template/workspace/TemplateWorkspace";
import { WIZARD_ANCHOR } from "../lib/useLayoutEditSession";

/**
 * Template tab: the current template (resume or cover letter) beside its tools, then the
 * template library and the importer. Saved and starter templates stay below the views
 * because a template switch changes both documents.
 */
export function TemplatePage() {
  return (
    <Page width="wide" className="space-y-8">
      <TemplateWorkspace />
      <SavedTemplatesPanel />
      <StarterTemplatesPanel />
      <div id={WIZARD_ANCHOR} className="scroll-mt-[calc(var(--rt-bar-top)+1rem)]">
        <TemplateImportWizard />
      </div>
    </Page>
  );
}
