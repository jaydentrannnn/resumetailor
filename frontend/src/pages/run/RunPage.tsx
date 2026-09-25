import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DocumentsCard } from "../../components/DocumentsCard";
import { ExperienceCard } from "../../components/ExperienceCard";
import { RunCostEstimate } from "../../components/RunCostEstimate";
import { RunHistoryPanel } from "../../components/RunHistoryPanel";
import { SkillsCard } from "../../components/SkillsCard";
import { Tabs } from "../../components/Tabs";
import { useRunState } from "../../state/runState";
import { useWorkspaceState } from "../../state/workspaceState";
import { BulletReview } from "./BulletReview";
import { JobInput } from "./JobInput";
import { ProgressPanel } from "./ProgressPanel";
import { ReportCard } from "./ReportCard";
import { RunOptions } from "./RunOptions";

/**
 * Tailor page: options, the job description, progress, then results and history.
 *
 * State lives in `RunProvider` so leaving the page mid-run keeps the JD, settings,
 * SSE stream and results; PDF auto-download is owned there too.
 *
 * At `lg` the grid places Options on row 1 (set once, then left alone), the job
 * description and its Progress on row 2, and the submit button across both columns
 * on row 3. Placement is stated per tile because several render conditionally and
 * auto-flow would reshuffle the rest when one disappears. Mobile collapses to one
 * column in source order.
 */
export function RunPage() {
  const {
    config,
    jdText,
    setJdText,
    settings,
    setSettings,
    jobId,
    report,
    expansion,
    skills,
    coverLetter,
    setCoverLetter,
    busy,
    settingsLoaded,
    settingsSaveState,
    settingsSaveError,
    flushSettings,
    startJob,
  } = useRunState();
  const { switching, activeId } = useWorkspaceState();
  const [resultParams, setResultParams] = useSearchParams();
  // Bumped after a re-render so the documents preview reloads the new PDF.
  const [docsRevision, setDocsRevision] = useState(0);
  const resultTab = ["overview", "bullets", "documents", "content"].includes(
    resultParams.get("result_tab") ?? "",
  )
    ? resultParams.get("result_tab")!
    : "overview";
  const setResultTab = (tab: string) =>
    setResultParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set("result_tab", tab);
        return next;
      },
      { replace: true },
    );

  // `setSearchParams` changes identity on every URL change, so this keys on an actual
  // jobId change — otherwise each tab click re-ran it and deleted the tab just set.
  const resetForJob = useRef(jobId);
  useEffect(() => {
    if (!jobId || resetForJob.current === jobId) return;
    resetForJob.current = jobId;
    setResultParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete("result_tab");
        return next;
      },
      { replace: true },
    );
  }, [jobId, setResultParams]);

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
      className={`mt-2 text-xs ${settingsSaveState === "failed" ? "text-danger" : "text-ink-muted"}`}
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
          className="ml-2 font-medium text-accent underline"
        >
          Retry
        </button>
      )}
    </p>
  );

  return (
    <form
      onSubmit={onSubmit}
      onKeyDown={onFormKeyDown}
      className="grid grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-[1.1fr_0.9fr]"
    >
      <h1 className="sr-only">Tailor resume</h1>

      <RunOptions
        config={config}
        settings={settings}
        onChange={setSettings}
        disabled={!settingsLoaded}
        workspaceId={activeId ?? "default"}
        saveNotice={saveNotice}
      />

      <JobInput jdText={jdText} setJdText={setJdText} disabled={busy} />

      {/* Absolutely positioned at `lg` so row 2 is sized by the job description alone
          and progress stretches to exactly its height; static on mobile. */}
      <div className="lg:relative lg:col-start-2 lg:row-start-2">
        <ProgressPanel />
      </div>

      <div className="lg:col-start-1 lg:col-span-2 lg:row-start-3">
        <button
          type="submit"
          data-shortcut="primary"
          disabled={busy || !jdText.trim() || !settingsLoaded || switching}
          className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-on-accent transition-[filter] duration-[var(--dur-short)] ease-out hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy
            ? "Tailoring…"
            : switching
              ? "Switching profile…"
              : !settingsLoaded
                ? "Loading settings…"
                : "Tailor resume"}
        </button>
        <RunCostEstimate
          jdText={jdText}
          settings={settings}
          enabled={settingsLoaded && !busy && !switching}
        />
      </div>

      {jobId && (
        <section id="tailored-results" className="space-y-4 lg:col-span-2 lg:row-start-4">
          <h2 className="text-lg font-semibold">Tailored results</h2>
          <Tabs
            label="Tailored results"
            items={[
              { id: "overview", label: "Overview" },
              { id: "bullets", label: "Review bullets" },
              { id: "documents", label: "Documents" },
              { id: "content", label: "Application content" },
            ]}
            value={resultTab}
            onChange={setResultTab}
          />
          {resultTab === "overview" && (
            <div role="tabpanel">
              {report ? (
                <ReportCard report={report} />
              ) : (
                <p className="rounded-lg border border-line bg-panel p-5 text-sm text-ink-muted">
                  A report has not been saved for this run.
                </p>
              )}
            </div>
          )}
          {resultTab === "bullets" && (
            <div role="tabpanel">
              <BulletReview jobId={jobId} onSaved={() => setDocsRevision((n) => n + 1)} />
            </div>
          )}
          {resultTab === "documents" && (
            <div role="tabpanel">
              <DocumentsCard
                revision={docsRevision}
                jobId={jobId}
                coverLetter={coverLetter}
                onCoverRegenerated={setCoverLetter}
              />
            </div>
          )}
          {resultTab === "content" && (
            <div role="tabpanel" className="space-y-4">
              {skills && <SkillsCard plan={skills} gaps={report?.gaps ?? []} jobId={jobId} />}
              {expansion && <ExperienceCard expansion={expansion} jobId={jobId} />}
              {!skills && !expansion && (
                <p className="rounded-lg border border-line bg-panel p-5 text-sm text-ink-muted">
                  No skills or experience expansion was saved for this run.
                </p>
              )}
            </div>
          )}
        </section>
      )}

      <RunHistoryPanel />
    </form>
  );
}
