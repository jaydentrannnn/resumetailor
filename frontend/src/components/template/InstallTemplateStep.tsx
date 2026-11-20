import { buttonClass } from "../../lib/buttonClass";
import type { useTemplateState } from "../../state/templateState";
type TemplateState = ReturnType<typeof useTemplateState>;
export function InstallTemplateStep({
  state,
  alsoImportContent,
  setAlsoImportContent,
  importBusy,
  canInstall,
  runInstall,
}: {
  state: TemplateState;
  alsoImportContent: boolean;
  setAlsoImportContent: (value: boolean) => void;
  importBusy: boolean;
  canInstall: boolean;
  runInstall: () => Promise<void>;
}) {
  const { uploading, calibrateAlso, setCalibrateAlso, installLabel, setInstallLabel, wizardStep } =
    state;
  return (
    <div className="mt-5 border-t border-line pt-4">
      {" "}
      <label className="mt-4 block text-sm">
        <span className="font-medium text-ink">Name</span>
        <span className="ml-1 text-xs text-ink-muted">(shown in your saved templates)</span>
        <input
          type="text"
          value={installLabel}
          maxLength={80}
          disabled={uploading}
          onChange={(e) => setInstallLabel(e.target.value)}
          className="field mt-1 max-w-md"
          placeholder="e.g. Google Docs export"
        />
      </label>
      <label className="mt-4 flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={calibrateAlso}
          disabled={uploading}
          onChange={(e) => setCalibrateAlso(e.target.checked)}
        />
        <span>
          <span className="font-medium text-ink">Also tune page fit</span>
          <span className="block text-xs text-ink-muted">
            Measures how much fits on a page in this template, so tailored resumes fill the page.
            Takes about 30 seconds.
          </span>
        </span>
      </label>
      {!state.fromLayout && (
        <label className="mt-2 flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={alsoImportContent}
            disabled={uploading || importBusy}
            onChange={(e) => setAlsoImportContent(e.target.checked)}
          />
          <span>
            <span className="font-medium text-ink">
              Also bring this file's words into your resume
            </span>
            <span className="block text-xs text-ink-muted">
              Entries that match by company, school or project name are updated, new ones are added,
              and the rest of your resume stays as it is. The current resume is backed up first.
            </span>
          </span>
        </label>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!canInstall || importBusy}
          onClick={() => void runInstall()}
          className={buttonClass("primary", "sm")}
        >
          {wizardStep === "installing"
            ? calibrateAlso
              ? "Installing and tuning page fit…"
              : "Installing…"
            : importBusy
              ? "Bringing in the words…"
              : calibrateAlso
                ? "Install and tune page fit"
                : "Install"}
        </button>
      </div>
    </div>
  );
}
