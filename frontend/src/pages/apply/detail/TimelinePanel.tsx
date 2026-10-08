import type { ApplicationRow } from "../../../api";
import { StatusMark, Tile } from "../../../components/ui";
import { applicationStatusLabel, applicationStatusTone } from "../../../lib/applicationStatus";
import { TONE_TEXT } from "../../../lib/tone";
import { SubmitEvidenceList } from "../../../components/SubmitEvidenceList";

const when = (at: string) => new Date(at).toLocaleString();

/** Timeline: every status change, newest first, then any automatic-submit evidence. */
export function TimelinePanel({
  app,
  applicationId,
}: {
  app: ApplicationRow;
  applicationId: string;
}) {
  const history = [...(app.status_history ?? [])].reverse();
  return (
    <div className="space-y-4">
      <Tile title="Timeline">
        {(app.archived_at || app.fill?.confirmation) && (
          <div className="mb-3 space-y-1 text-xs text-ink-muted">
            {app.archived_at && (
              <p>
                Moved to Done <span className="font-mono">{when(app.archived_at)}</span>
              </p>
            )}
            {app.fill?.confirmation && (
              <p className="text-sm text-ink">Confirmation: {app.fill.confirmation}</p>
            )}
          </div>
        )}
        {history.length ? (
          <ol>
            {history.map((change, index) => {
              const tone = applicationStatusTone(change.status);
              return (
                <li
                  key={index}
                  className="grid grid-cols-[16px_minmax(0,1fr)_auto] items-start gap-3 border-t border-line py-2.5 text-[13px] first:border-t-0"
                >
                  <span className={`pt-1 ${TONE_TEXT[tone]}`}>
                    <StatusMark tone={tone} />
                  </span>
                  <span className="min-w-0">
                    <span className="font-medium text-ink">
                      {applicationStatusLabel(change.status)}
                    </span>
                    {change.note && <p className="text-xs text-ink-muted">{change.note}</p>}
                  </span>
                  <span className="font-mono text-xs text-ink-muted">{when(change.at)}</span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-sm text-ink-muted">No status changes recorded.</p>
        )}
      </Tile>
      <SubmitEvidenceList applicationId={applicationId} />
    </div>
  );
}
