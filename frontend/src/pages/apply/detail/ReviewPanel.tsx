import type { ApplicationRow, ApplyReviewField, JobStatus } from "../../../api";
import { ApplicationReview } from "../../../components/ApplicationReview";
import { DocumentsCard } from "../../../components/DocumentsCard";
import { Tile } from "../../../components/ui";
import { BulletReview } from "../../run/BulletReview";

/** Form review: what the last fill left on the form, with corrections. */
export function ReviewPanel({
  app,
  tabClosed,
  disabled,
  error,
  onRefresh,
  onCorrect,
}: {
  app: ApplicationRow;
  tabClosed: boolean;
  disabled: boolean;
  error: string | null;
  onRefresh: () => void;
  onCorrect: (field: ApplyReviewField, value: string | null, optionIds: string[]) => void;
}) {
  if (!app.fill)
    return (
      <Tile>
        <p className="text-sm text-ink-muted">No form review has been recorded.</p>
      </Tile>
    );
  return (
    <ApplicationReview
      application={app}
      tabClosed={tabClosed}
      disabled={disabled}
      error={error}
      onRefresh={onRefresh}
      onCorrect={onCorrect}
    />
  );
}

/** Files: the tailored resume and cover letter, and editing bullets without AI. */
export function FilesPanel({
  app,
  job,
  revision,
  onBulletsSaved,
}: {
  app: ApplicationRow;
  job: JobStatus | null;
  revision: number;
  onBulletsSaved: () => void;
}) {
  if (!app.job_id)
    return (
      <Tile>
        <p className="text-sm text-ink-muted">
          No tailored documents were saved for this application.
        </p>
      </Tile>
    );
  return (
    <div className="space-y-4">
      <DocumentsCard
        revision={revision}
        jobId={app.job_id}
        coverLetter={job?.cover_letter}
        onCoverRegenerated={() => {}}
        readOnly
      />
      {!app.archived_at && (
        <Tile padding="sm">
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-ink">
              Edit bullets and render again (no AI)
            </summary>
            <p className="mt-2 text-xs text-ink-muted">The next fill uploads the updated resume.</p>
            <div className="mt-3">
              <BulletReview embedded jobId={app.job_id} onSaved={onBulletsSaved} />
            </div>
          </details>
        </Tile>
      )}
    </div>
  );
}
