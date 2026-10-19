import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DocumentsCard } from "../../components/DocumentsCard";
import { Modal } from "../../components/Modal";
import { RunCostEstimate } from "../../components/RunCostEstimate";
import { RunHistoryPanel } from "../../components/RunHistoryPanel";
import { Tabs } from "../../components/Tabs";
import { Button, CommandBar, EmptyState, Page } from "../../components/ui";
import { VIEWER_HEIGHT } from "../../lib/viewer";
import { useCommands } from "../../state/commandState";
import { useRunState } from "../../state/runState";
import { useWorkspaceState } from "../../state/workspaceState";
import { JobInput } from "./JobInput";
import { ProgressPanel } from "./ProgressPanel";
import { RunOptions } from "./RunOptions";
import { type ResultPane, RunResults, runMeta } from "./RunResults";
import { RunSaveNotice } from "./RunSaveNotice";

type Pane = "job" | ResultPane;

const PANES: { id: Pane; label: string; command: string }[] = [
  { id: "job", label: "Job", command: "Edit the job" },
  { id: "report", label: "Report", command: "Show the report" },
  { id: "bullets", label: "Review bullets", command: "Review bullets" },
  { id: "content", label: "Application content", command: "Show application content" },
];

/**
 * Tailor: the job and options (or, after a run, its report, bullet review and
 * application content) on the left; the tailored documents on the right, or the run's
 * progress while it works. Below `lg` the panes stack.
 *
 * State lives in `RunProvider`, so leaving the page mid-run keeps the JD, settings,
 * stream and results. The left pane lives in the URL (`pane`).
 */
export function RunPage() {
  const run = useRunState();
  const { config, jdText, setJdText, settings, setSettings, jobId, status, busy } = run;
  const { switching, activeId } = useWorkspaceState();
  const [params, setParams] = useSearchParams();
  const [docsRevision, setDocsRevision] = useState(0);
  const [coverRevision, setCoverRevision] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const requested = params.get("pane");
  const pane: Pane = jobId && PANES.some((p) => p.id === requested) ? (requested as Pane) : "job";
  const setPane = (next: string) =>
    setParams(
      (previous) => {
        const query = new URLSearchParams(previous);
        query.set("pane", next);
        return query;
      },
      { replace: true },
    );

  // Opening a run from History shows it; the drawer has done its job.
  useEffect(() => setHistoryOpen(false), [jobId]);

  const ready = run.settingsLoaded && !switching;
  const entry = run.history?.find((item) => item.job_id === jobId);
  const showProgress = busy || status === "failed" || status === "cancelled";
  const canTailor = !busy && Boolean(jdText.trim()) && ready;
  useCommands(() => [
    {
      id: "tailor-run",
      title: jobId ? "Tailor again" : "Tailor resume",
      group: "Tailor",
      keywords: "run start",
      shortcut: ["Ctrl", "Enter"],
      disabled: !canTailor,
      run: () => void run.startJob(),
    },
    {
      id: "tailor-history",
      title: "Run history",
      group: "Tailor",
      keywords: "past runs",
      run: () => setHistoryOpen(true),
    },
    ...PANES.map((item) => ({
      id: `tailor-pane-${item.id}`,
      title: item.command,
      group: "Tailor",
      disabled: !jobId || pane === item.id,
      run: () => setPane(item.id),
    })),
  ]);

  return (
    <Page width="wide">
      <CommandBar
        title="Tailor"
        state={jobId ? runMeta(entry, run.report?.title) : null}
        actions={
          <>
            <Button variant="plain" size="sm" onClick={() => setHistoryOpen(true)}>
              History
            </Button>
            <Button
              variant="primary"
              size="sm"
              data-shortcut="primary"
              disabled={!canTailor}
              onClick={() => void run.startJob()}
            >
              {busy
                ? "Tailoring…"
                : switching
                  ? "Switching profile…"
                  : !run.settingsLoaded
                    ? "Loading settings…"
                    : "Tailor resume"}
            </Button>
          </>
        }
      />
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(22rem,30rem)_minmax(0,1fr)]">
        <section aria-label="Job and results" className="min-w-0 space-y-4">
          {jobId && (
            <Tabs
              label="Tailor"
              variant="segmented"
              items={PANES}
              value={pane}
              onChange={setPane}
            />
          )}
          {pane === "job" || !jobId ? (
            <>
              <JobInput
                jdText={jdText}
                setJdText={setJdText}
                disabled={busy}
                footer={
                  <RunCostEstimate jdText={jdText} settings={settings} enabled={ready && !busy} />
                }
              />
              <RunOptions
                config={config}
                settings={settings}
                onChange={setSettings}
                disabled={!run.settingsLoaded}
                workspaceId={activeId ?? "default"}
                saveNotice={<RunSaveNotice />}
              />
            </>
          ) : (
            <div role="tabpanel" className="rounded-sm border border-line bg-panel p-5">
              <RunResults
                jobId={jobId}
                pane={pane}
                onResumeChanged={() => setDocsRevision((n) => n + 1)}
                onCoverChanged={() => setCoverRevision((n) => n + 1)}
              />
            </div>
          )}
        </section>
        <section
          aria-label="Document"
          className="min-w-0 lg:sticky lg:top-[calc(var(--rt-bar-top)+1.25rem)]"
        >
          {showProgress ? (
            <ProgressPanel />
          ) : jobId ? (
            <DocumentsCard
              jobId={jobId}
              revision={docsRevision}
              coverRevision={coverRevision}
              coverLetter={run.coverLetter}
              onCoverRegenerated={run.setCoverLetter}
              coverDetails={false}
              viewerClassName={VIEWER_HEIGHT}
            />
          ) : (
            <div className="rounded-sm border border-line bg-panel">
              <EmptyState title="Your tailored resume shows here">
                Paste a job posting on the left and press Tailor resume (Ctrl+Enter).
              </EmptyState>
            </div>
          )}
        </section>
      </div>
      {historyOpen && (
        <Modal
          title="Run history"
          placement="right"
          size="lg"
          onClose={() => setHistoryOpen(false)}
        >
          <RunHistoryPanel />
        </Modal>
      )}
    </Page>
  );
}
