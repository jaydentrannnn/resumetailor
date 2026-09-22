import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type ApplicantProfile,
  type ApplicationRow,
  type ApplicationsList,
  type BrowserStatus,
  type DailyStatus,
  type Packet,
  applicationsExportUrl,
  getApplicantProfile,
  getApplication,
  getBrowserStatus,
  getDailyStatus,
  listApplications,
  putApplicantProfile,
  retryApplication,
  runDailyApply,
  setApplicationStatus,
  startApplicationFill,
} from "../api";
import { useRunState } from "../state/runState";

//: Statuses `apply/daily.py::retry_application` has a retry path for — mirrors that
//: function's own status checks so the button only appears when a retry can succeed.
const RETRYABLE_STATUSES = new Set([
  "discovered",
  "needs_browser",
  "jd_fetched",
  "screened_out",
  "tailor_failed",
]);

const STATUS_CHIPS = [
  "ready",
  "awaiting_review",
  "screened_out",
  "needs_browser",
  "tailoring",
  "submitted",
  "discovered",
] as const;

/** Summary counters worth showing live, in funnel order. */
const PROGRESS_COUNTERS = [
  ["total_candidates", "candidates"],
  ["new_rows", "new"],
  ["discovered", "discovered"],
  ["jd_fetched", "jd fetched"],
  ["prefiltered_out", "prefiltered"],
  ["screened_out", "screened out"],
  ["grouped", "grouped"],
  ["reused", "reused"],
  ["tailored", "tailored"],
  ["ready", "ready"],
  ["needs_browser", "needs browser"],
  ["tailor_failed", "tailor failed"],
  ["submitted", "submitted"],
  ["submit_failed", "submit failed"],
] as const;

/** How often to re-poll `/api/applications/daily-status` while a run is live. */
const POLL_MS = 2000;

/**
 * Percent complete for the processing phase, clamped to 0-100.
 *
 * `total` is 0 during discovery (the row count is not known until every source
 * has been fetched), which reads as 0% rather than a divide-by-zero.
 */
export function runProgressPercent(processed: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0;
  const pct = Math.round((processed / total) * 100);
  return Math.max(0, Math.min(100, pct));
}

/** Human-readable one-liner for the current phase of a daily pass. */
export function describePhase(status: DailyStatus | null): string {
  if (!status) return "";
  if (status.running) {
    if (status.phase === "discovering") {
      return status.source_id
        ? `Fetching source ${status.source_id}…`
        : "Fetching sources…";
    }
    if (status.phase === "processing") {
      const position = Math.min(status.processed + 1, Math.max(status.total, 1));
      return status.current
        ? `Processing ${position}/${status.total}: ${status.current}`
        : `Processing ${position}/${status.total}…`;
    }
    return "Starting…";
  }
  if (status.phase === "done") {
    const reason = (status.summary?.reason as string) || "";
    if (reason) return `Last run skipped: ${reason}`;
    return status.dry_run ? "Last run finished (dry run)" : "Last run finished";
  }
  return "Idle";
}

/**
 * Daily apply funnel: queue of discovered/ready applications, CDP status,
 * packet drawer, and applicant-profile editor.
 */
export function ApplicationsPage() {
  const { settings, setSettings } = useRunState();
  const [list, setList] = useState<ApplicationsList | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [browser, setBrowser] = useState<BrowserStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [packet, setPacket] = useState<Packet | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [profile, setProfile] = useState<ApplicantProfile | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [daily, setDaily] = useState<DailyStatus | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [limit, setLimit] = useState<string>("");
  const [commandCopied, setCommandCopied] = useState(false);

  const refresh = useCallback(async () => {
    const [apps, status, prof] = await Promise.all([
      listApplications(filter || undefined),
      getBrowserStatus(),
      getApplicantProfile(),
    ]);
    setList(apps);
    setBrowser(status);
    setProfile(prof.profile);
  }, [filter]);

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, [refresh]);

  /** Re-fetch only the queue table — used by the poll loop, which must stay cheap. */
  const refreshList = useCallback(async () => {
    const apps = await listApplications(filter || undefined);
    setList(apps);
  }, [filter]);

  const refreshListRef = useRef(refreshList);
  refreshListRef.current = refreshList;

  // Polls progress even when idle, so a run started elsewhere (the nightly
  // scheduler, the CLI, another tab) still shows up here. The table is only
  // re-fetched while a run is live or on the running -> finished edge.
  useEffect(() => {
    let cancelled = false;
    let wasRunning = false;

    async function tick() {
      try {
        const status = await getDailyStatus();
        if (cancelled) return;
        setDaily(status);
        if (status.running || wasRunning) {
          await refreshListRef.current();
        }
        wasRunning = status.running;
      } catch {
        /* a failed poll is not worth a page-level error banner */
      }
    }

    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const counts = list?.counts ?? {};
  const rows = list?.applications ?? [];

  // Edge, not Chrome: Chrome refuses to open its remote-debugging port whenever any
  // other Chrome window (any profile) is already running under this account, which
  // would mean closing the user's normal browsing session every time. Edge is a
  // separate binary/process, so it can run this debug profile in the background
  // without touching Chrome at all.
  const browserCmd = useMemo(
    () =>
      `"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%LOCALAPPDATA%\\ResumeTailorEdge"`,
    [],
  );

  /** Persist the unattended batch-submit cap, clamped and debounced like any other setting. */
  function onSubmitCapChange(raw: string) {
    if (raw.trim() === "") return;
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    const clamped = Math.min(500, Math.max(0, Math.round(n)));
    setSettings({
      ...settings,
      apply: { ...settings.apply, auto_submit_max_per_run: clamped },
    });
  }

  /** Persist the funnel's own extract/answer model choice — separate from the Tailor
   * model setting; see `ApplySettings.model_spec` on the backend. */
  function onModelProviderChange(provider: string) {
    setSettings({
      ...settings,
      apply: {
        ...settings.apply,
        model_provider: provider as typeof settings.apply.model_provider,
      },
    });
  }

  function onModelNameChange(name: string) {
    setSettings({ ...settings, apply: { ...settings.apply, model_name: name } });
  }

  /** Copy the Edge launch command so the user can paste-and-run instead of
   * hand-selecting the code block. The server (often a Docker container) has no
   * way to spawn a process on the host, so this is the closest a browser button
   * can get to "launch it" — see the Desktop shortcut for true one-click. */
  async function onCopyBrowserCommand() {
    try {
      await navigator.clipboard.writeText(browserCmd);
      setCommandCopied(true);
      setTimeout(() => setCommandCopied(false), 2000);
    } catch {
      /* clipboard API unavailable (insecure context, permission denied, …) —
       * the command is still visible/selectable in the code block below. */
    }
  }

  async function onRunDaily() {
    setBusy(true);
    setError(null);
    try {
      const parsed = Number.parseInt(limit, 10);
      const started = await runDailyApply({
        limit: Number.isFinite(parsed) && parsed > 0 ? parsed : null,
        dry_run: dryRun,
      });
      if (!started.started) {
        setError("A daily run is already in progress.");
      }
      // Show the run as live immediately rather than waiting up to POLL_MS.
      setDaily(await getDailyStatus());
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onOpenPacket(row: ApplicationRow) {
    setSelectedId(row.source_job_id);
    setError(null);
    try {
      const detail = await getApplication(row.source_job_id);
      setPacket(detail.packet);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onFill(row: ApplicationRow) {
    setBusy(true);
    setError(null);
    try {
      await startApplicationFill(row.source_job_id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onRetry(row: ApplicationRow) {
    setBusy(true);
    setError(null);
    try {
      await retryApplication(row.source_job_id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onMark(row: ApplicationRow, status: string) {
    setError(null);
    try {
      await setApplicationStatus(row.source_job_id, status);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onSaveProfile() {
    if (!profile) return;
    setBusy(true);
    try {
      const saved = await putApplicantProfile(profile);
      setProfile(saved.profile);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-ink">Applications</h1>
          <p className="text-sm text-ink-muted">
            Daily funnel from SimplifyJobs → tailor → fill. You click Submit under policy A.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              browser?.reachable
                ? "bg-accent-soft text-ink"
                : "bg-danger/10 text-danger"
            }`}
            title={browser?.error || browser?.cdp_url}
          >
            Browser CDP {browser?.reachable ? "reachable" : "offline"}
          </span>
          <label
            className="flex items-center gap-1.5 text-xs text-ink-muted"
            title="Record discoveries only — no JD fetch, no tailoring, nothing written to the queue."
          >
            <input
              type="checkbox"
              checked={dryRun}
              disabled={daily?.running}
              onChange={(e) => setDryRun(e.target.checked)}
            />
            Dry run
          </label>
          <label
            className="flex items-center gap-1.5 text-xs text-ink-muted"
            title="Cap how many newly discovered postings this pass processes. Blank uses the profile's max_new_per_day."
          >
            Limit
            <input
              type="number"
              min={1}
              max={500}
              value={limit}
              disabled={daily?.running}
              placeholder="all"
              onChange={(e) => setLimit(e.target.value)}
              className="w-16 rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink"
            />
          </label>
          <label
            className="flex items-center gap-1.5 text-xs text-ink-muted"
            title="Unattended fill+submit cap per run — only applies to ATSes listed in auto_submit_ats (Workday is never auto-submitted). 0 disables unattended submission."
          >
            Auto-submit cap
            <input
              type="number"
              min={0}
              max={500}
              value={settings.apply.auto_submit_max_per_run}
              onChange={(e) => onSubmitCapChange(e.target.value)}
              className="w-16 rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink"
            />
          </label>
          <label
            className="flex items-center gap-1.5 text-xs text-ink-muted"
            title="Model for the funnel's own screening (JD extraction) and free-text answer drafting. Separate from the Tailor model — the actual resume tailoring still uses your Tailor settings."
          >
            Screening/answer model
            <select
              value={settings.apply.model_provider}
              onChange={(e) => onModelProviderChange(e.target.value)}
              className="rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink"
            >
              <option value="ollama">ollama</option>
              <option value="lmstudio">lmstudio</option>
              <option value="gemini">gemini</option>
              <option value="anthropic">anthropic</option>
            </select>
            <input
              type="text"
              value={settings.apply.model_name}
              onChange={(e) => onModelNameChange(e.target.value)}
              placeholder="model name"
              className="w-40 rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink"
            />
          </label>
          <button
            type="button"
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent disabled:opacity-50"
            disabled={busy || daily?.running}
            onClick={() => void onRunDaily()}
          >
            {daily?.running ? "Running…" : "Run daily now"}
          </button>
          <a
            className="rounded-md border border-line px-3 py-1.5 text-sm text-ink"
            href={applicationsExportUrl()}
          >
            Export CSV
          </a>
        </div>
      </div>

      {!browser?.reachable && (
        <div className="space-y-2 rounded-md border border-line bg-panel p-3 text-xs text-ink-muted">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              Launch a debug-enabled browser for fill (Edge recommended — it won't
              disturb your normal Chrome) — double-click the "ResumeTailor Edge
              (debug)" shortcut if you have one, or run:
            </span>
            <button
              type="button"
              onClick={() => void onCopyBrowserCommand()}
              className="shrink-0 rounded-md border border-line bg-bg px-2 py-1 text-xs font-medium text-ink"
            >
              {commandCopied ? "Copied!" : "Copy command"}
            </button>
          </div>
          <code className="block overflow-x-auto whitespace-pre-wrap break-all">
            {browserCmd}
          </code>
        </div>
      )}

      {error && (
        <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {daily && (daily.running || daily.phase === "done") && (
        <section
          className="space-y-2 rounded-lg border border-line bg-panel p-3"
          aria-live="polite"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium text-ink">
              {describePhase(daily)}
              {daily.running && daily.dry_run && (
                <span className="ml-2 rounded bg-warn/15 px-1.5 py-0.5 text-[10px] text-ink">
                  dry run — nothing saved
                </span>
              )}
            </p>
            {daily.running && daily.total > 0 && (
              <span className="text-xs text-ink-muted">
                {runProgressPercent(daily.processed, daily.total)}%
              </span>
            )}
          </div>

          {daily.running && (
            <div
              className="h-1.5 w-full overflow-hidden rounded-full bg-line"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={runProgressPercent(daily.processed, daily.total)}
            >
              <div
                className={`h-full bg-accent transition-all ${
                  daily.total > 0 ? "" : "animate-pulse"
                }`}
                style={{
                  width:
                    daily.total > 0
                      ? `${runProgressPercent(daily.processed, daily.total)}%`
                      : "100%",
                }}
              />
            </div>
          )}

          {daily.summary && (
            <div className="flex flex-wrap gap-1.5">
              {PROGRESS_COUNTERS.map(([key, label]) => {
                const value = Number(daily.summary?.[key] ?? 0);
                if (!value) return null;
                return (
                  <span
                    key={key}
                    className="rounded bg-surface px-1.5 py-0.5 text-[11px] text-ink-muted"
                  >
                    {label} {value}
                  </span>
                );
              })}
              {Array.isArray(daily.summary.errors) && daily.summary.errors.length > 0 && (
                <span
                  className="rounded bg-danger/10 px-1.5 py-0.5 text-[11px] text-danger"
                  title={(daily.summary.errors as string[]).slice(0, 10).join("\n")}
                >
                  errors {(daily.summary.errors as string[]).length}
                </span>
              )}
            </div>
          )}
        </section>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={`rounded-full px-3 py-1 text-xs ${
            filter === "" ? "bg-accent text-on-accent" : "bg-panel text-ink-muted"
          }`}
          onClick={() => setFilter("")}
        >
          all ({Object.values(counts).reduce((a, b) => a + b, 0)})
        </button>
        {STATUS_CHIPS.map((status) => (
          <button
            key={status}
            type="button"
            className={`rounded-full px-3 py-1 text-xs ${
              filter === status ? "bg-accent text-on-accent" : "bg-panel text-ink-muted"
            }`}
            onClick={() => setFilter(status)}
          >
            {status} ({counts[status] ?? 0})
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-panel text-ink-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Company</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Salary</th>
              <th className="px-3 py-2 font-medium">ATS</th>
              <th className="px-3 py-2 font-medium">Coverage</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.source_job_id} className="border-t border-line/60">
                <td className="px-3 py-2">
                  <div>{row.company}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(row.sources ?? []).map((src) => (
                      <span
                        key={src}
                        className="rounded bg-panel px-1.5 py-0.5 text-[10px] text-ink-muted"
                      >
                        {src}
                      </span>
                    ))}
                    {(row.group_size ?? 1) > 1 && (
                      <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] text-ink">
                        {row.group_size} locations
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <div>{row.role}</div>
                  {(row.eligibility_flags?.length ?? 0) > 0 && (
                    <div
                      className="mt-1 flex flex-wrap gap-1"
                      title={row.eligibility_flags.join("; ")}
                    >
                      {row.eligibility_flags.map((flag) => (
                        <span
                          key={flag}
                          className="rounded bg-warn/15 px-1.5 py-0.5 text-[10px] text-ink"
                        >
                          {flag}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-ink-muted">{row.salary || "—"}</td>
                <td className="px-3 py-2">
                  <span className="rounded bg-panel px-1.5 py-0.5 text-xs">{row.ats}</span>
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {row.screen
                    ? `${row.screen.coverage_matched}/${row.screen.coverage_total}`
                    : "—"}
                </td>
                <td className="px-3 py-2">{row.status}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {row.posting_url && (
                      <a
                        className="text-xs text-accent underline"
                        href={row.posting_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open
                      </a>
                    )}
                    <button
                      type="button"
                      className="text-xs text-accent underline"
                      onClick={() => void onOpenPacket(row)}
                    >
                      Packet
                    </button>
                    {(row.status === "ready" || row.status === "awaiting_review") && (
                      <button
                        type="button"
                        className="text-xs text-accent underline disabled:opacity-50"
                        disabled={busy}
                        onClick={() => void onFill(row)}
                      >
                        Open &amp; fill
                      </button>
                    )}
                    {RETRYABLE_STATUSES.has(row.status) && (
                      <button
                        type="button"
                        className="text-xs text-accent underline disabled:opacity-50"
                        disabled={busy}
                        onClick={() => void onRetry(row)}
                      >
                        Retry
                      </button>
                    )}
                    <button
                      type="button"
                      className="text-xs underline"
                      onClick={() => void onMark(row, "submitted")}
                    >
                      Submitted
                    </button>
                    <button
                      type="button"
                      className="text-xs underline"
                      onClick={() => void onMark(row, "skipped")}
                    >
                      Skip
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-ink-muted">
                  No applications yet. Enable apply in settings and run daily.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {packet && selectedId && (
        <div className="rounded-lg border border-line bg-panel p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="font-medium text-ink">
              Packet — {packet.company} / {packet.role}
            </h2>
            <button
              type="button"
              className="text-xs text-ink-muted underline"
              onClick={() => setPacket(null)}
            >
              Close
            </button>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {Object.entries(packet.fields).map(([key, value]) => (
              <div key={key} className="text-xs">
                <span className="text-ink-muted">{key}: </span>
                <span className="text-ink">{value}</span>
              </div>
            ))}
          </div>
          {packet.skills.length > 0 && (
            <p className="mt-3 text-xs text-ink-muted">
              Skills: {packet.skills.join(", ")}
            </p>
          )}
        </div>
      )}

      <div className="rounded-lg border border-line">
        <button
          type="button"
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium"
          onClick={() => setProfileOpen((v) => !v)}
        >
          Applicant profile
          <span className="text-ink-muted">{profileOpen ? "Hide" : "Show"}</span>
        </button>
        {profileOpen && profile && (
          <div className="space-y-3 border-t border-line px-4 py-4">
            {(
              [
                ["first_name", "First name"],
                ["last_name", "Last name"],
                ["preferred_name", "Preferred name"],
                ["email", "Email"],
                ["phone", "Phone"],
                ["earliest_start", "Earliest start (YYYY-MM)"],
                ["graduation_month", "Graduation (YYYY-MM)"],
                ["how_heard", "How heard"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="block text-xs text-ink-muted">
                {label}
                <input
                  className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-sm text-ink"
                  value={String(profile[key] ?? "")}
                  onChange={(e) =>
                    setProfile({ ...profile, [key]: e.target.value })
                  }
                />
              </label>
            ))}
            <button
              type="button"
              className="rounded-md bg-accent px-3 py-1.5 text-sm text-on-accent disabled:opacity-50"
              disabled={busy}
              onClick={() => void onSaveProfile()}
            >
              Save profile
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Count helper exported for vitest. */
export function sumStatusCounts(counts: Record<string, number>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0);
}
