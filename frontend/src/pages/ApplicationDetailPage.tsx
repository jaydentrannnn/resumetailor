import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  archiveApplications,
  acknowledgeApplicationResume,
  correctApplicationField,
  fetchJob,
  focusApplicationReviewTab,
  getApplication,
  getApplyOperation,
  refreshApplicationReview,
  setApplicationNotes,
  type ApplicationRow,
  type ApplyReviewField,
  type JobStatus,
  type Packet,
} from "../api";
import { ApplicationReview } from "../components/ApplicationReview";
import { ResumeQualityNotice } from "../components/ResumeQualityNotice";
import { DocumentsCard } from "../components/DocumentsCard";
import { Tabs } from "../components/Tabs";
import { ExperienceCard } from "../components/ExperienceCard";
import { SkillsCard } from "../components/SkillsCard";
import { SubmitEvidenceList } from "../components/SubmitEvidenceList";
import { applicationStatusLabel } from "../lib/applicationStatus";
import { IN_FLIGHT_STATUSES } from "../lib/applyPoll";
import { useWorkspaceState } from "../state/workspaceState";
import { isTabClosed } from "../lib/applicationRows";
import { useOpenTabs } from "../lib/useOpenTabs";
import { useToast } from "../lib/toast";
import { describe } from "../lib/errors";
import { CapturedBadge, siteName } from "./CapturedStubs";
import { BulletReview } from "./run/BulletReview";
import { ReportCard } from "./run/ReportCard";

type Detail = { application: ApplicationRow; packet: Packet | null; jd_text: string | null };
const tabs = ["overview", "jd", "files", "answers", "review", "timeline", "notes"] as const;
// Links saved before the tabs were renamed.
const TAB_ALIASES: Record<string, string> = { documents: "files", content: "answers" };
export function ApplicationDetailPage() {
  const { applicationId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { activeId } = useWorkspaceState();
  const [params, setParams] = useSearchParams();
  const requestedTab = TAB_ALIASES[params.get("tab") ?? ""] ?? params.get("tab");
  const tab = tabs.includes(requestedTab as (typeof tabs)[number]) ? requestedTab! : "overview";
  const [docsRevision, setDocsRevision] = useState(0);
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
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <ResumeQualityNotice quality={app.resume_review?.quality} />
      {app.resume_review?.required && app.resume_review.quality.verified && (
        <button
          className="rounded-md border border-warn px-3 py-2 text-sm text-warn"
          disabled={busy}
          onClick={async () => {
            if (!applicationId || !app.resume_review) return;
            const current = sequence.current;
            setBusy(true);
            setError(null);
            try {
              await acknowledgeApplicationResume(applicationId, app.resume_review.revision);
              const updated = await getApplication(applicationId);
              if (current === sequence.current) setDetail(updated);
            } catch (reason) {
              if (current === sequence.current) setError(String(reason));
            } finally {
              if (current === sequence.current) setBusy(false);
            }
          }}
        >
          Use this resume anyway
        </button>
      )}
      <button className="text-sm text-accent underline" onClick={() => navigate(back)}>
        ← Back to applications
      </button>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-semibold">
            {app.company} · {app.role}
          </h1>
          <p className="text-sm text-ink-muted">{app.location}</p>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span>
              {app.capture_stub ? "Needs description" : applicationStatusLabel(app.status)}
              {app.archived_at ? " · Archived" : ""}
            </span>
            <CapturedBadge row={app} />
          </p>
          {app.capture_stub && (
            <p className="mt-2 text-sm text-ink-muted">
              Saved from search results. Open it on {siteName(app.ats)} with the ResumeTailor
              extension installed and its description is saved automatically.
            </p>
          )}
          {app.apply_kind === "easy_apply" && (
            <p className="mt-2 text-sm text-ink-muted">
              Apply on {siteName(app.ats)}: this job uses {siteName(app.ats)}&apos;s own application
              form. Tailoring works; Fill can&apos;t drive that form.
            </p>
          )}
        </div>
        <div className="flex gap-2">
          {app.posting_url && (
            <a
              className="rounded-md border border-line px-3 py-2 text-sm"
              href={app.posting_url}
              target="_blank"
              rel="noreferrer"
            >
              {app.capture_stub ? `Open on ${siteName(app.ats)} ↗` : "Posting ↗"}
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
          { id: "jd", label: "Job description" },
          { id: "files", label: "Files" },
          { id: "answers", label: "Answers" },
          { id: "review", label: "Form review" },
          { id: "timeline", label: "Timeline" },
          { id: "notes", label: app.notes ? "Notes •" : "Notes" },
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
        </div>
      )}
      {tab === "jd" && (
        <div role="tabpanel">
          {detail?.jd_text ? (
            <section className="rounded-lg border border-line bg-panel p-5">
              <p className="whitespace-pre-wrap text-sm">{detail.jd_text}</p>
            </section>
          ) : (
            <p className="rounded-lg border border-line bg-panel p-5 text-sm text-ink-muted">
              The job description was not saved for this application.
            </p>
          )}
        </div>
      )}
      {tab === "timeline" && (
        <div role="tabpanel">
          <section className="rounded-lg border border-line bg-panel p-5">
            {app.archived_at && (
              <p className="text-xs text-ink-muted">
                Moved to Done {new Date(app.archived_at).toLocaleString()}
              </p>
            )}
            {app.fill?.confirmation && (
              <p className="mt-1 text-sm">Confirmation: {app.fill.confirmation}</p>
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
          {applicationId && <SubmitEvidenceList applicationId={applicationId} />}
        </div>
      )}
      {tab === "notes" && (
        <div role="tabpanel">
          <NotesPanel
            key={app.source_job_id}
            application={app}
            onSaved={(updated) =>
              setDetail((previous) => (previous ? { ...previous, application: updated } : previous))
            }
          />
        </div>
      )}
      {tab === "files" && (
        <div role="tabpanel" className="space-y-4">
          {app.job_id ? (
            <DocumentsCard
              revision={docsRevision}
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
          {app.job_id && !app.archived_at && (
            <details className="rounded-lg border border-line bg-panel p-4">
              <summary className="cursor-pointer text-sm font-medium">
                Edit bullets and render again (no AI)
              </summary>
              <p className="mt-2 text-xs text-ink-muted">
                The next fill uploads the updated resume.
              </p>
              <div className="mt-3">
                <BulletReview jobId={app.job_id} onSaved={() => void refreshEditedResume()} />
              </div>
            </details>
          )}
        </div>
      )}
      {tab === "answers" && (
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
          {app.fill?.long_text_answers && Object.keys(app.fill.long_text_answers).length > 0 && (
            <section className="rounded-lg border border-line bg-panel p-5">
              <h2 className="text-lg font-semibold">Written answers</h2>
              <p className="text-xs text-ink-muted">What the last fill typed into the form.</p>
              {Object.entries(app.fill.long_text_answers).map(([question, answer]) => (
                <div className="border-t border-line py-2 text-sm" key={question}>
                  <p className="font-medium">{question}</p>
                  <p className="mt-1 whitespace-pre-wrap text-ink-muted">{answer}</p>
                </div>
              ))}
            </section>
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

/** The applicant's own notes on one application, saved on demand. */
function NotesPanel({
  application,
  onSaved,
}: {
  application: ApplicationRow;
  onSaved: (updated: ApplicationRow) => void;
}) {
  const toast = useToast();
  const [text, setText] = useState(application.notes ?? "");
  const [saving, setSaving] = useState(false);
  const dirty = text !== (application.notes ?? "");
  async function save() {
    setSaving(true);
    try {
      onSaved(await setApplicationNotes(application.source_job_id, text));
      toast.success("Notes saved");
    } catch (reason) {
      toast.error("Could not save notes", describe(reason).detail);
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="space-y-3 rounded-lg border border-line bg-panel p-5">
      <label className="block text-sm font-medium" htmlFor="application-notes">
        Your notes
      </label>
      <textarea
        id="application-notes"
        className="field min-h-40 text-sm"
        maxLength={20000}
        placeholder="Recruiter name, interview dates, anything to remember."
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex items-center gap-3">
        <button
          type="button"
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent disabled:opacity-50"
          disabled={!dirty || saving}
          onClick={() => void save()}
        >
          {saving ? "Saving…" : "Save notes"}
        </button>
        {dirty && <span className="text-xs text-ink-muted">Unsaved changes</span>}
      </div>
    </section>
  );
}
