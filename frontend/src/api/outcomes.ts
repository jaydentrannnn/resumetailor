import type { ApplicationRow } from "./applications";
import { request } from "./core";

/** What happened after an application went out (`store_models.OutcomeType`). */
export type OutcomeType =
  | "assessment"
  | "interview_invited"
  | "interview_scheduled"
  | "interview_completed"
  | "offer"
  | "hired"
  | "offer_declined"
  | "rejected"
  | "withdrawn"
  | "ghosted"
  | "employer_timeline"
  | "followup_drafted"
  | "followup_sent";

/** One recorded fact. Corrected and removed events stay, with `voided_at` set. */
export type OutcomeEvent = {
  id: string;
  type: OutcomeType;
  occurred_on: string | null;
  recorded_at: string;
  source: "manual" | "mcp" | "monitor";
  note: string;
  replaces: string | null;
  voided_at: string | null;
};

/** What was sent: a read-only copy of the files when the row became submitted. */
export type SubmissionAttempt = {
  id: string;
  number: number;
  submitted_at: string;
  method: "auto" | "manual" | "monitor";
  /** True only when the app itself uploaded and sent these files. */
  confirmed: boolean;
  snapshot_dir: string;
  files: Record<string, string>;
  voided_at: string | null;
  error: string;
};

/** Derived from the events and legacy statuses (`outcomes.hiring_progress`). */
export type HiringProgress = {
  stage: "applied" | "assessment" | "interview" | "offer" | "hired" | null;
  closed: "rejected" | "withdrawn" | "ghosted" | "offer_declined" | null;
  responded: boolean;
  stage_dates: Record<string, string>;
  label: string;
};

const outcomesPath = (id: string) => `/api/applications/${encodeURIComponent(id)}/outcomes`;

/** Record an event; works on archived (Done) rows. */
export function recordOutcome(
  sourceJobId: string,
  body: { type: OutcomeType; occurred_on?: string | null; note?: string },
): Promise<ApplicationRow> {
  return request(outcomesPath(sourceJobId), { method: "POST", body: JSON.stringify(body) });
}

/** Correct an event (a replacement is recorded) or remove it with `void`. */
export function correctOutcome(
  sourceJobId: string,
  eventId: string,
  body: { type?: OutcomeType; occurred_on?: string | null; note?: string; void?: boolean },
): Promise<ApplicationRow> {
  return request(`${outcomesPath(sourceJobId)}/${encodeURIComponent(eventId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}
