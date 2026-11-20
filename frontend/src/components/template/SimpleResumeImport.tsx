import { useEffect, useRef, useState } from "react";
import { buttonClass } from "../../lib/buttonClass";
import { entryCount, resumeTotals } from "../../lib/readSummary";
import { isPdf } from "../../lib/uploadKinds";
import { useEditorState } from "../../state/editorState";
import { useTemplateState } from "../../state/templateState";
import { StatusMark, Tile } from "../ui";
import { InstallTemplateStep } from "./InstallTemplateStep";
import { MapTemplateStep } from "./MapTemplateStep";
import { SimpleImportReview } from "./SimpleImportReview";
import { UploadDropzone } from "./UploadDropzone";
import { useTemplateContentImport } from "./useTemplateContentImport";

/**
 * First-run upload: one box for a Word file or a PDF, what was read, and one button.
 * A Word file becomes the template and its words the resume in one step; a PDF, or a
 * layout that can't be a template, gives its words on a built-in design. The name, the
 * page-fit measurement and the content import are not choices here. The full wizard's
 * mapping controls (`MapTemplateStep`, `InstallTemplateStep`) open under "Something's
 * off"; the Template page keeps `TemplateImportWizard` as it is.
 */
export function SimpleResumeImport() {
  const state = useTemplateState();
  const editor = useEditorState();
  // What the template state holds now, for steps that run after an awaited request:
  // the starter list can arrive, and a template be installed, while a file is read.
  const latest = useRef(state);
  useEffect(() => {
    latest.current = state;
  });
  const content = useTemplateContentImport({ defaultOn: true });
  // The file whose words to bring in again after a failed attempt, without uploading
  // again; `wordsOnly` repeats the PDF / words-only path (a starter design if none is set).
  const [retry, setRetry] = useState<{ file: File; wordsOnly: boolean } | null>(null);
  const [adjust, setAdjust] = useState(false);
  /** A words-only import finished: the design it was put on (null = one was already set). */
  const [wordsDone, setWordsDone] = useState<{ design: string | null } | null>(null);
  const { wizardStep, analysis, profileDraft, draftFile, uploading, error } = state;
  const busy = uploading || content.importBusy || state.libraryBusy || state.remapBusy;
  const ready = Boolean(analysis?.ready && profileDraft);
  const reviewing = wizardStep === "mapping" && !!analysis && !!draftFile;
  const entries = entryCount(editor.resume);
  const totals = resumeTotals(editor.resume);

  /** The words without the file's layout: a PDF, or a layout that can't be a template. */
  async function importWordsOnly(file: File) {
    setWordsDone(null);
    setRetry({ file, wordsOnly: true });
    const outcome = await content.importContent(file);
    if (!outcome || outcome.kind === "error") return;
    let design: string | null = null;
    const now = latest.current;
    const starter = now.defaults[0];
    if (!now.info?.tagged.exists && starter && (await now.installDefault(starter.name)))
      design = starter.label;
    now.resetWizard();
    setWordsDone({ design });
  }

  function start(file: File) {
    setAdjust(false);
    setWordsDone(null);
    setRetry(null);
    content.setImportOutcome(null);
    if (isPdf(file)) void importWordsOnly(file);
    else void state.beginAnalyze(file);
  }

  async function install() {
    content.setImportOutcome(null);
    const installed = await state.confirmInstall();
    if (installed && draftFile && content.alsoImportContent) {
      // The design is saved now; only the words need bringing in again.
      setRetry({ file: draftFile, wordsOnly: false });
      await content.importContent(draftFile);
    }
  }

  function tryAgain() {
    if (!retry) return;
    if (retry.wordsOnly) void importWordsOnly(retry.file);
    else void content.importContent(retry.file);
  }

  function uploadAnother() {
    content.setImportOutcome(null);
    setWordsDone(null);
    setRetry(null);
    state.resetWizard();
  }

  const done = wizardStep === "done" && state.lastBuildOk === true;
  const waiting = wizardStep === "analyzing" || wizardStep === "installing" || content.importBusy;
  const outcome = content.importOutcome;
  return (
    <Tile embedded aria-label="Upload your resume">
      <p className="text-sm text-ink-muted">
        A Word file keeps your resume's exact look (in Google Docs: File › Download › Microsoft
        Word). A PDF works too: the app takes its words and you pick a look.
      </p>

      {done && !content.importBusy && outcome?.kind !== "error" && (
        <p className="mt-4 flex items-center gap-2 text-sm text-ink">
          <StatusMark tone="done" />
          Your resume is ready: its design is saved
          {outcome?.kind === "merged" && totals ? ` and ${totals} were read` : ""}. Press Next to
          check what was read.
        </p>
      )}
      {wordsDone && (
        <p className="mt-4 flex items-center gap-2 text-sm text-ink">
          <StatusMark tone="done" />
          <span>
            {`Your resume's words are in${wordsDone.design ? `, on the ${wordsDone.design} design` : ""}. `}
            {state.info?.tagged.exists
              ? "Pick another design below if you like, then press Next."
              : "Pick a design below, then press Next."}
          </span>
        </p>
      )}
      {(wizardStep === "idle" || wizardStep === "error") && !content.importBusy && (
        <>
          {entries > 0 && !wordsDone && wizardStep === "idle" && (
            <p className="mt-4 flex items-center gap-2 text-sm text-ink">
              <StatusMark tone="done" />
              Your resume is in{totals ? `: ${totals}` : ""}. Press Next, or upload another file to
              add to it.
            </p>
          )}
          <UploadDropzone
            allowPdf
            disabled={busy}
            onFile={start}
            label={
              wizardStep === "error"
                ? "Fix the file and drop it again, or"
                : "Drop your resume here (Word or PDF), or"
            }
          />
        </>
      )}
      {error && wizardStep === "error" && (
        <p className="mt-3 text-sm text-danger">{error.split("\n")[0]}</p>
      )}

      {waiting && (
        <p className="mt-4 text-sm text-ink-muted" role="status">
          {wizardStep === "installing"
            ? "Setting up your resume. The app is measuring how much fits on your page, which takes about 30 seconds."
            : wizardStep === "analyzing"
              ? "Reading your resume…"
              : "Bringing in your resume's words…"}
        </p>
      )}

      {reviewing && !adjust && !content.importBusy && (
        <SimpleImportReview
          fileName={draftFile.name}
          analysis={analysis}
          ready={ready}
          busy={busy}
          onInstall={() => void install()}
          onWordsOnly={() => void importWordsOnly(draftFile)}
          onAdjust={() => setAdjust(true)}
          onAnother={state.resetWizard}
        />
      )}
      {reviewing && adjust && (
        <>
          <button
            type="button"
            onClick={() => setAdjust(false)}
            className={buttonClass("plain", "sm", "mt-4")}
          >
            Back to the short view
          </button>
          <MapTemplateStep
            state={state}
            importBusy={content.importBusy}
            importContent={importWordsOnly}
          />
          <InstallTemplateStep
            state={state}
            alsoImportContent={content.alsoImportContent}
            setAlsoImportContent={content.setAlsoImportContent}
            importBusy={content.importBusy}
            canInstall={ready && !!state.installLabel.trim() && !busy}
            runInstall={install}
          />
        </>
      )}

      {outcome?.kind === "draft" && (
        <p className="mt-4 border-t border-line pt-4 text-sm text-ink">
          The words are loaded but not saved yet. Press Next to check and save them.
        </p>
      )}
      {outcome?.kind === "error" && (
        <div className="mt-4 border-t border-line pt-4 text-sm">
          <p className="text-danger">The words could not be read: {outcome.error}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {retry && (
              <button
                type="button"
                onClick={tryAgain}
                disabled={busy}
                className={buttonClass("primary", "sm")}
              >
                Try again
              </button>
            )}
            {wizardStep !== "idle" && wizardStep !== "error" && (
              <button
                type="button"
                onClick={uploadAnother}
                disabled={busy}
                className={buttonClass("plain", "sm")}
              >
                Upload another file
              </button>
            )}
          </div>
        </div>
      )}
      {error && state.lastBuildOk === false && wizardStep !== "error" && (
        <p className="mt-4 text-sm text-danger">{error.split("\n")[0]}</p>
      )}
    </Tile>
  );
}
