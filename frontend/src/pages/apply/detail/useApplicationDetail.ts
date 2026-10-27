import { useEffect, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import {
  acknowledgeApplicationResume,
  archiveApplications,
  correctApplicationField,
  fetchJob,
  focusApplicationReviewTab,
  getApplication,
  getApplicationsRevision,
  getApplyOperation,
  refreshApplicationReview,
  type ApplicationRow,
  type ApplyReviewField,
  type JobStatus,
  type Packet,
} from "../../../api";
import { startAdaptivePoll } from "../../../lib/adaptivePoll";
import { IN_FLIGHT_STATUSES } from "../../../lib/applyPoll";

export type Detail = {
  application: ApplicationRow;
  packet: Packet | null;
  jd_text: string | null;
  expansion_needed?: boolean;
};
export const DETAIL_TABS = [
  "overview",
  "outcome",
  "jd",
  "files",
  "answers",
  "review",
  "timeline",
  "notes",
] as const;
// Links saved before the tabs were renamed.
const TAB_ALIASES: Record<string, string> = { documents: "files", content: "answers" };

/** A tailor run still working: followed until it settles. */
const RUN_IN_FLIGHT = new Set(["queued", "running"]);

/**
 * One application's details: the record, its tailor run, the tab in the URL, and the
 * actions on it (archive/restore, accept a flagged resume, refresh or correct the form
 * review, open its browser tab). A tailor retry or fill in flight is followed until it
 * settles, and the run is read again whenever the row's run or status changes (audit
 * #16); a response for an application no longer on screen is dropped.
 */
export function useApplicationDetail(applicationId: string | undefined, workspaceId: unknown) {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const requestedTab = TAB_ALIASES[params.get("tab") ?? ""] ?? params.get("tab");
  const tab = DETAIL_TABS.includes(requestedTab as (typeof DETAIL_TABS)[number])
    ? requestedTab!
    : "overview";
  const [docsRevision, setDocsRevision] = useState(0);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  useEffect(() => {
    if (!applicationId) return;
    window.scrollTo(0, 0);
    const current = ++sequence.current;
    setDetail(null);
    setJob(null);
    setError(null);
    getApplication(applicationId)
      .then((result) => {
        if (current === sequence.current) setDetail(result);
      })
      .catch((reason) => {
        if (current === sequence.current) setError(String(reason));
      });
    const requestSequence = sequence;
    return () => {
      requestSequence.current++;
    };
  }, [applicationId, workspaceId]);
  const app = detail?.application;
  const jobId = app?.job_id ?? null;
  const status = app?.status;

  // The run is read for the row's current run and again whenever its status moves (a
  // retry re-tailors under the same id), then followed while it is still working.
  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    const current = sequence.current;
    let live = true;
    let timer = 0;
    const load = () =>
      fetchJob(jobId)
        .then((run) => {
          if (!live || current !== sequence.current) return;
          setJob(run);
          if (RUN_IN_FLIGHT.has(run.status)) timer = window.setTimeout(load, 3000);
        })
        .catch(() => {
          /* Saved application details remain available without a run. */
        });
    void load();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [jobId, status]);

  // Follow the registry (audit #17): read the row again whenever any application changed
  // (a fill, the nightly run, the extension), and on every poll while a tailor retry or
  // a fill is moving it — every 2 s then, every 15 s otherwise.
  const inFlight = !!app && IN_FLIGHT_STATUSES.has(app.status);
  const inFlightRef = useRef(inFlight);
  inFlightRef.current = inFlight;
  useEffect(() => {
    if (!applicationId) return;
    const current = sequence.current;
    let seen: string | null = null;
    const { stop } = startAdaptivePoll(async () => {
      const registry = await getApplicationsRevision();
      if (current !== sequence.current) return false;
      const revision = `${registry.workspace_id}:${registry.revision}`;
      if ((seen !== null && revision !== seen) || inFlightRef.current) {
        const result = await getApplication(applicationId);
        if (current === sequence.current) setDetail(result);
      }
      seen = revision;
      return inFlightRef.current;
    });
    return stop;
  }, [applicationId, workspaceId]);

  const from = (location.state as { from?: string } | null)?.from;
  const back = from ?? (app?.archived_at ? "/applications?tab=done" : "/applications");

  function setTab(value: string) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set("tab", value);
        return next;
      },
      { replace: true },
    );
  }

  /** Run `work` with the page busy; its result is dropped if another application opened. */
  async function guarded(work: () => Promise<Detail | void>) {
    const current = sequence.current;
    setBusy(true);
    try {
      const updated = await work();
      if (updated && current === sequence.current) setDetail(updated);
    } catch (reason) {
      if (current === sequence.current) setError(String(reason));
    } finally {
      if (current === sequence.current) setBusy(false);
    }
  }

  async function refreshEditedResume() {
    setDocsRevision((n) => n + 1);
    if (!applicationId || !app?.job_id) return;
    const current = sequence.current;
    try {
      const [updated, run] = await Promise.all([
        getApplication(applicationId),
        fetchJob(app.job_id),
      ]);
      if (current === sequence.current) {
        setDetail(updated);
        setJob(run);
      }
    } catch (reason) {
      if (current === sequence.current) setError(String(reason));
    }
  }

  /** Read the application again (after an action from its header). */
  async function reload() {
    if (!applicationId) return;
    const current = sequence.current;
    try {
      const updated = await getApplication(applicationId);
      if (current === sequence.current) setDetail(updated);
    } catch (reason) {
      if (current === sequence.current) setError(String(reason));
    }
  }

  /** Archive or restore, then show what the server did: a refusal names its reason, and
   * restoring a submitted application also undoes its submitted mark (audit #18). */
  async function move() {
    if (!app) return;
    setBusy(true);
    setError(null);
    try {
      const result = await archiveApplications([app.source_job_id], !app.archived_at);
      const refused = result.errors[app.source_job_id];
      if (refused) setError(`${app.archived_at ? "Not restored" : "Not archived"}: ${refused}`);
      await reload();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function waitForReview(operationId: string) {
    for (let attempt = 0; attempt < 150; attempt++) {
      const state = await getApplyOperation(operationId);
      if (!["queued", "running", "paused"].includes(state.state)) return;
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error("Review is still running. Refresh the page to see its latest result.");
  }

  const refreshReview = () => {
    if (!app) return;
    const id = app.source_job_id;
    return guarded(async () => {
      const started = await refreshApplicationReview(id);
      await waitForReview(started.operation_id);
      return getApplication(id);
    });
  };

  const correct = (field: ApplyReviewField, value: string | null, optionIds: string[]) => {
    if (!app?.fill?.review_snapshot_id) return;
    const snapshot = app.fill.review_snapshot_id;
    return guarded(async () => {
      const started = await correctApplicationField(app.source_job_id, {
        snapshot_id: snapshot,
        field_id: field.field_id,
        expected_state_hash: field.expected_state_hash,
        value,
        option_ids: optionIds,
        idempotency_key: crypto.randomUUID(),
      });
      await waitForReview(started.operation_id);
      return getApplication(app.source_job_id);
    });
  };

  const acceptResume = () => {
    if (!applicationId || !app?.resume_review) return;
    const revision = app.resume_review.revision;
    setError(null);
    return guarded(async () => {
      await acknowledgeApplicationResume(applicationId, revision);
      return getApplication(applicationId);
    });
  };

  const focusTab = () => {
    if (!app) return;
    void focusApplicationReviewTab(app.source_job_id).catch((reason) => setError(String(reason)));
  };

  const setApplication = (updated: ApplicationRow) =>
    setDetail((previous) => (previous ? { ...previous, application: updated } : previous));

  return {
    tab,
    setTab,
    detail,
    app,
    job,
    error,
    busy,
    back,
    docsRevision,
    refreshEditedResume,
    reload,
    move,
    refreshReview,
    correct,
    acceptResume,
    focusTab,
    setApplication,
  };
}
