import { useState } from "react";
import type { ApplicationRow, PrepStage } from "../../../api";
import { Button, Segmented, Spinner, Tile } from "../../../components/ui";
import { PrepView } from "./PrepView";
import { useInterviewPrep } from "./useInterviewPrep";

const ROUNDS: { id: PrepStage; label: string }[] = [
  { id: "recruiter_screen", label: "Recruiter screen" },
  { id: "technical", label: "Technical" },
  { id: "behavioral", label: "Behavioral" },
  { id: "final", label: "Final round" },
];

/**
 * "Interview prep", once an interview is recorded: pick the round, Prepare drafts it from
 * the files that were sent (and earlier-round notes), and each round's prep is kept.
 */
export function InterviewPrepTile({ app }: { app: ApplicationRow }) {
  const interviewed = Boolean(app.hiring?.stage_dates?.interview);
  const { preps, loaded, making, make } = useInterviewPrep(app.source_job_id);
  const saved = ROUNDS.find((round) => preps[round.id]);
  const [round, setRound] = useState<PrepStage | null>(null);
  if (!interviewed) return null;
  const chosen = round ?? saved?.id ?? "recruiter_screen";
  const prep = preps[chosen];
  const label = ROUNDS.find((r) => r.id === chosen)?.label ?? chosen;

  return (
    <Tile
      title="Interview prep"
      meta={<span className="text-xs text-ink-muted">From what you sent</span>}
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center gap-3">
        <Segmented
          label="Interview round"
          items={ROUNDS.map((r) => ({ ...r, label: preps[r.id] ? `${r.label} ✓` : r.label }))}
          value={chosen}
          onChange={(id) => setRound(id as PrepStage)}
        />
        <Button
          size="sm"
          variant={prep ? "ghost" : "primary"}
          disabled={making !== null || !loaded}
          onClick={() => void make(chosen)}
        >
          {making === chosen && <Spinner />}
          {prep ? "Prepare again" : `Prepare for ${label.toLowerCase()}`}
        </Button>
      </div>
      {prep ? (
        <PrepView prep={prep} />
      ) : (
        <p className="text-[13px] text-ink-2">
          {making === chosen
            ? "Drafting questions and stories from your resume…"
            : "Likely questions, stories from your bullets and questions to ask. Nothing is sent."}
        </p>
      )}
    </Tile>
  );
}
