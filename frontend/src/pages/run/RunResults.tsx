import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DocumentsCard } from "../../components/DocumentsCard";
import { ExperienceCard } from "../../components/ExperienceCard";
import { GenerateExperienceCard } from "../../components/GenerateExperienceCard";
import { SkillsCard } from "../../components/SkillsCard";
import { Tabs } from "../../components/Tabs";
import { Tile } from "../../components/ui";
import { useRunState } from "../../state/runState";
import { BulletReview } from "./BulletReview";
import { ReportCard } from "./ReportCard";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "bullets", label: "Review bullets" },
  { id: "documents", label: "Documents" },
  { id: "content", label: "Application content" },
];

/** "Halcyon Health · Data Analyst Intern · Oct 7, 1:12 PM" for the shown run. */
function runMeta(
  entry: { title?: string; company?: string; created_at?: string } | undefined,
  fallback: string | undefined,
): string {
  const when = entry?.created_at ? new Date(entry.created_at) : null;
  return [
    entry?.company,
    entry?.title || fallback,
    when && !Number.isNaN(when.getTime())
      ? when.toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })
      : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * The "Last result" tile: the shown run's report, bullet review, documents and
 * application content behind segmented tabs. The selected tab lives in the URL
 * (`result_tab`) and resets when a different run is shown. Each card renders
 * `embedded`, so nothing inside the tile is boxed again.
 */
export function RunResults({ jobId }: { jobId: string }) {
  const {
    report,
    refreshReport,
    expansion,
    setExpansion,
    skills,
    coverLetter,
    setCoverLetter,
    busy,
    history,
  } = useRunState();
  const [resultParams, setResultParams] = useSearchParams();
  // Bumped after a re-render so the documents preview reloads the new PDF.
  const [docsRevision, setDocsRevision] = useState(0);
  const resultTab = TABS.some((tab) => tab.id === resultParams.get("result_tab"))
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

  const entry = history?.find((run) => run.job_id === jobId);

  return (
    <Tile
      id="tailored-results"
      title="Last result"
      aria-label="Last result"
      meta={runMeta(entry, report?.title)}
    >
      <Tabs
        label="Tailored results"
        variant="segmented"
        items={TABS}
        value={resultTab}
        onChange={setResultTab}
      />
      <div role="tabpanel" className="mt-5">
        {resultTab === "overview" &&
          (report ? (
            <ReportCard report={report} embedded />
          ) : (
            <p className="text-sm text-ink-muted">A report has not been saved for this run.</p>
          ))}
        {resultTab === "bullets" && (
          <BulletReview
            jobId={jobId}
            ready={!busy}
            embedded
            onSaved={() => {
              setDocsRevision((n) => n + 1);
              void refreshReport();
            }}
          />
        )}
        {resultTab === "documents" && (
          <DocumentsCard
            revision={docsRevision}
            jobId={jobId}
            coverLetter={coverLetter}
            onCoverRegenerated={setCoverLetter}
            embedded
          />
        )}
        {resultTab === "content" && (
          <div className="space-y-6">
            {skills && (
              <SkillsCard plan={skills} gaps={report?.gaps ?? []} jobId={jobId} embedded />
            )}
            <div className={skills ? "border-t border-line pt-6" : undefined}>
              {expansion ? (
                <ExperienceCard expansion={expansion} jobId={jobId} embedded />
              ) : (
                <GenerateExperienceCard
                  jobId={jobId}
                  ready={!busy}
                  onGenerated={setExpansion}
                  embedded
                />
              )}
            </div>
          </div>
        )}
      </div>
    </Tile>
  );
}
