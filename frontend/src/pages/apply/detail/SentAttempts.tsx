import type { SubmissionAttempt } from "../../../api";
import { Tile } from "../../../components/ui";
import { attemptFileUrl } from "../../../lib/attemptFiles";

function howSent(attempt: SubmissionAttempt): string {
  if (attempt.method === "manual")
    return "Marked submitted by you. These are the prepared files; what you uploaded isn't confirmed.";
  if (attempt.method === "monitor")
    return "You submitted in the tab ResumeTailor filled, and the confirmation was seen.";
  return attempt.confirmed
    ? "Sent by ResumeTailor, and the confirmation was seen."
    : "Sent by ResumeTailor; the confirmation wasn't seen.";
}

function AttemptFiles({
  applicationId,
  attempt,
}: {
  applicationId: string;
  attempt: SubmissionAttempt;
}) {
  const names = Object.keys(attempt.files);
  if (!names.length) return <p className="text-xs text-ink-muted">No files were copied.</p>;
  const attached = attempt.attached ?? {};
  const groups = [
    ["Attached by the app", names.filter((name) => name in attached)],
    [
      Object.keys(attached).length ? "Prepared files" : "Prepared files (not confirmed attached)",
      names.filter((name) => !(name in attached)),
    ],
  ] as const;
  return (
    <>
      {groups
        .filter(([, list]) => list.length)
        .map(([label, list]) => (
          <p key={label} className="text-xs text-ink-muted">
            {label}:{" "}
            {list.map((name, index) => (
              <span key={name}>
                {index > 0 && ", "}
                <a
                  className="rt-link"
                  href={attemptFileUrl(applicationId, attempt.number, name)}
                  target="_blank"
                  rel="noreferrer"
                  title={`SHA-256 ${attempt.files[name]}`}
                >
                  {name.split("/").pop()}
                </a>
              </span>
            ))}
          </p>
        ))}
    </>
  );
}

/** "What was sent": the read-only copy kept each time the application went out. */
export function SentAttempts({
  applicationId,
  attempts,
}: {
  applicationId: string;
  attempts: SubmissionAttempt[];
}) {
  if (!attempts.length) return null;
  return (
    <Tile title="What was sent">
      <ol className="space-y-3">
        {[...attempts].reverse().map((attempt) => (
          <li key={attempt.id} className="text-[13px]">
            <p
              className={attempt.voided_at ? "text-ink-muted line-through" : "font-medium text-ink"}
            >
              Attempt {attempt.number} · {new Date(attempt.submitted_at).toLocaleString()}
            </p>
            {attempt.voided_at && <p className="text-xs text-ink-muted">Undone; files kept.</p>}
            <p className="text-xs text-ink-2">{howSent(attempt)}</p>
            <AttemptFiles applicationId={applicationId} attempt={attempt} />
            {attempt.error && <p className="text-xs text-attn">{attempt.error}</p>}
          </li>
        ))}
      </ol>
    </Tile>
  );
}
