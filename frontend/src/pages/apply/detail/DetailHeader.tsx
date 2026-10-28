import type { ApplicationRow } from "../../../api";
import { Button, buttonClass, CommandBar, StatusChip } from "../../../components/ui";
import { applicationStatusLabel, applicationStatusTone } from "../../../lib/applicationStatus";
import { CapturedBadge, siteName } from "../../CapturedStubs";
import type { DetailCommands } from "./useDetailCommands";

// Steps that need you are orange, as on the Apply list; Fill is the page's main action.
const NEXT_VARIANT = { continue: "attention", reopen: "attention", review: "attention" } as const;

/**
 * The application's command bar: a back link, "{company} · {role}", its status, platform
 * and location, with Posting ↗, Open application tab, the next step (as on its Apply
 * row), Mark submitted, Skip and Archive/Restore on the right. Notes about where it came
 * from or how it applies sit under the bar.
 */
export function DetailHeader({
  app,
  tabOpen,
  busy,
  commands,
  onBack,
  onFocusTab,
  onMove,
}: {
  app: ApplicationRow;
  /** The fill's browser tab is still open. */
  tabOpen: boolean;
  busy: boolean;
  commands: DetailCommands;
  onBack: () => void;
  onFocusTab: () => void;
  onMove: () => void;
}) {
  const notes = app.capture_stub || app.apply_kind === "easy_apply";
  const off = busy || commands.working;
  const nextVariant =
    commands.next in NEXT_VARIANT
      ? NEXT_VARIANT[commands.next as keyof typeof NEXT_VARIANT]
      : "primary";
  return (
    <>
      <CommandBar
        back={
          <button type="button" className="hover:text-ink" onClick={onBack}>
            ← Apply
          </button>
        }
        title={`${app.company} · ${app.role}`}
        state={
          <>
            <StatusChip tone={app.capture_stub ? "attention" : applicationStatusTone(app.status)}>
              {app.capture_stub ? "Needs description" : applicationStatusLabel(app.status)}
              {app.archived_at ? " · Archived" : ""}
            </StatusChip>
            {app.ats && <span>{siteName(app.ats)}</span>}
            {app.location && <span>{app.location}</span>}
            <CapturedBadge row={app} />
          </>
        }
        actions={
          <>
            {app.posting_url && (
              <a
                className={buttonClass("plain", "sm")}
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
            {commands.label && (
              <Button variant={nextVariant} size="sm" disabled={off} onClick={commands.runNext}>
                {commands.label}
              </Button>
            )}
            {commands.canMark && (
              <>
                <Button
                  size="sm"
                  disabled={off}
                  title="You sent it yourself: mark it submitted and move it to Done"
                  onClick={() => commands.mark("submitted")}
                >
                  Mark submitted
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={off}
                  onClick={() => commands.mark("skipped")}
                >
                  Skip
                </Button>
              </>
            )}
            <Button variant="plain" size="sm" disabled={off} onClick={onMove}>
              {app.archived_at ? "Restore" : "Archive"}
            </Button>
          </>
        }
      />
      {notes && (
        <div className="space-y-1 text-[13px] text-ink-muted">
          {app.capture_stub && (
            <p>
              Saved from search results. Open it on {siteName(app.ats)} with the ResumeTailor
              extension installed and its description is saved automatically.
            </p>
          )}
          {app.apply_kind === "easy_apply" && (
            <p>
              Apply on {siteName(app.ats)}: this job uses {siteName(app.ats)}&apos;s own application
              form. Tailoring works; Fill can&apos;t drive that form.
            </p>
          )}
        </div>
      )}
    </>
  );
}
