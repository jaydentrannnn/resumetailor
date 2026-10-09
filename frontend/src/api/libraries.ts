/** The vocabulary dictionary (built-in + the user's additions) and vocabulary proposals. */

import { request } from "./core";

/** One spelling of a term, or one verb of a family. */
export type VocabularyItem = { value: string; builtin: boolean; hidden: boolean };

/** One dictionary term with its other spellings, or one opening-verb family. */
export type VocabularyEntry = {
  kind: "term" | "family";
  name: string;
  builtin: boolean;
  hidden: boolean;
  items: VocabularyItem[];
};

export type VocabularyKind = "term" | "alias" | "verb";

/** Counts and a fingerprint of the composed table. */
export type LibraryEffective = {
  term_count: number;
  tag_alias_count: number;
  verb_count: number;
  fingerprint: string;
};

/** One LLM-drafted vocabulary addition awaiting approval. `target_exists` says whether
 * approving an alias adds it to an existing term or creates that term. */
export type LibraryProposal = {
  id: string;
  kind: "tag_alias" | "verb_family";
  alias: string | null;
  canonical: string | null;
  verb: string | null;
  family: string | null;
  rationale: string;
  source: "run" | "manual";
  created_at: string;
  target_exists: boolean;
};

export type LibraryState = {
  entries: VocabularyEntry[];
  effective: LibraryEffective;
  /** Notes from composition (a user alias skipped because it would chain). */
  diagnostics: string[];
  proposals: LibraryProposal[];
  /** Set only by generateLibraryProposals when a draft partially failed. */
  warning: string | null;
};

export function fetchLibraries(): Promise<LibraryState> {
  /** The whole dictionary (hidden entries flagged) and pending suggestions. */
  return request<LibraryState>("/api/libraries");
}

export function addVocabulary(
  kind: VocabularyKind,
  value: string,
  target = "",
): Promise<LibraryState> {
  /** Add a term, another spelling of term `target`, or a verb to family `target`. */
  return request<LibraryState>("/api/libraries/additions", {
    method: "POST",
    body: JSON.stringify({ kind, value, target }),
  });
}

export function removeVocabulary(kind: VocabularyKind, value: string): Promise<LibraryState> {
  /** Delete one of the user's own entries (built-ins can only be hidden). */
  return request<LibraryState>("/api/libraries/additions/remove", {
    method: "POST",
    body: JSON.stringify({ kind, value }),
  });
}

export function setVocabularyHidden(
  kind: VocabularyKind,
  value: string,
  hidden: boolean,
): Promise<LibraryState> {
  /** Hide, or show again, one built-in term, spelling or verb. */
  return request<LibraryState>("/api/libraries/hidden", {
    method: "POST",
    body: JSON.stringify({ kind, value, hidden }),
  });
}

export function generateLibraryProposals(jdText?: string): Promise<LibraryState> {
  /** Draft new vocabulary suggestions from the resume's own gaps, optionally against
   * a pasted job description. */
  return request<LibraryState>("/api/libraries/proposals", {
    method: "POST",
    body: JSON.stringify({ jd_text: jdText ?? "" }),
  });
}

export function approveLibraryProposals(
  proposalIds: string[],
  targets: Record<string, string> = {},
): Promise<LibraryState> {
  /** Add proposals to the vocabulary; `targets[id]` sends an alias to another term. */
  return request<LibraryState>("/api/libraries/proposals/approve", {
    method: "POST",
    body: JSON.stringify({ proposal_ids: proposalIds, targets }),
  });
}

export function rejectLibraryProposals(proposalIds: string[]): Promise<LibraryState> {
  /** Decline selected proposals so they are never re-drafted. */
  return request<LibraryState>("/api/libraries/proposals/reject", {
    method: "POST",
    body: JSON.stringify({ proposal_ids: proposalIds }),
  });
}
