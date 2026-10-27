import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DocumentsCard } from "../../components/DocumentsCard";
import { RunCostEstimate } from "../../components/RunCostEstimate";
import { RunHistoryPanel } from "../../components/RunHistoryPanel";
import { Tabs } from "../../components/Tabs";
import { Button, CommandBar, EmptyState, Page, TileLayout } from "../../components/ui";
import { BESIDE_DOCUMENT, VIEWER_HEIGHT } from "../../lib/viewer";
import { useCommands } from "../../state/commandState";
import { useRunState } from "../../state/runState";
import { useWorkspaceState } from "../../state/workspaceState";
import { JobInput } from "./JobInput";
import { ProgressPanel } from "./ProgressPanel";
import { RunOptions } from "./RunOptions";
import { type ResultPane, RunResults, runMeta } from "./RunResults";
import { RunSaveNotice } from "./RunSaveNotice";
import { SendToApply } from "./SendToApply";

type Pane = "job" | ResultPane;
type View = "tailor" | "history";

const VIEWS: { id: View; label: string }[] = [
  { id: "tailor", label: "Tailor" },
  { id: "history", label: "History" },
];

const PANES: { id: Pane; label: string; command: string }[] = [
  { id: "job", label: "Job", command: "Edit the job" },
  { id: "report", label: "Report", command: "Show the report" },
  { id: "bullets", label: "Review bullets", command: "Review bullets" },
  { id: "content", label: "Application content", command: "Show application content" },
];

/**
 * Tailor: the job and options (or, after a run, its report, bullet review and
 * application content) on the left; the tailored documents on the right, one page wide
 * at the window's height, or the run's progress while it works. Tailor resume sits
 * under the posting it reads. History is the page's second view, the whole width for
 * the runs table; opening a run comes back here. Below `lg` the panes stack.
 *
 * State lives in `RunProvider`, so leaving the page mid-run keeps the JD, settings,
 * stream and results. The left pane (`pane`) and the view (`view`) live in the URL.
 */
export function RunPage() {
  const run = useRunState();
  const { jobId, status, busy } = run;
  const [params, setParams] = useSearchParams();
  const [docsRevision, setDocsRevision] = useState(0);
  const [coverRevision, setCoverRevision] = useState(0);
  const requested = params.get("pane");
  const pane: Pane = jobId && PANES.some((p) => p.id === requested) ? (requested as Pane) : "job";
  const view: View = params.get("view") === "history" ? "history" : "tailor";
  const setQuery = (key: string, next: string | null) =>
    setParams(
      (previous) => {
        const query = new URLSearchParams(previous);
        if (next === null) query.delete(key);
        else query.set(key, next);
        return query;
      },
      { replace: true },
    );
  const setPane = (next: string) => setQuery("pane", next);
  const setView = (next: string) => setQuery("view", next === "history" ? "history" : null);

  const entry = run.history?.find((item) => item.job_id === jobId);
  const showProgress = busy || status === "failed" || status === "cancelled";
  const canTailor = useCanTailor();
  const startJob = () => {
    setView("tailor");
    void run.startJob();
  };
  useCommands(() => [
    {
      id: "tailor-run",
      title: jobId ? "Tailor again" : "Tailor resume",
      group: "Tailor",
      keywords: "run start",
      shortcut: ["Ctrl", "Enter"],
      disabled: !canTailor,
      run: startJob,
    },
    {
      id: "tailor-history",
      title: view === "history" ? "Back to the current run" : "Run history",
      group: "Tailor",
      keywords: "past runs",
      run: () => setView(view === "history" ? "tailor" : "history"),
    },
    ...PANES.map((item) => ({
      id: `tailor-pane-${item.id}`,
      title: item.command,
      group: "Tailor",
      disabled: !jobId || pane === item.id,
      run: () => {
        setView("tailor");
        setPane(item.id);
      },
    })),
  ]);

  return (
    <Page width="wide">
      <CommandBar
        title="Tailor"
        state={jobId && view === "tailor" ? runMeta(entry, run.report?.title) : null}
        actions={
          <>
            {jobId && status === "succeeded" && !busy && view === "tailor" && (
              <SendToApply jobId={jobId} title={run.report?.title ?? ""} />
            )}
            <Tabs
              label="Tailor view"
              variant="segmented"
              items={VIEWS}
              value={view}
              onChange={setView}
            />
          </>
        }
      />
      {view === "history" ? (
        <TileLayout.Provider value="flat">
          {run.history.length ? (
            <RunHistoryPanel onOpened={() => setView("tailor")} />
          ) : (
            <EmptyState title={run.historyLoaded ? "No runs yet" : "Loading runs…"}>
              {run.historyLoaded ? "Every resume you tailor is kept here." : null}
            </EmptyState>
          )}
        </TileLayout.Provider>
      ) : (
        <div className={`grid items-start gap-4 ${BESIDE_DOCUMENT}`}>
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
              <JobPane onTailor={startJob} />
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
              <div
                className={`flex items-center justify-center rounded-sm border border-line bg-panel ${VIEWER_HEIGHT}`}
              >
                <EmptyState title="Your tailored resume shows here">
                  Paste a job posting on the left and press Tailor resume (Ctrl+Enter).
                </EmptyState>
              </div>
            )}
          </section>
        </div>
      )}
    </Page>
  );
}

function useCanTailor(): boolean {
  const { jdText, busy, settingsLoaded } = useRunState();
  const { switching } = useWorkspaceState();
  return !busy && Boolean(jdText.trim()) && settingsLoaded && !switching;
}

/** The posting, with Tailor resume right under it, then the run options. */
function JobPane({ onTailor }: { onTailor: () => void }) {
  const run = useRunState();
  const { config, jdText, setJdText, settings, setSettings, jobId, busy } = run;
  const { switching, activeId } = useWorkspaceState();
  const ready = run.settingsLoaded && !switching;
  const canTailor = useCanTailor();
  return (
    <>
      <JobInput
        jdText={jdText}
        setJdText={setJdText}
        disabled={busy}
        footer={
          <>
            <RunCostEstimate jdText={jdText} settings={settings} enabled={ready && !busy} />
            <div className="flex-1" />
            <Button
              variant="primary"
              data-shortcut="primary"
              disabled={!canTailor}
              onClick={onTailor}
            >
              {busy
                ? "Tailoring…"
                : switching
                  ? "Switching profile…"
                  : !run.settingsLoaded
                    ? "Loading settings…"
                    : jobId
                      ? "Tailor again"
                      : "Tailor resume"}
              <span aria-hidden className="ml-2 font-mono text-micro font-normal opacity-60">
                Ctrl Enter
              </span>
            </Button>
          </>
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
  );
}
