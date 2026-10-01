/** localStorage scratch for the Tailor page: the JD draft and last job id per profile,
 * plus the one-time legacy settings import. Every access tolerates storage failing. */

import type { JobSettings } from "../api";

const JD_KEY_PREFIX = "resumeTailor.jdText";
//: Pre-server-settings storage key. Settings now live in the active profile's
//: settings.json; this is only read once, to import a leftover blob on first load.
export const LEGACY_SETTINGS_KEY = "resumeTailor.settings";

/**
 * A JD draft is scoped per profile — different profiles target different postings —
 * but stays client-side scratch rather than server state, since it is never final
 * until a run is started.
 */
export function jdStorageKey(workspaceId: string | null): string {
  return workspaceId ? `${JD_KEY_PREFIX}:${workspaceId}` : JD_KEY_PREFIX;
}

/**
 * Load a previously typed JD from localStorage for this profile, or an empty string.
 */
export function loadJdText(workspaceId: string | null): string {
  try {
    return localStorage.getItem(jdStorageKey(workspaceId)) ?? "";
  } catch {
    return "";
  }
}

const JOB_KEY_PREFIX = "resumeTailor.jobId";

/** Storage key for the most recently started job's id, scoped per profile so a reload
 * can re-attach to it — without this, a mid-run refresh orphans the job server-side
 * with no UI attached to it. */
function jobStorageKey(workspaceId: string | null): string {
  return workspaceId ? `${JOB_KEY_PREFIX}:${workspaceId}` : JOB_KEY_PREFIX;
}

export function loadStoredJobId(workspaceId: string | null): string | null {
  try {
    return localStorage.getItem(jobStorageKey(workspaceId));
  } catch {
    return null;
  }
}

/** A run stops producing further status changes once it reaches one of these. */
export function isTerminalJobStatus(status: string): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

/** Persist (or clear, when `jobId` is null) the last-started job id for this profile. */
export function storeJobId(workspaceId: string | null, jobId: string | null): void {
  try {
    if (jobId) localStorage.setItem(jobStorageKey(workspaceId), jobId);
    else localStorage.removeItem(jobStorageKey(workspaceId));
  } catch {
    /* quota / private mode — in-memory state is still correct for this session */
  }
}

/**
 * Read a settings blob left over from before settings moved server-side. Consulted
 * exactly once, by the settings-loading effect below, to avoid losing a returning
 * user's choices the first time their profile's settings.json is created.
 */
export function loadLegacySettings(): Partial<JobSettings> | null {
  try {
    const raw = localStorage.getItem(LEGACY_SETTINGS_KEY);
    return raw ? (JSON.parse(raw) as Partial<JobSettings>) : null;
  } catch {
    return null;
  }
}
