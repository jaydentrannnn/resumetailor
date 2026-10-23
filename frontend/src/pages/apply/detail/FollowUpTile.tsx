import { useState } from "react";
import {
  draftFollowUp,
  recordOutcome,
  type ApplicationRow,
  type FollowupNote,
  type NoteChannel,
} from "../../../api";
import { CopyButton } from "../../../components/CopyButton";
import { Button, Segmented, Tile } from "../../../components/ui";
import { describe } from "../../../lib/errors";
import { useToast } from "../../../lib/toast";

const CHANNELS = [
  { id: "email", label: "Email" },
  { id: "linkedin", label: "LinkedIn" },
  { id: "portal", label: "Portal message" },
];

const SENT_BY: Record<NoteChannel, string> = {
  email: "email",
  linkedin: "LinkedIn",
  portal: "portal message",
};

const todayIso = () => new Date().toLocaleDateString("en-CA");

/**
 * "Follow up" or "Thank-you note", when one is due (`app.follow_up.due`): pick where it
 * goes and who to, draft it from what was sent, copy it, then Mark as sent records a
 * "Follow-up sent" event. Nothing is sent from here.
 */
export function FollowUpTile({
  app,
  onSaved,
}: {
  app: ApplicationRow;
  onSaved: (updated: ApplicationRow) => void;
}) {
  const toast = useToast();
  const [channel, setChannel] = useState<NoteChannel>("email");
  const [recipient, setRecipient] = useState("");
  const [note, setNote] = useState<FollowupNote | null>(null);
  const [busy, setBusy] = useState(false);
  const state = app.follow_up;
  if (!state?.due) return null;
  const thankYou = state.due === "thank_you";
  const text = note
    ? [note.subject && `Subject: ${note.subject}`, note.body].filter(Boolean).join("\n\n")
    : "";

  async function run<T>(action: () => Promise<T>, failed: string): Promise<T | null> {
    setBusy(true);
    try {
      return await action();
    } catch (reason) {
      toast.error(failed, describe(reason).detail);
      return null;
    } finally {
      setBusy(false);
    }
  }
  const draft = async () => {
    const made = await run(
      () => draftFollowUp(app.source_job_id, { kind: state.due!, channel, recipient }),
      "Could not draft the note",
    );
    if (made) setNote(made);
  };
  const markSent = async () => {
    const updated = await run(
      () =>
        recordOutcome(app.source_job_id, {
          type: "followup_sent",
          occurred_on: todayIso(),
          note: `${thankYou ? "Thank-you" : "Follow-up"} by ${SENT_BY[channel]}`,
        }),
      "Could not save",
    );
    if (updated) {
      setNote(null);
      onSaved(updated);
      toast.success("Recorded as sent");
    }
  };

  return (
    <Tile
      title={thankYou ? "Thank-you note" : "Follow up"}
      meta={
        <span className="text-xs text-ink-muted">
          {thankYou
            ? "After your interview"
            : `Sent ${state.days_since_sent} days ago, no reply yet`}
        </span>
      }
      className="space-y-3 text-[13px]"
    >
      <div className="flex flex-wrap items-end gap-3">
        <Segmented
          label="Send by"
          items={CHANNELS}
          value={channel}
          onChange={(id) => setChannel(id as NoteChannel)}
        />
        <label className="block min-w-48 flex-1 text-xs">
          <span className="mb-1 block text-ink-2">To (optional)</span>
          <input
            className="field w-full text-sm"
            value={recipient}
            maxLength={120}
            placeholder="Recruiter or interviewer name"
            onChange={(e) => setRecipient(e.target.value)}
          />
        </label>
        <Button size="sm" variant="primary" disabled={busy} onClick={() => void draft()}>
          {note ? "Draft again" : "Draft note"}
        </Button>
      </div>
      {note && (
        <div className="space-y-2">
          {note.warnings.map((warning) => (
            <p key={warning} className="text-xs text-attn">
              {warning}
            </p>
          ))}
          <textarea
            aria-label="Drafted note"
            readOnly
            className="field min-h-40 w-full text-sm"
            value={text}
          />
          <div className="flex gap-2">
            <CopyButton label="Copy note" text={text} />
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void markSent()}>
              Mark as sent
            </Button>
          </div>
        </div>
      )}
    </Tile>
  );
}
