import type { ApplicationRow } from "../../../api";
import { Button, buttonClass, PageHeader, StatusChip } from "../../../components/ui";
import { applicationStatusLabel, applicationStatusTone } from "../../../lib/applicationStatus";
import { CapturedBadge, siteName } from "../../CapturedStubs";

/**
 * The application's title: a back link, its status and platform as the eyebrow,
 * "{company} · {role}" and the location, with Posting ↗, Open application tab and
 * Archive/Restore on the right.
 */
export function DetailHeader({
  app,
  tabOpen,
  busy,
  onBack,
  onFocusTab,
  onMove,
}: {
  app: ApplicationRow;
  /** The fill's browser tab is still open. */
  tabOpen: boolean;
  busy: boolean;
  onBack: () => void;
  onFocusTab: () => void;
  onMove: () => void;
}) {
  return (
    <PageHeader
      back={
        <button
          type="button"
          className="inline-flex items-center gap-1.5 text-[13px] text-ink-muted hover:text-ink"
          onClick={onBack}
        >
          ← Applications
        </button>
      }
      eyebrow={
        <span className="inline-flex flex-wrap items-center gap-2">
          <StatusChip
            tone={app.capture_stub ? "attention" : applicationStatusTone(app.status)}
            className="font-sans normal-case tracking-normal"
          >
            {app.capture_stub ? "Needs description" : applicationStatusLabel(app.status)}
            {app.archived_at ? " · Archived" : ""}
          </StatusChip>
          {app.ats && <span>{siteName(app.ats)}</span>}
          <span className="font-sans normal-case tracking-normal">
            <CapturedBadge row={app} />
          </span>
        </span>
      }
      title={`${app.company} · ${app.role}`}
      description={
        <>
          {app.location && <p>{app.location}</p>}
          {app.capture_stub && (
            <p className="mt-1 text-[13px]">
              Saved from search results. Open it on {siteName(app.ats)} with the ResumeTailor
              extension installed and its description is saved automatically.
            </p>
          )}
          {app.apply_kind === "easy_apply" && (
            <p className="mt-1 text-[13px]">
              Apply on {siteName(app.ats)}: this job uses {siteName(app.ats)}&apos;s own application
              form. Tailoring works; Fill can&apos;t drive that form.
            </p>
          )}
        </>
      }
      actions={
        <>
          {app.posting_url && (
            <a
              className={buttonClass("secondary", "sm")}
              href={app.posting_url}
              target="_blank"
              rel="noreferrer"
            >
              {app.capture_stub ? `Open on ${siteName(app.ats)} ↗` : "Posting ↗"}
            </a>
          )}
          {tabOpen && (
            <Button size="sm" onClick={onFocusTab}>
              Open application tab
            </Button>
          )}
          <Button size="sm" disabled={busy} onClick={onMove}>
            {app.archived_at ? "Restore" : "Archive"}
          </Button>
        </>
      }
    />
  );
}
