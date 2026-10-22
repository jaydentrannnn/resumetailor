import { useState } from "react";
import {
  correctOutcome,
  recordOutcome,
  type ApplicationRow,
  type OutcomeEvent,
} from "../../../api";
import { Button, StatusChip, Tile } from "../../../components/ui";
import { hiringTone, OUTCOME_LABELS } from "../../../lib/applicationStatus";
import { describe } from "../../../lib/errors";
import { useToast } from "../../../lib/toast";
import { OutcomeForm, type OutcomeInput } from "./OutcomeForm";
import { SentAttempts } from "./SentAttempts";

const STEP_LABELS: Record<string, string> = {
  applied: "Applied",
  assessment: "Assessment",
  interview: "Interview",
  offer: "Offer",
  hired: "Hired",
};

/** An ISO date as a local calendar day (no time-zone shift). */
function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString();
}

function eventStatus(event: OutcomeEvent, all: OutcomeEvent[]): string {
  if (event.voided_at) return all.some((o) => o.replaces === event.id) ? "Corrected" : "Removed";
  if (event.source === "mcp") return "Added by your assistant";
  return `Recorded ${new Date(event.recorded_at).toLocaleDateString()}`;
}

/**
 * Outcome: how far the application got, a form to record what happened (it works on
 * Done rows), every recorded event with Edit and Remove (both keep history), and the
 * files that were sent.
 */
export function OutcomePanel({
  app,
  onSaved,
}: {
  app: ApplicationRow;
  onSaved: (updated: ApplicationRow) => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState<OutcomeEvent | null>(null);
  const [busy, setBusy] = useState(false);
  // Bumped after each save so the form starts empty again.
  const [saves, setSaves] = useState(0);
  const id = app.source_job_id;
  const hiring = app.hiring;
  const events = [...(app.outcome_events ?? [])].reverse();

  async function save(action: () => Promise<ApplicationRow>, done: string) {
    setBusy(true);
    try {
      onSaved(await action());
      setEditing(null);
      setSaves((n) => n + 1);
      toast.success(done);
    } catch (reason) {
      toast.error("Could not save", describe(reason).detail);
    } finally {
      setBusy(false);
    }
  }
  const submit = (input: OutcomeInput) =>
    void save(
      () => (editing ? correctOutcome(id, editing.id, input) : recordOutcome(id, input)),
      editing ? "Correction saved" : "Recorded",
    );
  const remove = (event: OutcomeEvent) =>
    void save(() => correctOutcome(id, event.id, { void: true }), "Removed");

  return (
    <div className="space-y-4">
      <Tile
        title="Hiring progress"
        meta={hiring?.stage && <StatusChip tone={hiringTone(hiring)}>{hiring.label}</StatusChip>}
      >
        <p className="text-[13px] text-ink-2">
          {Object.entries(hiring?.stage_dates ?? {})
            .map(([step, day]) => `${STEP_LABELS[step] ?? step} ${dayLabel(day)}`)
            .join(" · ") || "Record an interview, an offer or a reply below."}
        </p>
      </Tile>
      <Tile title={editing ? "Correct this event" : "Record what happened"}>
        <OutcomeForm
          key={`${editing?.id ?? "new"}-${saves}`}
          editing={editing}
          busy={busy}
          onSubmit={submit}
          onCancel={() => setEditing(null)}
        />
      </Tile>
      {events.length > 0 && (
        <Tile title="Recorded">
          <ol>
            {events.map((event) => (
              <li
                key={event.id}
                className="flex items-start gap-3 border-t border-line py-2.5 text-[13px] first:border-t-0"
              >
                <div className="min-w-0 flex-1">
                  <p
                    className={
                      event.voided_at ? "text-ink-muted line-through" : "font-medium text-ink"
                    }
                  >
                    {OUTCOME_LABELS[event.type]}
                    {event.occurred_on && ` · ${dayLabel(event.occurred_on)}`}
                  </p>
                  {event.note && <p className="text-xs text-ink-2">{event.note}</p>}
                  <p className="text-xs text-ink-muted">{eventStatus(event, events)}</p>
                </div>
                {!event.voided_at && (
                  <div className="flex shrink-0 gap-1">
                    <Button
                      size="sm"
                      variant="plain"
                      disabled={busy}
                      onClick={() => setEditing(event)}
                    >
                      Edit
                    </Button>
                    <Button size="sm" variant="plain" disabled={busy} onClick={() => remove(event)}>
                      Remove
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ol>
        </Tile>
      )}
      <SentAttempts attempts={app.attempts ?? []} />
    </div>
  );
}
