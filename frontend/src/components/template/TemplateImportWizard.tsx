import { buttonClass } from "../../lib/buttonClass";
import { Stepper, Tile } from "../ui";
import { useTemplateState } from "../../state/templateState";
import { useTemplateContentImport } from "./useTemplateContentImport";
import { UploadTemplateStep } from "./UploadTemplateStep";
import { MapTemplateStep } from "./MapTemplateStep";
import { InstallTemplateStep } from "./InstallTemplateStep";
import { InstalledTemplateStep } from "./InstalledTemplateStep";
import { TemplateContentResult } from "./TemplateContentResult";

/** Analyze → map → install, using the same template state transitions. */
export function TemplateImportWizard({
  title = "Replace template",
  embedded = false,
}: {
  title?: string;
  /** Inside the onboarding step tile: no tile of its own, the title becomes an h3. */
  embedded?: boolean;
} = {}) {
  const Title = embedded ? "h3" : "h2";
  const state = useTemplateState();
  const {
    uploading,
    wizardStep,
    draftFile,
    profileDraft,
    analysis,
    installLabel,
    remapBusy,
    confirmInstall,
    resetWizard,
  } = state;
  const {
    alsoImportContent,
    setAlsoImportContent,
    importBusy,
    importOutcome,
    setImportOutcome,
    importContent,
  } = useTemplateContentImport();
  const canInstall =
    Boolean(draftFile && profileDraft && analysis?.ready && installLabel.trim()) &&
    !uploading &&
    !remapBusy &&
    wizardStep === "mapping";

  const runInstall = async () => {
    setImportOutcome(null);
    const installed = await confirmInstall();
    if (!installed || !alsoImportContent || !draftFile) return;
    await importContent(draftFile);
  };

  return (
    <Tile embedded={embedded}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Title className="rt-tile-title">{title}</Title>
          <p className="mt-1 text-sm text-ink-muted">
            Upload a single-column Word/Google Docs export. The importer detects section headings
            and field separators, then you confirm before it rebuilds the tagged template. Any
            section can be left out, as long as there is at least one of Experience, Projects or
            another list of entries.
          </p>
        </div>
        {wizardStep !== "idle" ? (
          <button
            type="button"
            onClick={() => resetWizard()}
            disabled={uploading}
            className={buttonClass("secondary", "sm")}
          >
            Start over
          </button>
        ) : null}
      </div>
      <div className="mt-5">
        <Stepper
          label="Template import steps"
          steps={[
            { id: "upload", label: "Upload" },
            { id: "map", label: "Map sections" },
            { id: "install", label: "Install" },
          ]}
          current={
            wizardStep === "done"
              ? 3
              : wizardStep === "installing"
                ? 2
                : wizardStep === "mapping"
                  ? 1
                  : 0
          }
          failed={wizardStep === "error" ? 0 : undefined}
        />
      </div>

      <UploadTemplateStep state={state} />
      {(wizardStep === "mapping" || wizardStep === "installing" || wizardStep === "done") &&
        analysis && (
          <>
            <MapTemplateStep state={state} importBusy={importBusy} importContent={importContent} />
            <InstallTemplateStep
              state={state}
              alsoImportContent={alsoImportContent}
              setAlsoImportContent={setAlsoImportContent}
              importBusy={importBusy}
              canInstall={canInstall}
              runInstall={runInstall}
            />
            <TemplateContentResult importOutcome={importOutcome} />
          </>
        )}
      <InstalledTemplateStep state={state} />
    </Tile>
  );
}
