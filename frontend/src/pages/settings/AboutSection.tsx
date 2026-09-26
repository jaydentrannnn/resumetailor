import { useCallback, useEffect, useState } from "react";
import {
  checkForUpdate,
  fetchHealth,
  fetchUpdateStatus,
  installUpdate,
  type UpdateStatus,
} from "../../api";
import { Button, Card, Kbd } from "../../components/ui";
import { buttonClass } from "../../lib/buttonClass";
import { SHORTCUTS } from "../../lib/shortcuts";
import { UPDATE_IN_PROGRESS, updateStatusLine } from "../../lib/updateStatus";

/** Settings → About: version, updates, diagnostics for support, shortcuts. */
export function AboutSection() {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    fetchHealth()
      .then((h) => setVersion(h.version))
      .catch(() => setVersion(null));
  }, []);
  return (
    <div className="space-y-6">
      <Card title="ResumeTailor" description={version ? `Version ${version}` : undefined}>
        <p className="text-sm text-ink">
          Tailors your resume to each job without changing its look, and never adds anything you did
          not write.
        </p>
      </Card>
      <UpdatesCard />
      <Card
        title="Get help"
        description="The diagnostics file shows what the app did, with your name, contact details, keys and passwords removed. Attach it when you report a problem."
      >
        <a className={buttonClass("secondary")} href="/api/diagnostics.zip" download>
          Download diagnostics
        </a>
      </Card>
      <Card title="Keyboard shortcuts">
        <ul className="space-y-2 text-sm">
          {SHORTCUTS.map((s) => (
            <li key={s.action} className="flex items-center justify-between gap-4">
              <span>{s.description}</span>
              <span className="flex gap-1">
                {s.keys.map((k) => (
                  <Kbd key={k}>{k}</Kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

/**
 * Settings → About → Updates (desktop app). Nothing installs until the user clicks
 * Install; the server then waits for any running tailor or Apply operation, backs up
 * the data, and the app restarts into the new version.
 */
export function UpdatesCard() {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const load = useCallback(() => {
    fetchUpdateStatus()
      .then((next) => {
        setStatus(next);
        setError(null);
      })
      // During an install the server stops; keep the last status on screen.
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Follow a check or an install closely; otherwise the card is static.
  const polling = status != null && UPDATE_IN_PROGRESS.has(status.state);
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(load, 1500);
    return () => window.clearInterval(timer);
  }, [polling, load]);

  const act = async (action: () => Promise<UpdateStatus>) => {
    setSending(true);
    try {
      setStatus(await action());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  if (!status) return null;
  if (!status.supported) {
    return (
      <Card title="Updates">
        <p className="text-sm text-ink-muted">
          This copy runs from source or Docker. Update it with <code>git pull</code> (or{" "}
          <code>docker compose up --build</code>); the installed desktop app updates itself.
        </p>
      </Card>
    );
  }

  const notes = status.available?.notes.trim();
  return (
    <Card
      title="Updates"
      description={status.current ? `You have version ${status.current}.` : undefined}
      actions={
        <>
          {status.state === "available" && (
            <Button variant="primary" loading={sending} onClick={() => act(installUpdate)}>
              Install and restart
            </Button>
          )}
          <Button
            loading={sending && status.state !== "available"}
            disabled={polling}
            onClick={() => act(checkForUpdate)}
          >
            Check now
          </Button>
        </>
      }
    >
      <p
        role="status"
        className={`text-sm ${status.state === "error" ? "text-danger" : "text-ink"}`}
      >
        {updateStatusLine(status)}
      </p>
      {status.state === "downloading" && status.pct != null && (
        <div
          role="progressbar"
          aria-label="Download progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={status.pct}
          className="mt-3 h-2 overflow-hidden rounded-full bg-line"
        >
          <div className="h-full bg-accent" style={{ width: `${status.pct}%` }} />
        </div>
      )}
      {notes && status.state === "available" && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            What&apos;s new in {status.available?.version}
          </p>
          <p className="mt-1 whitespace-pre-line text-sm text-ink">{notes}</p>
        </div>
      )}
      {status.state === "available" && (
        <p className="mt-3 text-xs text-ink-muted">
          Your data and templates are backed up first. If a tailor or Apply run is going, the
          install waits for it to finish.
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
    </Card>
  );
}
