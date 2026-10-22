import { Link, useNavigate, useParams } from "react-router-dom";
import { ResumeQualityNotice } from "../components/ResumeQualityNotice";
import { Button, Page, Skeleton, Tabs } from "../components/ui";
import { isTabClosed } from "../lib/applicationRows";
import { useOpenTabs } from "../lib/useOpenTabs";
import { DocumentsCard } from "../components/DocumentsCard";
import { WIDE, useMediaQuery } from "../lib/useMediaQuery";
import { BESIDE_DOCUMENT, VIEWER_HEIGHT } from "../lib/viewer";
import { useWorkspaceState } from "../state/workspaceState";
import { AnswersPanel } from "./apply/detail/AnswersPanel";
import { DetailHeader } from "./apply/detail/DetailHeader";
import { NotesPanel } from "./apply/detail/NotesPanel";
import { OutcomePanel } from "./apply/detail/OutcomePanel";
import { JobDescriptionPanel, OverviewPanel } from "./apply/detail/OverviewPanel";
import { FilesPanel, ReviewPanel } from "./apply/detail/ReviewPanel";
import { TimelinePanel } from "./apply/detail/TimelinePanel";
import { useApplicationDetail } from "./apply/detail/useApplicationDetail";

/**
 * One application: header with its status and actions, then Overview / Outcome (once
 * sent) / Job description / Files / Answers / Form review / Timeline / Notes, each panel
 * its own tiles. App.tsx
 * lazy-imports this module, so it stays at this path.
 */
export function ApplicationDetailPage() {
  const { applicationId } = useParams();
  const navigate = useNavigate();
  const { activeId } = useWorkspaceState();
  const { openTabs } = useOpenTabs();
  const view = useApplicationDetail(applicationId, activeId);
  const wide = useMediaQuery(WIDE);
  const { app, detail, job, error, busy, tab } = view;
  if (error && !detail)
    return (
      <Page width="wide">
        <Link className="text-[13px] text-ink-muted hover:text-ink" to="/applications">
          ← Back to applications
        </Link>
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      </Page>
    );
  if (!app)
    return (
      <Page width="wide">
        <p className="sr-only" role="status">
          Loading application…
        </p>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-12 w-2/3" />
        <Skeleton className="h-48" />
      </Page>
    );
  const tabClosed = isTabClosed(app, openTabs);
  // Wide windows keep the tailored documents beside every tab, as on Tailor.
  const beside = wide && !!app.job_id;
  return (
    <Page width="wide">
      <DetailHeader
        app={app}
        tabOpen={!!app.fill?.browser_target_id && !app.archived_at && !tabClosed}
        busy={busy}
        onBack={() => navigate(view.back)}
        onFocusTab={view.focusTab}
        onMove={() => void view.move()}
      />
      <ResumeQualityNotice quality={app.resume_review?.quality} />
      {app.resume_review?.required && app.resume_review.quality.verified && (
        <div>
          <Button disabled={busy} onClick={() => void view.acceptResume()}>
            Use this resume anyway
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className={`grid items-start gap-5 ${beside ? BESIDE_DOCUMENT : ""}`}>
        <div className="min-w-0 space-y-4">
          <Tabs
            label="Application details"
            items={[
              { id: "overview", label: "Overview" },
              // Only once it was sent: what happened next is recorded here.
              ...(app.hiring?.stage ? [{ id: "outcome", label: "Outcome" }] : []),
              { id: "jd", label: "Job description" },
              { id: "files", label: beside ? "Extras" : "Files" },
              { id: "answers", label: "Answers" },
              { id: "review", label: "Form review" },
              { id: "timeline", label: "Timeline" },
              { id: "notes", label: app.notes ? "Notes •" : "Notes" },
            ]}
            value={tab}
            onChange={view.setTab}
          />
          <div role="tabpanel">
            {tab === "overview" && <OverviewPanel app={app} job={job} />}
            {tab === "outcome" && <OutcomePanel app={app} onSaved={view.setApplication} />}
            {tab === "jd" && <JobDescriptionPanel text={detail?.jd_text} />}
            {tab === "files" && (
              <FilesPanel
                app={app}
                job={job}
                revision={view.docsRevision}
                expansionNeeded={detail?.expansion_needed ?? false}
                onBulletsSaved={() => void view.refreshEditedResume()}
                onArtifactsChanged={() => void view.refreshEditedResume()}
                viewerBeside={beside}
              />
            )}
            {tab === "answers" && <AnswersPanel app={app} job={job} packet={detail?.packet} />}
            {tab === "review" && (
              <ReviewPanel
                app={app}
                tabClosed={tabClosed}
                disabled={busy || !!app.archived_at}
                error={error}
                onRefresh={() => void view.refreshReview()}
                onCorrect={(field, value, ids) => void view.correct(field, value, ids)}
              />
            )}
            {tab === "timeline" && applicationId && (
              <TimelinePanel app={app} applicationId={applicationId} />
            )}
            {tab === "notes" && (
              <NotesPanel key={app.source_job_id} application={app} onSaved={view.setApplication} />
            )}
          </div>
        </div>
        {beside && app.job_id && (
          <section
            aria-label="Documents"
            className="sticky top-[calc(var(--rt-bar-top)+1.25rem)] min-w-0"
          >
            <DocumentsCard
              revision={view.docsRevision}
              jobId={app.job_id}
              coverLetter={job?.cover_letter}
              onCoverRegenerated={() => {}}
              readOnly
              coverDetails={false}
              viewerClassName={VIEWER_HEIGHT}
            />
          </section>
        )}
      </div>
    </Page>
  );
}
