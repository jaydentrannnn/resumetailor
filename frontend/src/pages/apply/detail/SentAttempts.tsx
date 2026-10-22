import type { SubmissionAttempt } from "../../../api";
import { Tile } from "../../../components/ui";

function howSent(attempt: SubmissionAttempt): string {
  if (attempt.method === "manual")
    return "Marked submitted by you. These are the prepared files; what you uploaded isn't confirmed.";
  if (attempt.method === "monitor")
    return "You submitted in the tab ResumeTailor filled, and the confirmation was seen.";
  return attempt.confirmed
    ? "Sent by ResumeTailor, and the confirmation was seen."
    : "Sent by ResumeTailor; the confirmation wasn't seen.";
}

/** "What was sent": the read-only copy kept each time the application went out. */
export function SentAttempts({ attempts }: { attempts: SubmissionAttempt[] }) {
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
            <p className="text-xs text-ink-muted">
              {Object.keys(attempt.files).join(", ") || "No files were copied."}
            </p>
            {attempt.error && <p className="text-xs text-attn">{attempt.error}</p>}
            {attempt.snapshot_dir && (
              <p className="break-all font-mono text-[11px] text-ink-muted">
                {attempt.snapshot_dir}
              </p>
            )}
          </li>
        ))}
      </ol>
    </Tile>
  );
}
