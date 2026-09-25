import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
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
} from "../api";
import { ApplicationReview } from "../components/ApplicationReview";
import { DocumentsCard } from "../components/DocumentsCard";
import { Tabs } from "../components/Tabs";
import { ExperienceCard } from "../components/ExperienceCard";
import { SkillsCard } from "../components/SkillsCard";
import { applicationStatusLabel } from "../lib/applicationStatus";
import { IN_FLIGHT_STATUSES } from "../lib/applyPoll";
import { useWorkspaceState } from "../state/workspaceState";
import { isTabClosed } from "../lib/applicationRows";
import { useOpenTabs } from "../lib/useOpenTabs";
import { ReportCard } from "./run/ReportCard";

type Detail = { application: ApplicationRow; packet: Packet | null; jd_text: string | null };
const tabs = ["overview", "documents", "content", "review"] as const;
export function ApplicationDetailPage() {
  const { applicationId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { activeId } = useWorkspaceState();
  const [params, setParams] = useSearchParams();
  const tab = tabs.includes(params.get("tab") as (typeof tabs)[number])
    ? params.get("tab")!
    : "overview";
  const [detail, setDetail] = useState<Detail | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  const { openTabs } = useOpenTabs();
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
  }, [applicationId, activeId]);
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
  const back = from ?? (app?.archived_at ? "/applications?archive_open=1" : "/applications");
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
  async function refreshReview() {
    if (!app) return;
    const current = sequence.current;
    setBusy(true);
    try {
      const started = await refreshApplicationReview(app.source_job_id);
      await waitForReview(started.operation_id);
      const updated = await getApplication(app.source_job_id);
      if (current === sequence.current) setDetail(updated);
    } catch (reason) {
      if (current === sequence.current) setError(String(reason));
    } finally {
      if (current === sequence.current) setBusy(false);
    }
  }
  async function correct(field: ApplyReviewField, value: string | null, optionIds: string[]) {
    if (!app?.fill?.review_snapshot_id) return;
    setBusy(true);
    const current = sequence.current;
    try {
      const started = await correctApplicationField(app.source_job_id, {
        snapshot_id: app.fill.review_snapshot_id,
        field_id: field.field_id,
        expected_state_hash: field.expected_state_hash,
        value,
        option_ids: optionIds,
        idempotency_key: crypto.randomUUID(),
      });
      await waitForReview(started.operation_id);
      const updated = await getApplication(app.source_job_id);
      if (current === sequence.current) setDetail(updated);
    } catch (reason) {
      if (current === sequence.current) setError(String(reason));
    } finally {
      if (current === sequence.current) setBusy(false);
    }
  }
  if (error && !detail)
    return (
      <div>
        <Link className="text-accent underline" to="/applications">
          Back to applications
        </Link>
        <p role="alert" className="mt-4 text-danger">
          {error}
        </p>
      </div>
    );
  if (!app) return <p className="text-sm text-ink-muted">Loading application…</p>;
  return (
    <div className="space-y-5">
      <button className="text-sm text-accent underline" onClick={() => navigate(back)}>
        ← Back to applications
      </button>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-semibold">
            {app.company} · {app.role}
          </h1>
          <p className="text-sm text-ink-muted">{app.location}</p>
          <p className="mt-2 text-sm">
            {applicationStatusLabel(app.status)}
            {app.archived_at ? " · Archived" : ""}
          </p>
        </div>
        <div className="flex gap-2">
          {app.posting_url && (
            <a
              className="rounded-md border border-line px-3 py-2 text-sm"
              href={app.posting_url}
              target="_blank"
              rel="noreferrer"
            >
              Posting ↗
            </a>
          )}
          {app.fill?.browser_target_id && !app.archived_at && !isTabClosed(app, openTabs) && (
            <button
              className="rounded-md border border-line px-3 text-sm"
              onClick={() =>
                void focusApplicationReviewTab(app.source_job_id).catch((reason) =>
                  setError(String(reason)),
                )
              }
            >
              Open application tab
            </button>
          )}
          <button
            className="rounded-md bg-accent px-3 text-sm text-on-accent disabled:opacity-40"
            disabled={busy}
            onClick={() => void move()}
          >
            {app.archived_at ? "Restore" : "Archive"}
          </button>
        </div>
      </header>
      {error && (
        <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
          {error}
        </p>
      )}
      <Tabs
        label="Application details"
        items={[
          { id: "overview", label: "Overview" },
          { id: "documents", label: "Documents" },
          { id: "content", label: "Application content" },
          { id: "review", label: "Form review" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "overview" && (
        <div role="tabpanel" className="space-y-4">
          <section className="rounded-lg border border-line bg-panel p-5">
            <h2 className="text-lg font-semibold">Overview</h2>
            <p className="mt-2 text-sm">
              Coverage:{" "}
              {app.screen?.coverage_total
                ? `${app.screen.coverage_matched}/${app.screen.coverage_total} (${Math.round((app.screen.coverage_matched / app.screen.coverage_total) * 100)}%)`
                : "Not assessed"}
            </p>
            {app.status === "screened_out" && app.screen && (
              <div className="mt-3 text-sm">
                <p>
                  <strong>Screened out: {app.screen_label ?? "see reasons"}</strong>
                </p>
                <ul className="mt-1 list-disc pl-5 text-ink-muted">
                  {app.screen.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
                {app.screen.evidence?.map((quote, index) => (
                  <blockquote
                    className="mt-2 border-l-2 border-line pl-3 text-ink-muted"
                    key={index}
                  >
                    “{quote}”
                  </blockquote>
                ))}
              </div>
            )}
            {app.error && <p className="text-sm text-danger">{app.error}</p>}
          </section>
          {job?.report && <ReportCard report={job.report} />}
          {detail?.jd_text && (
            <details className="rounded-lg border border-line bg-panel p-5">
              <summary className="cursor-pointer font-semibold">Job description</summary>
              <p className="mt-3 whitespace-pre-wrap text-sm">{detail.jd_text}</p>
            </details>
          )}
          <section className="rounded-lg border border-line bg-panel p-5">
            <h2 className="text-lg font-semibold">Status history</h2>
            {app.archived_at && (
              <p className="text-xs text-ink-muted">
                Archived {new Date(app.archived_at).toLocaleString()}
              </p>
            )}
            {app.status_history?.length ? (
              <ol className="mt-2 space-y-2">
                {[...app.status_history].reverse().map((change, index) => (
                  <li className="border-t border-line pt-2 text-sm" key={index}>
                    <strong>{applicationStatusLabel(change.status)}</strong> ·{" "}
                    {new Date(change.at).toLocaleString()}
                    {change.note && <p className="text-ink-muted">{change.note}</p>}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-ink-muted">No status changes recorded.</p>
            )}
          </section>
        </div>
      )}
      {tab === "documents" && (
        <div role="tabpanel">
          {app.job_id ? (
            <DocumentsCard
              jobId={app.job_id}
              coverLetter={job?.cover_letter}
              onCoverRegenerated={() => {}}
              readOnly
            />
          ) : (
            <p className="rounded-lg border border-line bg-panel p-5 text-sm text-ink-muted">
              No tailored documents were saved for this application.
            </p>
          )}
        </div>
      )}
      {tab === "content" && (
        <div role="tabpanel" className="space-y-4">
          <p className="text-xs text-ink-muted">
            Prepared content was saved with this application and may differ from later Profile
            edits.
          </p>
          {job?.skills && app.job_id && (
            <SkillsCard plan={job.skills} gaps={job.report?.gaps ?? []} jobId={app.job_id} />
          )}
          {job?.expansion && app.job_id && (
            <ExperienceCard expansion={job.expansion} jobId={app.job_id} />
          )}
          {detail?.packet && (
            <section className="rounded-lg border border-line bg-panel p-5">
              <h2 className="text-lg font-semibold">Prepared answers</h2>
              {Object.entries(detail.packet.fields)
                .filter(([key]) => !/password|credential|secret/i.test(key))
                .map(([key, value]) => (
                  <details className="border-t border-line py-2 text-sm" key={key}>
                    <summary className="cursor-pointer">{key}</summary>
                    <p className="whitespace-pre-wrap">{value}</p>
                  </details>
                ))}
            </section>
          )}
        </div>
      )}
      {tab === "review" && (
        <div role="tabpanel">
          {app.fill ? (
            <ApplicationReview
              application={app}
              tabClosed={isTabClosed(app, openTabs)}
              disabled={busy || !!app.archived_at}
              error={error}
              onRefresh={() => void refreshReview()}
              onCorrect={(field, value, ids) => void correct(field, value, ids)}
            />
          ) : (
            <p className="rounded-lg border border-line bg-panel p-5 text-sm text-ink-muted">
              No form review has been recorded.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
