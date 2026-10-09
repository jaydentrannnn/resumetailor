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
        <span className="font-medium text-ink">Save as</span>
        <span className="ml-1 text-xs text-ink-muted">(library label; must be unique)</span>
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
          <span className="font-medium text-ink">Also calibrate fit constants</span>
          <span className="block text-xs text-ink-muted">
            Runs build + measure (Word/LibreOffice) so page packing matches the new template.
            Slower; constants reload without restarting the server.
          </span>
        </span>
      </label>
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
            Also merge this file's content into the master resume
          </span>
          <span className="block text-xs text-ink-muted">
            Matches entries by company/school/project name: matching entries are updated (their
            bullets refreshed), new ones are added, and everything else in your master resume is
            left as-is. Backs up the current file first, and asks for confirmation before writing.
          </span>
        </span>
      </label>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!canInstall || importBusy}
          onClick={() => void runInstall()}
          className={buttonClass("primary", "sm")}
        >
          {wizardStep === "installing"
            ? calibrateAlso
              ? "Installing & calibrating…"
              : "Installing…"
            : importBusy
              ? "Importing content…"
              : calibrateAlso
                ? "Confirm, install & calibrate"
                : "Confirm & install"}
        </button>
      </div>
    </div>
  );
}
