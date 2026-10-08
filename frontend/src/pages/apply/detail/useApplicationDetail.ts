import { useEffect, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import {
  acknowledgeApplicationResume,
  archiveApplications,
  correctApplicationField,
  fetchJob,
  focusApplicationReviewTab,
  getApplication,
  getApplyOperation,
  refreshApplicationReview,
  type ApplicationRow,
  type ApplyReviewField,
  type JobStatus,
  type Packet,
} from "../../../api";
import { IN_FLIGHT_STATUSES } from "../../../lib/applyPoll";

export type Detail = { application: ApplicationRow; packet: Packet | null; jd_text: string | null };
export const DETAIL_TABS = [
  "overview",
  "jd",
  "files",
  "answers",
  "review",
  "timeline",
  "notes",
] as const;
// Links saved before the tabs were renamed.
const TAB_ALIASES: Record<string, string> = { documents: "files", content: "answers" };

/**
 * One application's details: the record, its tailor run, the tab in the URL, and the
 * actions on it (archive/restore, accept a flagged resume, refresh or correct the form
 * review, open its browser tab). A tailor retry or fill in flight is followed until it
 * settles; a response for an application no longer on screen is dropped.
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
      .then(async (result) => {
        if (current !== sequence.current) return;
        setDetail(result);
        if (result.application.job_id) {
          try {
            const run = await fetchJob(result.application.job_id);
            if (current === sequence.current) setJob(run);
          } catch {
            /* Saved application details remain available without a run. */
          }
        }
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

  // A tailor retry or a fill moves the row on a background thread: follow it until it settles.
  const inFlight = !!app && IN_FLIGHT_STATUSES.has(app.status);
  useEffect(() => {
    if (!inFlight || !applicationId) return;
    const current = sequence.current;
    const id = window.setInterval(() => {
      getApplication(applicationId)
        .then((result) => {
          if (current === sequence.current) setDetail(result);
        })
        .catch(() => {
          /* keep the last copy */
        });
    }, 3000);
    return () => window.clearInterval(id);
  }, [inFlight, applicationId]);

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

  async function move() {
    if (!app) return;
    setBusy(true);
    try {
      await archiveApplications([app.source_job_id], !app.archived_at);
      setDetail((previous) =>
        previous
          ? {
              ...previous,
              application: {
                ...previous.application,
                archived_at: app.archived_at ? null : new Date().toISOString(),
              },
            }
          : previous,
      );
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
    move,
    refreshReview,
    correct,
    acceptResume,
    focusTab,
    setApplication,
  };
}
