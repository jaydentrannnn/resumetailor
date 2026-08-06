import { useState } from "react";

import { AnalyzeReport } from "./AnalyzeReport";
import { PreviewCompare } from "./PreviewCompare";
import { SectionMapStep } from "./SectionMapStep";
import { UploadDropzone } from "./UploadDropzone";
import { importMasterResumeContent } from "../../api";
import type { MasterResume } from "../../lib/resumeEdit";
import { useEditorState } from "../../state/editorState";
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
    headingOverrides,
    remapBusy,
    remapHeading,
    beginAnalyze,
    setProfileDraft,
    confirmInstall,
    resetWizard,
    info,
    calibrateAlso,
    setCalibrateAlso,
    installLabel,
    setInstallLabel,
  } = useTemplateState();
  const { loadDraft } = useEditorState();

  // Content import is a separate action from the template install (it hits a
  // different endpoint and writes nothing), but the wizard offers it as "one upload
  // does both" — checked here, run right after a successful install below.
  const [alsoImportContent, setAlsoImportContent] = useState(false);
  const [suggestTags, setSuggestTags] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importOutcome, setImportOutcome] = useState<
    { warnings: string[]; untagged: number } | { error: string } | null
  >(null);

  const canInstall =
    Boolean(draftFile && profileDraft && analysis?.ready && installLabel.trim()) &&
    !uploading &&
    !remapBusy &&
    wizardStep === "mapping";

  const runInstall = async () => {
    setImportOutcome(null);
    const installed = await confirmInstall();
    if (!installed || !alsoImportContent || !draftFile) return;
    setImportBusy(true);
    try {
      const result = await importMasterResumeContent(draftFile, { suggestTags });
      loadDraft(
        result.resume as MasterResume,
        "Imported from the template upload — review on the Master Resume tab and save to keep it.",
      );
      setImportOutcome({ warnings: result.warnings, untagged: result.untagged_bullet_count });
    } catch (err) {
      setImportOutcome({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      setImportBusy(false);
    }
  };

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
            <>
              <SectionMapStep
                analysis={analysis}
                profile={profileDraft}
                onChange={setProfileDraft}
                headingOverrides={headingOverrides}
                remapBusy={remapBusy}
                onRemapHeading={(paragraphId, kind) =>
                  void remapHeading(paragraphId, kind)
                }
              />
              <PreviewCompare sourceSha256={analysis.source_sha256} profile={profileDraft} />
            </>
          ) : (
            <p className="mt-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              No suggested mapping — see the issues above for what the analyzer could
              not map, fix the source document, and upload again.
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
                Also import content from this file
              </span>
              <span className="block text-xs text-ink-muted">
                Parses bullets, dates, and contact info into a Master Resume draft —
                loaded as unsaved state on the Master Resume tab for you to review and
                save. Writes nothing on its own.
              </span>
            </span>
          </label>
          {alsoImportContent ? (
            <label className="mt-2 ml-6 flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={suggestTags}
                disabled={uploading || importBusy}
                onChange={(e) => setSuggestTags(e.target.checked)}
              />
              <span>
                <span className="font-medium text-ink">Suggest tags for untagged bullets</span>
                <span className="block text-xs text-ink-muted">
                  Uses an LLM call to propose tags for bullets the deterministic import
                  could not match on its own. Never blocks the import if it fails.
                </span>
              </span>
            </label>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!canInstall || importBusy}
              onClick={() => void runInstall()}
              className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
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
          {importOutcome && "error" in importOutcome ? (
            <p className="mt-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              Content import failed: {importOutcome.error}
            </p>
          ) : null}
          {importOutcome && "warnings" in importOutcome ? (
            <div className="mt-4 rounded-md bg-accent-soft px-3 py-2 text-sm text-accent">
              <p>
                Content imported — open the Master Resume tab to review and save it.
                {importOutcome.untagged > 0
                  ? ` ${importOutcome.untagged} bullet(s) need a tag.`
                  : null}
              </p>
              {importOutcome.warnings.length > 0 ? (
                <ul className="mt-1 list-disc pl-5 text-xs text-ink-muted">
                  {importOutcome.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
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
