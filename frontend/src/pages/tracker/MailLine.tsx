import { Link } from "react-router-dom";
import { CopyButton } from "../../components/CopyButton";
import { Button, InlineHelp } from "../../components/ui";
import { relativeTime } from "../../lib/sources";
import { shortDate } from "../../lib/tracker";
import { useTracker } from "./trackerContext";

const ASK_CLAUDE = "Check my email for job updates";
const SETTINGS = "/settings?tab=email";

/**
 * The line over the board saying when job email was last read: the app's own mailbox
 * check when one is set up (with Check now), else how to ask Claude Desktop.
 */
export function MailLine() {
  const { board, busy, checkEmail } = useTracker();
  const mail = board?.mail;
  if (mail?.configured) {
    return (
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-ink-muted">
        {mail.running ? (
          <span role="status">Checking {mail.username}…</span>
        ) : mail.last_error ? (
          <span role="alert" className="text-danger">
            Could not check email: {mail.last_error}{" "}
            <Link to={SETTINGS} className="rt-link">
              Email settings
            </Link>
          </span>
        ) : (
          <span>
            {mail.last_checked
              ? `Email checked ${relativeTime(mail.last_checked)}.`
              : "Email not checked yet."}
          </span>
        )}
        {!mail.running && (
          <Button
            size="sm"
            variant="plain"
            loading={busy === "mail-check"}
            onClick={() => void checkEmail()}
          >
            Check now
          </Button>
        )}
      </p>
    );
  }
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
      {board?.last_synced
        ? `Email last checked ${shortDate(board.last_synced)}.`
        : "Email not checked yet."}
      <Link to={SETTINGS} className="rt-link">
        Connect an email account
      </Link>
      <InlineHelp label="checking email">
        Connect your mailbox in Settings › Email and the app reads job email itself. Or, in Claude
        Desktop with Gmail and ResumeTailor connected, ask: “{ASK_CLAUDE}”. Updates appear here to
        accept; nothing is recorded until you do.
      </InlineHelp>
      <CopyButton label="Copy the request" text={ASK_CLAUDE} />
    </p>
  );
}
