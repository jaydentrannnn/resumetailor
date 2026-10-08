import { RunCostEstimate } from "../../components/RunCostEstimate";
import { RunHistoryPanel } from "../../components/RunHistoryPanel";
import { buttonClass, Page, PageHeader } from "../../components/ui";
import { useRunState } from "../../state/runState";
import { useWorkspaceState } from "../../state/workspaceState";
import { JobInput } from "./JobInput";
import { ProgressPanel } from "./ProgressPanel";
import { RunOptions } from "./RunOptions";
import { RunResults } from "./RunResults";

/**
 * Tailor page: the header, the Options tile, the job description beside "This run",
 * then the last result and the recent runs.
 *
 * State lives in `RunProvider` so leaving the page mid-run keeps the JD, settings,
 * SSE stream and results; PDF auto-download is owned there too. At `lg` the job
 * description and this run sit side by side; below it every tile stacks in source order.
 */
export function RunPage() {
  const {
    config,
    jdText,
    setJdText,
    settings,
    setSettings,
    jobId,
    busy,
    settingsLoaded,
    settingsSaveState,
    settingsSaveError,
    flushSettings,
    startJob,
  } = useRunState();
  const { switching, activeId, activeLabel } = useWorkspaceState();
  const resumeName = activeLabel || config?.contact_name;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    await startJob();
  }

  function onFormKeyDown(e: React.KeyboardEvent<HTMLFormElement>) {
    /** Enter in a text/number field must not submit the whole form. Textareas,
     * selects, and buttons are unaffected. */
    if (e.key === "Enter" && (e.target as HTMLElement).tagName === "INPUT") {
      e.preventDefault();
    }
  }

  const saveNotice = settingsLoaded && settingsSaveState !== "saved" && (
    <p
      className={`mb-3 text-xs ${settingsSaveState === "failed" ? "text-danger" : "text-ink-muted"}`}
      role={settingsSaveState === "failed" ? "alert" : "status"}
    >
      {settingsSaveState === "saving"
        ? "Saving options…"
        : settingsSaveState === "unsaved"
          ? "Unsaved options"
          : `Options could not be saved: ${settingsSaveError ?? "Please retry."}`}
      {settingsSaveState === "failed" && (
        <button
          type="button"
          onClick={() => void flushSettings()}
          className="ml-2 font-medium text-ink underline"
        >
          Retry
        </button>
      )}
    </p>
  );

  const submit = (
    <>
      <button
        type="submit"
        data-shortcut="primary"
        disabled={busy || !jdText.trim() || !settingsLoaded || switching}
        className={buttonClass("primary", "lg")}
      >
        {busy
          ? "Tailoring…"
          : switching
            ? "Switching profile…"
            : !settingsLoaded
              ? "Loading settings…"
              : "Tailor resume"}
      </button>
      <div className="ml-auto">
        <RunCostEstimate
          jdText={jdText}
          settings={settings}
          enabled={settingsLoaded && !busy && !switching}
        />
      </div>
    </>
  );

  return (
    <Page width="wide">
      <PageHeader
        eyebrow={resumeName ? `Resume: ${resumeName}` : undefined}
        title="Tailor resume"
        description="Paste a job posting. Your bullets are rewritten to match it, and the document keeps its original layout."
      />
      <form onSubmit={onSubmit} onKeyDown={onFormKeyDown} className="space-y-4">
        <RunOptions
          config={config}
          settings={settings}
          onChange={setSettings}
          disabled={!settingsLoaded}
          workspaceId={activeId ?? "default"}
          saveNotice={saveNotice}
        />

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <JobInput jdText={jdText} setJdText={setJdText} disabled={busy} footer={submit} />
          <ProgressPanel />
        </div>

        {jobId && <RunResults jobId={jobId} />}

        <RunHistoryPanel />
      </form>
    </Page>
  );
}
