import { AnalyzeReport } from "./AnalyzeReport";
import { SectionMapStep } from "./SectionMapStep";
import { UploadDropzone } from "./UploadDropzone";
import { useTemplateState } from "../../state/templateState";

/**
 * Multi-step template import: analyze → confirm mapping → install.
 */
export function TemplateImportWizard() {
  const {
    uploading,
    error,
    buildLog,
    lastBuildOk,
    wizardStep,
    draftFile,
    analysis,
    profileDraft,
    beginAnalyze,
    setProfileDraft,
    confirmInstall,
    resetWizard,
    uploadLegacy,
    info,
    calibrateAlso,
    setCalibrateAlso,
    installLabel,
    setInstallLabel,
  } = useTemplateState();

  const canInstall =
    Boolean(draftFile && profileDraft && analysis?.ready && installLabel.trim()) &&
    !uploading &&
    wizardStep === "mapping";

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Replace template</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Upload a single-column Word/Google Docs export. The importer detects
            section headings and field separators, then you confirm before it rebuilds
            the tagged template. Experience is required; Education, Projects, and Skills
            can be omitted when absent.
          </p>
        </div>
        {wizardStep !== "idle" ? (
          <button
            type="button"
            onClick={() => resetWizard()}
            disabled={uploading}
            className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
          >
            Start over
          </button>
        ) : null}
      </div>

      {wizardStep === "idle" || wizardStep === "error" ? (
        <UploadDropzone
          disabled={uploading}
          onFile={(file) => void beginAnalyze(file)}
          label={
            uploading
              ? "Analyzing…"
              : wizardStep === "error"
                ? "Fix the source and drop a new .docx, or"
                : "Drop a .docx here, or"
          }
        />
      ) : null}

      {wizardStep === "analyzing" ? (
        <p className="mt-4 text-sm text-ink-muted">Analyzing document structure…</p>
      ) : null}

      {(wizardStep === "mapping" || wizardStep === "installing" || wizardStep === "done") &&
      analysis ? (
        <>
          <p className="mt-4 text-sm text-ink-muted">
            File: <span className="font-medium text-ink">{draftFile?.name}</span>
          </p>
          <AnalyzeReport analysis={analysis} />
          {profileDraft ? (
            <SectionMapStep
              analysis={analysis}
              profile={profileDraft}
              onChange={setProfileDraft}
            />
          ) : (
            <p className="mt-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              No suggested mapping. Use the legacy install only if this is the original
              all-caps EDUCATION / WORK EXPERIENCES / PROJECTS / SKILLS layout.
            </p>
          )}
          <label className="mt-4 block text-sm">
            <span className="font-medium text-ink">Save as</span>
            <span className="ml-1 text-xs text-ink-muted">
              (library label; must be unique)
            </span>
            <input
              type="text"
              value={installLabel}
              maxLength={80}
              disabled={uploading}
              onChange={(e) => setInstallLabel(e.target.value)}
              className="mt-1 w-full max-w-md rounded-md border border-line bg-paper px-3 py-2 text-ink"
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
                Runs build + measure (Word/LibreOffice) so page packing matches the new
                template. Slower; constants reload without restarting the server.
              </span>
            </span>
          </label>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!canInstall}
              onClick={() => void confirmInstall()}
              className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
            >
              {wizardStep === "installing"
                ? calibrateAlso
                  ? "Installing & calibrating…"
                  : "Installing…"
                : calibrateAlso
                  ? "Confirm, install & calibrate"
                  : "Confirm & install"}
            </button>
            <button
              type="button"
              disabled={uploading || !draftFile}
              onClick={() => draftFile && void uploadLegacy(draftFile)}
              className="rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
              title="Exact all-caps headings only; clears any prior profile"
            >
              Legacy install (no mapping)
            </button>
          </div>
        </>
      ) : null}

      {error && (wizardStep === "error" || lastBuildOk === false) ? (
        <p className="mt-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {error.split("\n")[0]}
        </p>
      ) : null}

      {lastBuildOk === true && wizardStep === "done" ? (
        <p className="mt-4 rounded-md bg-accent-soft px-3 py-2 text-sm text-accent">
          Template rebuilt successfully.
          {info?.calibration.stale
            ? " Fit constants may still be stale — enable calibrate on the next install, or run calibrate.py."
            : calibrateAlso
              ? " Fit constants were recalibrated for this template."
              : null}
        </p>
      ) : null}

      {buildLog ? (
        <pre className="mt-4 max-h-48 overflow-auto rounded-md border border-line bg-paper/60 p-3 text-xs text-ink whitespace-pre-wrap">
          {buildLog}
        </pre>
      ) : null}
    </section>
  );
}
