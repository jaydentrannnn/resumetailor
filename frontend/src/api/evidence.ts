import { apiError, request } from "./core";

export type EvidenceSourceKind = "github" | "syllabus" | "letter" | "writeup" | "other";
export type EvidenceAttribution = "own" | "contributed" | "fork" | "unknown" | "";
export type EvidenceKind = "bullet" | "project" | "skill" | "coursework";
export type EvidenceState = "pending" | "added" | "matching_only" | "dismissed";

/** A GitHub repository or document the student added (`web/routes/evidence.SourceView`). */
export type EvidenceSource = {
  id: string;
  kind: EvidenceSourceKind;
  title: string;
  url: string | null;
  added_at: string;
  flags: string[];
  attribution: EvidenceAttribution;
  commit_share: number | null;
  languages: string[];
  /** "" until the student scans it. */
  scanned_at: string;
  dropped: number;
  drop_reasons: Record<string, number>;
  model: string;
  chars: number;
};

export type NewProject = {
  name: string;
  tech: string[];
  url: string;
  start: string;
  end: string;
};

/** One item read from a source, waiting for the student (`evidence_store.Proposal`). */
export type EvidenceProposal = {
  id: string;
  source_id: string;
  kind: EvidenceKind;
  target_entry_id: string;
  new_project: NewProject | null;
  text: string;
  excerpt: string;
  basis: "stated" | "inferred";
  question: string;
  state: EvidenceState;
  decided_at: string;
  added_to: string;
};

export type EvidenceView = {
  sources: EvidenceSource[];
  proposals: EvidenceProposal[];
  matching: Record<string, string[]>;
  github_user: string;
  github_token: boolean;
  warnings: string[];
};

/** What the student settled on in the add dialog (`evidence_accept.AddRequest`). */
export type EvidenceAddRequest = {
  text: string;
  target_entry_id?: string;
  new_project?: NewProject;
  section_id?: string;
  skills?: string[];
  skill_group?: string;
  education_index?: number;
};

const post = <T>(path: string, body: unknown = {}): Promise<T> =>
  request(path, { method: "POST", body: JSON.stringify(body) });
const proposalPath = (id: string, action: string) =>
  `/api/evidence/proposals/${encodeURIComponent(id)}/${action}`;

export function getEvidence(): Promise<EvidenceView> {
  return request("/api/evidence");
}

/** List a user's repositories (or one repository); nothing is scanned yet. */
export function addGitHubEvidence(target: string): Promise<EvidenceView> {
  return post("/api/evidence/github", { target });
}

/** Add pasted text and scan it. */
export function addTextEvidence(
  kind: EvidenceSourceKind,
  title: string,
  text: string,
): Promise<EvidenceView> {
  return post("/api/evidence/text", { kind, title, text });
}

/** Add an uploaded .txt, .pdf or .docx and scan it. */
export async function addFileEvidence(
  kind: EvidenceSourceKind,
  title: string,
  file: File,
): Promise<EvidenceView> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  form.append("title", title);
  const res = await fetch("/api/evidence/file", { method: "POST", body: form });
  if (!res.ok) throw await apiError(res);
  return (await res.json()) as EvidenceView;
}

export function scanEvidenceSource(sourceId: string): Promise<EvidenceView> {
  return post(`/api/evidence/sources/${encodeURIComponent(sourceId)}/scan`);
}

export function removeEvidenceSource(sourceId: string): Promise<EvidenceView> {
  return request(`/api/evidence/sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" });
}

/** Write the item into the master resume; returns the saved resume for the editor. */
export function addEvidenceToResume(
  proposalId: string,
  body: EvidenceAddRequest,
): Promise<{ evidence: EvidenceView; resume: Record<string, unknown> }> {
  return post(proposalPath(proposalId, "add"), body);
}

export function keepEvidenceForMatching(
  proposalId: string,
  targetEntryId = "",
): Promise<EvidenceView> {
  return post(proposalPath(proposalId, "matching-only"), { target_entry_id: targetEntryId });
}

export function dismissEvidence(proposalId: string): Promise<EvidenceView> {
  return post(proposalPath(proposalId, "dismiss"));
}

/** Undo Dismiss or Matching only. */
export function reopenEvidence(proposalId: string): Promise<EvidenceView> {
  return post(proposalPath(proposalId, "reopen"));
}
