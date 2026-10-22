import { useState } from "react";
import type { OutcomeEvent, OutcomeType } from "../../../api";
import { Button } from "../../../components/ui";
import { OUTCOME_LABELS } from "../../../lib/applicationStatus";

// "Follow-up drafted" is written by the follow-up tool, not picked by hand.
const CHOICES = (Object.keys(OUTCOME_LABELS) as OutcomeType[]).filter(
  (type) => type !== "followup_drafted",
);

export type OutcomeInput = { type: OutcomeType; occurred_on: string | null; note: string };

/** "Record what happened": an outcome, its date when known, and a note. With `editing`
 * set, the same fields save a correction of that event. */
export function OutcomeForm({
  editing,
  busy,
  onSubmit,
  onCancel,
}: {
  editing: OutcomeEvent | null;
  busy: boolean;
  onSubmit: (input: OutcomeInput) => void;
  onCancel: () => void;
}) {
  const [type, setType] = useState<OutcomeType>(editing?.type ?? "interview_invited");
  const [day, setDay] = useState(editing?.occurred_on ?? "");
  const [note, setNote] = useState(editing?.note ?? "");
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ type, occurred_on: day || null, note });
      }}
    >
      <div className="flex flex-wrap gap-3">
        <label className="block min-w-48 flex-1 text-xs">
          <span className="mb-1 block text-ink-2">What happened</span>
          <select
            className="field w-full text-sm"
            value={type}
            onChange={(e) => setType(e.target.value as OutcomeType)}
          >
            {CHOICES.map((choice) => (
              <option key={choice} value={choice}>
                {OUTCOME_LABELS[choice]}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs">
          <span className="mb-1 block text-ink-2">When (optional)</span>
          <input
            type="date"
            className="field text-sm"
            value={day}
            onChange={(e) => setDay(e.target.value)}
          />
        </label>
      </div>
      <label className="block text-xs">
        <span className="mb-1 block text-ink-2">Note (optional)</span>
        <textarea
          className="field min-h-16 w-full text-sm"
          maxLength={2000}
          placeholder="Who you spoke with, what they asked, what comes next."
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={busy}>
          {editing ? "Save correction" : "Record"}
        </Button>
        {editing && (
          <Button variant="plain" disabled={busy} onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
