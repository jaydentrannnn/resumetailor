import { request } from "./core";

/** The interview round prep is drafted for (`interview_prep.Stage`). */
export type PrepStage = "recruiter_screen" | "technical" | "behavioral" | "final";

export type PrepQuestion = {
  question: string;
  source: "requirement" | "gap" | "feedback" | "stage";
  about: string;
};

/** A STAR story built only from the cited bullets (guard-checked). */
export type PrepStory = {
  question: string;
  bullet_ids: string[];
  situation: string;
  task: string;
  action: string;
  result: string;
};

/** A sent bullet an interviewer is likely to dig into. */
export type ProbePoint = { bullet_id: string; text: string; reasons: string[] };

export type InterviewPrep = {
  stage: PrepStage;
  questions: PrepQuestion[];
  stories: PrepStory[];
  ask: string[];
  probe_points: ProbePoint[];
  warnings: string[];
  based_on: string;
  model: string;
  made_at: string;
};

/** What to send next for one sent application (`followup_due.state`). */
export type FollowUpState = {
  sent_on: string | null;
  days_since_sent: number | null;
  follow_ups_sent: number;
  due: "follow_up" | "thank_you" | null;
  stale: boolean;
  reason: string;
};

export type NoteChannel = "email" | "linkedin" | "portal";

/** A drafted note; `source` is "template" when the draft failed the claim check. */
export type FollowupNote = {
  kind: "follow_up" | "thank_you";
  channel: NoteChannel;
  subject: string;
  body: string;
  source: "llm" | "template";
  warnings: string[];
  model: string;
};

const rowPath = (id: string, rest: string) => `/api/applications/${encodeURIComponent(id)}/${rest}`;

/** Every saved prep for this application, one per round. */
export function getInterviewPreps(sourceJobId: string): Promise<{ preps: InterviewPrep[] }> {
  return request(rowPath(sourceJobId, "interview-prep"));
}

/** Draft (or redo) prep for one round from what was sent; it is saved. */
export function makeInterviewPrep(sourceJobId: string, stage: PrepStage): Promise<InterviewPrep> {
  return request(rowPath(sourceJobId, "interview-prep"), {
    method: "POST",
    body: JSON.stringify({ stage }),
  });
}

/** Draft a follow-up or thank-you note; nothing is sent or recorded. */
export function draftFollowUp(
  sourceJobId: string,
  body: { kind: FollowupNote["kind"]; channel: NoteChannel; recipient?: string },
): Promise<FollowupNote> {
  return request(rowPath(sourceJobId, "follow-up"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}
