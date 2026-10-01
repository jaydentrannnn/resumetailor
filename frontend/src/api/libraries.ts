/** Vocabulary libraries (packs, selection, impact) and vocabulary proposals. */

import { request } from "./core";

/** A workspace's own additions and removals, layered on top of its enabled packs. */
export type LibraryOverrides = {
  tag_aliases: Record<string, string>;
  tag_aliases_removed: string[];
  /** verb -> family, one family per overridden verb (not a pack's family -> verbs[]). */
  verb_families: Record<string, string>;
  verb_families_removed: string[];
};

/** One pack's summary row for the pack list — no alias/verb bodies. */
export type LibraryPackSummary = {
  id: string;
  label: string;
  description: string;
  builtin: boolean;
  customized: boolean;
  tag_alias_count: number;
  verb_count: number;
  created_at: string;
  updated_at: string;
};

/** One pack's full contents, for the pack editor. */
export type LibraryPack = {
  id: string;
  label: string;
  description: string;
  builtin: boolean;
  customized: boolean;
  tag_aliases: Record<string, string>;
  verb_families: Record<string, string[]>;
  created_at: string;
  updated_at: string;
};

export type LibraryPackDraft = {
  label: string;
  description: string;
  tag_aliases: Record<string, string>;
  verb_families: Record<string, string[]>;
  /** Allow overwriting a target another pack already claims. */
  force?: boolean;
};

/** Summary of the composed table — per-pack contents already sit in `packs`. */
export type LibraryEffective = {
  tag_alias_count: number;
  verb_count: number;
  fingerprint: string;
};

/** One LLM-drafted vocabulary addition awaiting approval. */
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
};

export type LibraryState = {
  packs: LibraryPackSummary[];
  enabled_packs: string[];
  overrides: LibraryOverrides;
  effective: LibraryEffective;
  /** Notes from composition: a missing pack, a cross-pack verb collision, or a
   * dropped alias chain. Never errors. */
  diagnostics: string[];
  proposals: LibraryProposal[];
  /** Set only by generateLibraryProposals when a draft partially failed (e.g. the
   * model was unreachable) — the call still returns 200 with whatever succeeded. */
  warning: string | null;
};

/** What approving one alias would rewrite in the current master resume, if anything. */
export type LibraryAliasImpact = {
  alias: string;
  canonical: string;
  affected_tags: string[];
  affected_bullets: [string, string][];
};

export function fetchLibraries(): Promise<LibraryState> {
  /** Every pack (built-in and user-authored), the active profile's selection and
   * overrides, and the composed table's summary. */
  return request<LibraryState>("/api/libraries");
}

export function fetchLibraryPack(id: string): Promise<LibraryPack> {
  /** One pack's full contents, for the pack editor. */
  return request<LibraryPack>(`/api/libraries/packs/${encodeURIComponent(id)}`);
}

/**
 * Parse a `{message, errors}` validation-error body from a pack write, joining every
 * message rather than showing only the first — mirrors `templateErrorDetail`.
 *
 * `message` is itself `"; ".join(errors)` (`LibraryValidationError.__init__`,
 * libraries.py) — a summary derived from `errors`, not a distinct piece of information.
 * Appending `errors.join("\n")` after it would print the same text twice (obviously so
 * when there's exactly one error); `errors` alone is the complete, better-formatted
 * version, so it wins whenever present.
 */
async function libraryErrorDetail(res: Response): Promise<string> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") {
      detail = d;
    } else if (d && typeof d === "object" && "message" in d) {
      const errors = (d as { errors?: string[] }).errors ?? [];
      detail = errors.length ? errors.join("\n") : String((d as { message: string }).message);
    } else {
      detail = JSON.stringify(d ?? body);
    }
  } catch {
    /* keep statusText */
  }
  return detail;
}

export async function createLibraryPack(draft: LibraryPackDraft): Promise<LibraryState> {
  /** Create a new user-authored pack. The id is derived from the label. */
  const res = await fetch("/api/libraries/packs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
  if (!res.ok) throw new Error(await libraryErrorDetail(res));
  return res.json();
}

export async function updateLibraryPack(
  id: string,
  draft: LibraryPackDraft,
): Promise<LibraryState> {
  /** Update a user-authored pack's contents. Refuses a built-in id. */
  const res = await fetch(`/api/libraries/packs/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
  if (!res.ok) throw new Error(await libraryErrorDetail(res));
  return res.json();
}

export function deleteLibraryPack(id: string): Promise<LibraryState> {
  /** Delete a user-authored pack. Refuses a shipped id. */
  return request<LibraryState>(`/api/libraries/packs/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function resetLibraryPack(id: string): Promise<LibraryState> {
  /** Restore a shipped pack to its bundled seed by deleting its shadow file. */
  return request<LibraryState>(`/api/libraries/packs/${encodeURIComponent(id)}/reset`, {
    method: "POST",
  });
}

export function setLibrarySelection(
  enabledPacks: string[],
  overrides: LibraryOverrides,
): Promise<LibraryState> {
  /** Set the active profile's enabled packs and overrides. */
  return request<LibraryState>("/api/libraries/selection", {
    method: "PUT",
    body: JSON.stringify({ enabled_packs: enabledPacks, overrides }),
  });
}

export function previewLibraryImpact(
  tagAliases: Record<string, string>,
): Promise<{ impacts: LibraryAliasImpact[] }> {
  /** What approving each of `tagAliases` would rewrite in the current master resume. */
  return request<{ impacts: LibraryAliasImpact[] }>("/api/libraries/impact", {
    method: "POST",
    body: JSON.stringify({ tag_aliases: tagAliases }),
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

/** Thrown by `approveLibraryProposals` when approving would rewrite an existing bullet
 * tag and the caller has not yet confirmed that. Carries the exact impact so the UI can
 * show it before re-submitting with `acknowledgeRewrites: true`. */
export class LibraryApprovalConflict extends Error {
  impact: LibraryAliasImpact[];
  constructor(message: string, impact: LibraryAliasImpact[]) {
    super(message);
    this.name = "LibraryApprovalConflict";
    this.impact = impact;
  }
}

export async function approveLibraryProposals(
  proposalIds: string[],
  targetPackId: string,
  acknowledgeRewrites: boolean,
): Promise<LibraryState> {
  /** Fold selected proposals into an existing user-authored pack. Throws
   * `LibraryApprovalConflict` (409) when the change would rewrite an existing tag and
   * `acknowledgeRewrites` was not set. */
  const res = await fetch("/api/libraries/proposals/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      proposal_ids: proposalIds,
      target_pack_id: targetPackId,
      acknowledge_rewrites: acknowledgeRewrites,
    }),
  });
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    const detail = (body.detail ?? {}) as { message?: string; impact?: LibraryAliasImpact[] };
    throw new LibraryApprovalConflict(
      detail.message ?? "Approving this would rewrite existing tags.",
      detail.impact ?? [],
    );
  }
  if (!res.ok) {
    throw new Error(await libraryErrorDetail(res));
  }
  return res.json();
}

export function rejectLibraryProposals(proposalIds: string[]): Promise<LibraryState> {
  /** Decline selected proposals so they are never re-drafted. */
  return request<LibraryState>("/api/libraries/proposals/reject", {
    method: "POST",
    body: JSON.stringify({ proposal_ids: proposalIds }),
  });
}
