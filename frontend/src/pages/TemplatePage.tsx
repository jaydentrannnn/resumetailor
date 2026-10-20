import { CommandBar, Page } from "../components/ui";
import { PageFitCard } from "../components/template/PageFitCard";
import { SavedTemplatesPanel } from "../components/template/SavedTemplatesPanel";
import { StarterTemplatesPanel } from "../components/template/StarterTemplatesPanel";
import { TemplateImportWizard } from "../components/template/TemplateImportWizard";
import { TemplateWorkspace } from "../components/template/workspace/TemplateWorkspace";
import { WIZARD_ANCHOR } from "../lib/useLayoutEditSession";
import { useTemplateState } from "../state/templateState";

/**
 * Template tab: the current template (resume or cover letter) with its tools in one
 * tile, then page fit, the template library and the importer. Saved and starter
 * templates stay below the views because a template switch changes both documents.
 */
export function TemplatePage() {
  const { info, pendingTemplate } = useTemplateState();
  const installed = !!info?.tagged.exists;
  return (
    <Page>
      <CommandBar
        title="Template"
        state={
          installed
            ? pendingTemplate
              ? `Switching to ${pendingTemplate}…`
              : info?.active_label
            : null
        }
      />
      <TemplateWorkspace />
      {installed && info && <PageFitCard calibration={info.calibration} />}
      <SavedTemplatesPanel />
      <StarterTemplatesPanel />
      <div id={WIZARD_ANCHOR} className="scroll-mt-[calc(var(--rt-bar-top)+1rem)]">
        <TemplateImportWizard />
      </div>
    </Page>
  );
}
