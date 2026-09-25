import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  archiveApplications,
  applicationsExportUrl,
  controlApplyOperation,
  focusApplicationReviewTab,
  getApplyOperation,
  getBrowserStatus,
  getDailyStatus,
  listApplications,
  listApplyOperations,
  retryApplication,
  setApplicationStatus,
  startApplyOperation,
  type ApplicationRow,
  type ApplicationsList,
  type ApplyOperation,
  type ProfileGap,
} from "../api";
import { useProfileGaps } from "../state/applicantProfileState";
import {
  DataTable,
  Pagination,
  RowActionsMenu,
  type TableColumn,
  type MenuItem,
} from "../components/TableControls";
import { ApplicationProgress } from "../components/ApplicationProgress";
import { useRunState } from "../state/runState";
import { useWorkspaceState } from "../state/workspaceState";
import { useConfirm } from "../state/confirmState";
import {
  applicationStatusLabel,
  applicationStatusTone,
  statusToneClass,
} from "../lib/applicationStatus";
import { startAdaptivePoll } from "../lib/adaptivePoll";
import { EDGE_DEBUG_COMMANDS, detectOs, type DesktopOs } from "../lib/browserCommand";
import { CopyButton } from "../components/CopyButton";
import {
  canContinueFill,
  canReopenFill,
  isTabClosed,
  retryShortLabel,
  retryTitle,
  type OpenTabs,
} from "../lib/applicationRows";
import { useOpenTabs } from "../lib/useOpenTabs";
import { tailorModelLabel } from "../lib/modelLabel";
import {
  consumeApplicationListScroll,
  rememberApplicationListScroll,
} from "../lib/applicationNavigation";
import { IN_FLIGHT_STATUSES, pollSignature, shouldRefreshTables } from "../lib/applyPoll";

// "review": filled applications waiting on the applicant, shown above the working table.
type Scope = "queue" | "review" | "archive";
const selectionCache = new Map<string, Set<string>>();
const terminal = new Set(["submitted", "interview", "rejected", "ghosted", "skipped"]);
const review = new Set(["awaiting_review", "awaiting_otp", "submit_unconfirmed", "fill_failed"]);
// One fixed box for every row action, <button> or <Link>: same width so the column
// lines up, one line (short labels; the full wording is the tooltip), and the compact
// `rt-row-action` height. Font size is set on the cell wrapper (see TableControls'
// menuItemClass for why a text-* class on a <button> is ignored).
const actionBase =
  "rt-row-action inline-flex w-[4.75rem] shrink-0 items-center justify-center whitespace-nowrap rounded-md px-2 font-medium disabled:cursor-not-allowed disabled:opacity-40";
const actionTone: Record<string, string> = {
  Fill: "bg-accent text-on-accent hover:brightness-110",
  Review: "bg-warn-soft text-warn hover:brightness-95",
  // The fill stopped for the applicant: still a "needs you" row, but the next step is to resume it.
  Continue: "bg-warn-soft text-warn hover:brightness-95",
  // Its tab was closed, so resuming means a fresh tab.
  Reopen: "bg-warn-soft text-warn hover:brightness-95",
  View: "border border-line bg-panel text-ink hover:border-line-hover",
};
// A retry after a failure is red; the same button as a routine next step
// (e.g. "Fetch JD" on a newly discovered row) is a teal outline, not an alarm.
const retryTone = (status: string) =>
  applicationStatusTone(status) === "danger"
    ? "border border-danger/50 bg-panel text-danger hover:bg-danger-soft"
    : "border border-accent/60 bg-panel text-accent hover:bg-accent-soft";
const allStatuses = [
  "discovered",
  "jd_fetched",
  "needs_browser",
  "screened_out",
  "screened_in",
  "tailoring",
  "tailor_failed",
  "ready",
  "filling",
  "awaiting_otp",
  "fill_failed",
  "awaiting_review",
  "submitted",
  "submit_unconfirmed",
  "interview",
  "rejected",
  "ghosted",
  "skipped",
];

function useApplicationTable(
  scope: Scope,
  workspaceId: string,
  params: URLSearchParams,
  setParams: ReturnType<typeof useSearchParams>[1],
  enabled: boolean,
) {
  const key = useCallback((name: string) => `${scope}_${name}`, [scope]);
  const [data, setData] = useState<ApplicationsList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [selected, setSelectedState] = useState(
    () => new Set(selectionCache.get(`${workspaceId}:${scope}`) ?? []),
  );
  const sequence = useRef(0);
  const q = params.get(key("q")) ?? "";
  const status = params.get(key("status")) ?? "";
  const page = Math.max(0, (Number(params.get(key("page"))) || 1) - 1);
  const size = [25, 50, 100].includes(Number(params.get(key("size"))))
    ? Number(params.get(key("size")))
    : 25;
  const sort = params.get(key("sort")) ?? (scope === "archive" ? "archived_at" : "discovered_at");
  const direction: "asc" | "desc" = params.get(key("direction")) === "asc" ? "asc" : "desc";
  const [search, setSearch] = useState(q);
  useEffect(() => {
    const id = window.setTimeout(() => setSearch(q), 250);
    return () => window.clearTimeout(id);
  }, [q]);
  function setSelected(next: Set<string>) {
    setSelectedState(next);
    selectionCache.set(`${workspaceId}:${scope}`, next);
  }
  function change(values: Record<string, string>, reset = true) {
    sequence.current++;
    if (reset) setSelected(new Set());
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        Object.entries(values).forEach(([field, value]) =>
          value ? next.set(key(field), value) : next.delete(key(field)),
        );
        if (!("page" in values)) next.delete(key("page"));
        return next;
      },
      { replace: true },
    );
  }
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    if (!enabled) return;
    const current = ++sequence.current;
    setLoading(true);
    listApplications({
      archive: scope === "archive" ? "archived" : "active",
      group: scope === "queue" ? "working" : scope === "review" ? "review" : undefined,
      q: search.trim(),
      status: status || undefined,
      sort,
      direction,
      limit: size,
      offset: page * size,
    })
      .then((result) => {
        if (current !== sequence.current) return;
        setData(result);
        setError(null);
        setSelectedState((previous) => {
          const ids = new Set(result.applications.map((row) => row.source_job_id));
          const next = new Set([...previous].filter((id) => ids.has(id)));
          if (next.size === previous.size) return previous; // unchanged: keep the reference
          selectionCache.set(`${workspaceId}:${scope}`, next);
          return next;
        });
        const lastPage = Math.max(0, Math.ceil(result.total / size) - 1);
        if (page > lastPage)
          setParams(
            (previous) => {
              const next = new URLSearchParams(previous);
              if (lastPage) next.set(key("page"), String(lastPage + 1));
              else next.delete(key("page"));
              return next;
            },
            { replace: true },
          );
      })
      .catch((reason) => {
        if (current === sequence.current) setError(String(reason));
      })
      .finally(() => {
        if (current === sequence.current) setLoading(false);
      });
  }, [
    workspaceId,
    enabled,
    scope,
    search,
    status,
    sort,
    direction,
    size,
    page,
    revision,
    setParams,
    key,
  ]);
  return {
    data,
    error,
    loading,
    selected,
    setSelected,
    q,
    status,
    page,
    size,
    sort,
    direction,
    change,
    refresh,
  };
}

/** One line naming the blank profile fields forms ask for, linking to where to set them. */
export function ProfileGapsNotice({ gaps }: { gaps: ProfileGap[] }) {
  if (!gaps.length) return null;
  const shown = gaps
    .slice(0, 4)
    .map((gap) => gap.label)
    .join(", ");
  const more = gaps.length > 4 ? ` and ${gaps.length - 4} more` : "";
  return (
    <p role="status" className="rounded-md border border-warn/50 bg-panel px-3 py-2 text-sm">
      Autofill will skip questions your profile leaves blank: {shown}
      {more}.{" "}
      <Link className="text-accent underline" to={gaps[0].path}>
        Set them in your profile
      </Link>
    </p>
  );
}

export function ApplicationsDashboard() {
  const { settings, setSettings, config } = useRunState();
  const { activeId } = useWorkspaceState();
  const { confirm } = useConfirm();
  const profileGaps = useProfileGaps();
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const archiveOpen = params.get("archive_open") === "1";
  const reviewOpen = params.get("review_closed") !== "1";
  const queueOpen = params.get("queue_closed") !== "1";
  // Collapse state lives in the URL, like archive_open, so it survives a visit to a detail page.
  function toggleParam(name: string, value: boolean) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (value) next.set(name, "1");
        else next.delete(name);
        return next;
      },
      { replace: true },
    );
  }
  const queue = useApplicationTable("queue", activeId ?? "", params, setParams, true);
  const archive = useApplicationTable("archive", activeId ?? "", params, setParams, archiveOpen);
  const reviewTable = useApplicationTable("review", activeId ?? "", params, setParams, true);
  const [archiveTotal, setArchiveTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [operation, setOperation] = useState<ApplyOperation | null>(null);
  const [dailyRunning, setDailyRunning] = useState(false);
  const [browserConnected, setBrowserConnected] = useState(false);
  const { openTabs, reachable: tabsReachable, recheck: recheckTabs } = useOpenTabs();
  useEffect(() => {
    if (tabsReachable != null) setBrowserConnected(tabsReachable);
  }, [tabsReachable]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ids: string[]; archived: boolean } | null>(null);
  const [columns, setColumns] = useState<Record<Scope, string[]>>({
    queue: [],
    review: [],
    archive: [],
  });
  const [dryRun, setDryRun] = useState(false);
  const [limit, setLimit] = useState("");
  const active =
    dailyRunning || (!!operation && ["queued", "running", "paused"].includes(operation.state));
  const scrollRestored = useRef(false);
  useEffect(() => {
    if (scrollRestored.current || !queue.data || (archiveOpen && !archive.data)) return;
    const position = consumeApplicationListScroll(activeId ?? "");
    if (position == null) return;
    scrollRestored.current = true;
    window.requestAnimationFrame(() => window.scrollTo(0, position));
  }, [activeId, queue.data, archiveOpen, archive.data]);
  const refreshQueue = queue.refresh;
  const refreshArchive = archive.refresh;
  const refreshReview = reviewTable.refresh;
  const refresh = useCallback(() => {
    refreshQueue();
    refreshReview();
    if (archiveOpen) refreshArchive();
    recheckTabs();
    setRevision((n) => n + 1);
  }, [refreshQueue, refreshReview, refreshArchive, archiveOpen, recheckTabs]);
  // The poll reads these through refs so it never restarts (and forgets what it saw)
  // when the archive is toggled or the rows change.
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const inFlightRef = useRef(false);
  const wakePollRef = useRef<() => void>(() => {});
  inFlightRef.current = [queue.data, reviewTable.data].some((data) =>
    data?.applications.some((row) => IN_FLIGHT_STATUSES.has(row.status)),
  );
  useEffect(() => {
    let live = true;
    listApplications({ archive: "archived", limit: 1 })
      .then((result) => {
        if (live) setArchiveTotal(result.total);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [activeId, revision]);
  useEffect(() => {
    getBrowserStatus()
      .then((result) => setBrowserConnected(result.reachable))
      .catch(() => {});
  }, [activeId]);
  useEffect(() => {
    let live = true;
    let seen: string | null = null;
    // Resolves to whether anything is in flight, which sets the next poll's delay.
    async function poll(): Promise<boolean> {
      const [operations, day] = await Promise.all([listApplyOperations(), getDailyStatus()]);
      if (!live) return false;
      setDailyRunning(day.running);
      const current =
        operations.find((op) => ["queued", "running", "paused"].includes(op.state)) ??
        operations[0];
      const latest = current ? await getApplyOperation(current.operation_id) : null;
      if (!live) return false;
      setOperation(latest);
      const snapshot = {
        operationId: latest?.operation_id ?? null,
        state: latest?.state ?? null,
        dailyRunning: day.running,
      };
      if (shouldRefreshTables(seen, snapshot, inFlightRef.current)) refreshRef.current();
      seen = pollSignature(snapshot);
      const operationActive = ["queued", "running", "paused"].includes(latest?.state ?? "");
      return operationActive || day.running || inFlightRef.current;
    }
    const { stop, wake } = startAdaptivePoll(poll);
    wakePollRef.current = wake;
    return () => {
      live = false;
      wakePollRef.current = () => {};
      stop();
    };
  }, []);
  const selectedRows = (queue.data?.applications ?? []).filter((row) =>
    queue.selected.has(row.source_job_id),
  );
  const prepareIds = selectedRows
    .filter((row) => !terminal.has(row.status))
    .map((row) => row.source_job_id);
  const fillIds = selectedRows
    .filter((row) => row.status === "ready" && row.preparation_eligible !== false)
    .map((row) => row.source_job_id);
  // Every fill that stops for the applicant lands in the review table, so resuming lives there.
  const selectedReview = (reviewTable.data?.applications ?? []).filter((row) =>
    reviewTable.selected.has(row.source_job_id),
  );
  const continueIds = selectedReview
    .filter((row) => canContinueFill(row, openTabs))
    .map((row) => row.source_job_id);
  const reopenRows = selectedReview.filter(canReopenFill);
  async function start(
    action: "find" | "prepare" | "fill",
    ids: string[] = [],
    mode: "initial" | "continue" | "reopen" = "initial",
    force = false,
  ) {
    setBusy(true);
    setError(null);
    try {
      setOperation(
        await startApplyOperation({
          action,
          application_ids: ids,
          fill_mode: mode,
          force_prepare: force,
          limit: Number(limit) > 0 ? Number(limit) : null,
          dry_run: action === "find" && dryRun,
          auto_submit: settings.apply.auto_submit_enabled,
          blocker_mode: "continue",
          model_provider: settings.apply.model_provider,
          model_name: settings.apply.model_name,
        }),
      );
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
      wakePollRef.current();
    }
  }
  /** Reopen in fresh tabs; ask first only when a tab that may hold unsaved answers is still open. */
  function reopen(rows: ApplicationRow[], tabs: OpenTabs) {
    const ids = rows.map((row) => row.source_job_id);
    if (!ids.length) return;
    if (!rows.some((row) => row.fill?.browser_target_id && !isTabClosed(row, tabs))) {
      void start("fill", ids, "reopen");
      return;
    }
    const many = ids.length > 1;
    void confirm({
      title: many ? `Reopen ${ids.length} application tabs?` : "Reopen application tab?",
      message: many
        ? "Unsaved answers in tabs that are still open may be lost."
        : "Unsaved answers in the old browser tab may be lost.",
      confirmLabel: "Reopen and fill",
    }).then((ok) => {
      if (ok) void start("fill", ids, "reopen");
    });
  }
  async function move(ids: string[], archived: boolean) {
    if (!ids.length) return;
    setBusy(true);
    setError(null);
    try {
      const result = await archiveApplications(ids, archived);
      if (result.updated.length) {
        const source = archived ? queue : archive;
        source.setSelected(
          new Set([...source.selected].filter((id) => !result.updated.includes(id))),
        );
        setNotice({ ids: result.updated, archived });
        refresh();
      }
      if (Object.keys(result.errors).length)
        setError(
          Object.entries(result.errors)
            .map(([id, message]) => `${id}: ${message}`)
            .join("; "),
        );
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }
  async function retry(row: ApplicationRow) {
    setBusy(true);
    try {
      await retryApplication(row.source_job_id);
      refresh();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }
  async function mark(row: ApplicationRow, status: "submitted" | "skipped") {
    try {
      const updated = await setApplicationStatus(row.source_job_id, status);
      // Submitting archives server-side; say so rather than letting the row vanish.
      if (updated.archived_at) setNotice({ ids: [row.source_job_id], archived: true });
      refresh();
    } catch (reason) {
      setError(String(reason));
    }
  }
  function detail(row: ApplicationRow, tab = "overview") {
    return {
      pathname: `/applications/${encodeURIComponent(row.source_job_id)}`,
      search: `?tab=${tab}`,
      state: { from: `${location.pathname}${location.search}`, archive: !!row.archived_at },
    };
  }
  function menu(row: ApplicationRow, archived: boolean): MenuItem[] {
    const items: MenuItem[] = [];
    if (row.job_id)
      items.push({
        label: "Tailored PDF",
        href: `/api/jobs/${encodeURIComponent(row.job_id)}/preview.pdf`,
      });
    if (row.posting_url) items.push({ label: "Job posting", href: row.posting_url });
    if (archived)
      return [
        ...items,
        {
          label: "Restore",
          disabled: busy || active,
          action: () => void move([row.source_job_id], false),
          description: "Available when Apply is idle",
        },
      ];
    if (row.job_id && !row.preparation_eligible && !terminal.has(row.status))
      items.push({
        label: "Prepare again",
        disabled: busy || active,
        action: () => void start("prepare", [row.source_job_id], "initial", true),
      });
    const tabOpen = !!row.fill?.browser_target_id && !isTabClosed(row, openTabs);
    if (tabOpen)
      items.push({
        label: "Open application tab",
        action: () =>
          void focusApplicationReviewTab(row.source_job_id).catch((reason) =>
            setError(String(reason)),
          ),
      });
    if (tabOpen && !["submitted", "filling", "submit_unconfirmed"].includes(row.status))
      items.push({
        label: "Continue fill",
        disabled: busy || active || !row.preparation_eligible,
        action: () => void start("fill", [row.source_job_id], "continue"),
      });
    if (canReopenFill(row))
      items.push({
        label: "Reopen and fill",
        disabled: busy || active,
        action: () => reopen([row], openTabs),
      });
    if (["awaiting_review", "awaiting_otp", "submit_unconfirmed"].includes(row.status))
      items.push({ label: "Mark submitted", action: () => void mark(row, "submitted") });
    if (!terminal.has(row.status))
      items.push({ label: "Skip", action: () => void mark(row, "skipped"), danger: true });
    return [
      ...items,
      {
        label: "Archive",
        disabled: busy || active,
        action: () => void move([row.source_job_id], true),
        description: "Available when Apply is idle",
      },
    ];
  }
  function renderTable(scope: Scope) {
    const state = scope === "queue" ? queue : scope === "review" ? reviewTable : archive;
    const archived = scope === "archive";
    const rows = state.data?.applications ?? [];
    const ids = rows
      .filter((row) => state.selected.has(row.source_job_id))
      .map((row) => row.source_job_id);
    const dateColumn = archived ? "archived_at" : "discovered_at";
    const cols: TableColumn<ApplicationRow>[] = [
      {
        id: "company",
        heading: "Company",
        sortable: true,
        className: "w-[19%]",
        cell: (row) => <strong className="font-medium">{row.company}</strong>,
      },
      {
        id: "role",
        heading: "Role / location",
        sortable: true,
        className: "w-[23%]",
        cell: (row) => (
          <>
            <Link
              className="font-medium text-accent hover:underline"
              to={detail(row)}
              onClick={() => rememberApplicationListScroll(activeId ?? "")}
            >
              {row.role}
            </Link>
            <p className="text-xs text-ink-muted">{row.location}</p>
          </>
        ),
      },
      {
        id: "ats",
        heading: "Platform",
        sortable: true,
        className: "w-[9%]",
        cell: (row) =>
          row.ats ? (
            <span className="rounded bg-panel px-1.5 py-0.5 text-xs">{row.ats}</span>
          ) : (
            <span className="text-ink-muted">—</span>
          ),
      },
      {
        id: "status",
        heading: "Status",
        sortable: true,
        className: "w-[17%]",
        cell: (row) => (
          <>
            <span
              className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${statusToneClass[applicationStatusTone(row.status)]}`}
            >
              {applicationStatusLabel(row.status)}
            </span>
            {row.screen_label && (
              <p
                className="mt-1 line-clamp-1 text-xs text-ink-muted"
                title={row.screen?.reasons.join("; ")}
              >
                {row.screen_label}
              </p>
            )}
            {row.review_summary && (
              <p
                className="mt-1 line-clamp-1 text-xs text-warn"
                title={row.fill?.handoff_reason || row.review_summary}
              >
                {row.review_summary}
              </p>
            )}
            {row.error && !archived && (
              <p className="mt-1 line-clamp-1 text-xs text-danger">{row.error}</p>
            )}
            {!archived && review.has(row.status) && isTabClosed(row, openTabs) && (
              <p className="mt-1 text-xs text-ink-muted">Tab closed</p>
            )}
          </>
        ),
      },
      ...(scope === "queue"
        ? [
            {
              id: "coverage",
              heading: "Coverage",
              sortable: true,
              className: "w-[11%]",
              cell: (row: ApplicationRow) =>
                row.screen?.coverage_total
                  ? `${row.screen.coverage_matched}/${row.screen.coverage_total} · ${Math.round((row.screen.coverage_matched / row.screen.coverage_total) * 100)}%`
                  : "Not assessed",
            },
          ]
        : []),
      {
        id: dateColumn,
        heading: archived ? "Archived" : "Discovered",
        sortable: true,
        className: "w-[12%]",
        cell: (row) => {
          const value = archived ? row.archived_at : row.discovered_at;
          return value ? new Date(value).toLocaleDateString() : "—";
        },
      },
      ...columns[scope].map((id) => ({
        id,
        heading: id[0].toUpperCase() + id.slice(1),
        sortable: true,
        className: "w-[10%]",
        cell: (row: ApplicationRow) =>
          id === "sources"
            ? [...new Set(row.sources)].join(", ")
            : id === "coverage"
              ? row.screen?.coverage_total
                ? `${row.screen.coverage_matched}/${row.screen.coverage_total}`
                : "Not assessed"
              : id === "discovered_at"
                ? row.discovered_at
                  ? new Date(row.discovered_at).toLocaleDateString()
                  : "—"
                : String(row[id as "salary"] || "—"),
      })),
      {
        id: "actions",
        heading: "Actions",
        className: "w-[19%]",
        cell: (row) => {
          const retryKind =
            !archived && !terminal.has(row.status) && !review.has(row.status) && row.retry_kind
              ? retryShortLabel(row.retry_kind, row.status)
              : null;
          const kind =
            archived || terminal.has(row.status)
              ? "View"
              : review.has(row.status)
                ? canContinueFill(row, openTabs)
                  ? "Continue"
                  : isTabClosed(row, openTabs) && canReopenFill(row)
                    ? "Reopen"
                    : "Review"
                : row.status === "ready" && row.preparation_eligible !== false
                  ? "Fill"
                  : (retryKind ?? "View");
          // "Continue" resumes the fill in its open tab, "Reopen" starts over once that tab
          // is closed; Review stays one menu item away.
          const replaced =
            kind === "Continue" ? "Continue fill" : kind === "Reopen" ? "Reopen and fill" : null;
          const items = replaced
            ? [
                { label: "Review", action: () => navigate(detail(row, "review")) },
                ...menu(row, archived).filter((item) => item.label !== replaced),
              ]
            : menu(row, archived).filter((item) => item.label !== kind);
          return (
            <div className="flex flex-nowrap items-center gap-1 text-xs">
              {kind === "Continue" ? (
                <button
                  className={`${actionBase} ${actionTone.Continue}`}
                  title={
                    browserConnected
                      ? "Continue fill in the open application tab"
                      : "Connect the browser in Apply settings to continue"
                  }
                  disabled={busy || active || !browserConnected}
                  onClick={() => void start("fill", [row.source_job_id], "continue")}
                >
                  Continue
                </button>
              ) : kind === "Reopen" ? (
                <button
                  className={`${actionBase} ${actionTone.Reopen}`}
                  title="The application tab was closed: open the posting in a new tab and fill it again"
                  disabled={busy || active || !browserConnected}
                  onClick={() => reopen([row], openTabs)}
                >
                  Reopen
                </button>
              ) : kind === "Fill" || retryKind === kind ? (
                <button
                  className={`${actionBase} ${kind === "Fill" ? actionTone.Fill : retryTone(row.status)}`}
                  title={kind !== "Fill" && row.retry_kind ? retryTitle(row.retry_kind) : undefined}
                  disabled={busy || active}
                  onClick={() =>
                    kind === "Fill" ? void start("fill", [row.source_job_id]) : void retry(row)
                  }
                >
                  {kind}
                </button>
              ) : (
                <Link
                  to={detail(row, kind === "Review" ? "review" : "overview")}
                  onClick={() => rememberApplicationListScroll(activeId ?? "")}
                  className={`${actionBase} ${actionTone[kind] ?? actionTone.View}`}
                >
                  {kind}
                </Link>
              )}
              <RowActionsMenu label={`More actions for ${row.company} ${row.role}`} items={items} />
            </div>
          );
        },
      },
    ];
    const pagination = (
      <Pagination
        page={state.page}
        size={state.size}
        total={state.data?.total ?? 0}
        onPage={(page) => {
          state.change({ page: String(page + 1) });
          document.getElementById(`${scope}-toolbar`)?.scrollIntoView();
        }}
        onSize={(size) => state.change({ size: String(size) })}
      />
    );
    return (
      <div className="space-y-3">
        <div id={`${scope}-toolbar`} className="flex flex-wrap gap-2">
          <input
            className="min-w-48 flex-1 rounded-md border border-line bg-panel px-3 text-sm"
            aria-label={`Search ${archived ? "archived" : "working"} applications`}
            data-shortcut="search"
            placeholder="Search company, role, or location"
            value={state.q}
            onChange={(e) => state.change({ q: e.target.value })}
          />
          <select
            aria-label="Filter by status"
            className="rounded-md border border-line bg-panel px-2 text-sm"
            value={state.status}
            onChange={(e) => state.change({ status: e.target.value })}
          >
            <option value="">All statuses</option>
            {[...new Set([...allStatuses, ...Object.keys(state.data?.counts ?? {})])]
              .filter((value) => scope === "archive" || review.has(value) === (scope === "review"))
              .map((value) => (
                <option value={value} key={value}>
                  {applicationStatusLabel(value)} ({state.data?.counts[value] ?? 0})
                </option>
              ))}
          </select>
          <button
            className="rounded-md border border-line bg-panel px-3 text-sm"
            onClick={state.refresh}
          >
            Refresh
          </button>
          <details className="relative">
            <summary className="cursor-pointer rounded-md border border-line bg-panel px-3 py-2 text-sm">
              Columns
            </summary>
            <div className="absolute right-0 z-20 w-32 space-y-2 rounded-md border border-line bg-panel p-3 text-xs shadow">
              {(archived
                ? ["coverage", "discovered_at", "salary", "sources"]
                : ["salary", "sources"]
              ).map((id) => (
                <label className="block" key={id}>
                  <input
                    type="checkbox"
                    checked={columns[scope].includes(id)}
                    onChange={(e) =>
                      setColumns((current) => ({
                        ...current,
                        [scope]: e.target.checked
                          ? [...current[scope], id]
                          : current[scope].filter((value) => value !== id),
                      }))
                    }
                  />{" "}
                  {id.replaceAll("_", " ")}
                </label>
              ))}
            </div>
          </details>
        </div>
        {/* text-sm on the bar, not the buttons: index.css's unlayered `button { font: inherit }`
          overrides a text-* class on a <button>, so the buttons and the Export link only
          match when they inherit one size. */}
        {scope === "queue" && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel p-3 text-sm">
            <button
              type="button"
              className="inline-flex items-center rounded-md border border-line bg-panel px-3 font-medium text-ink hover:border-line-hover disabled:opacity-50"
              disabled={busy || active}
              title="Discover new postings from the configured sources"
              onClick={() => void start("find")}
            >
              Find jobs
            </button>
            <a
              className="rt-control inline-flex items-center rounded-md border border-line bg-panel px-3 font-medium text-ink hover:border-line-hover"
              href={applicationsExportUrl()}
            >
              Export CSV
            </a>
            <span aria-hidden className="mx-1 h-6 w-px bg-line" />
            <button
              type="button"
              className="inline-flex items-center rounded-md border border-accent/50 bg-accent-soft px-3 font-medium text-ink disabled:opacity-50"
              disabled={busy || active || !prepareIds.length}
              title="Fetch, screen, and tailor the selected applications"
              onClick={() => void start("prepare", prepareIds)}
            >
              Prepare selected ({prepareIds.length})
            </button>
            <button
              type="button"
              className="inline-flex items-center rounded-md bg-accent px-3 font-medium text-on-accent disabled:opacity-50"
              disabled={busy || active || !fillIds.length || !browserConnected}
              title={
                browserConnected
                  ? "Open and fill the selected prepared applications"
                  : "Connect the browser in Apply settings to fill"
              }
              onClick={() => void start("fill", fillIds)}
            >
              Fill selected ({fillIds.length})
            </button>
            <span className="ml-auto text-xs text-ink-muted">
              Fill{" "}
              {settings.apply.auto_submit_enabled ? "submits verified forms" : "stops for review"}
            </span>
            {ids.length > fillIds.length && (
              <span className="text-xs text-warn">
                {ids.length - fillIds.length} selected cannot Fill yet
              </span>
            )}
          </div>
        )}
        {scope === "review" && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel p-3 text-sm">
            <button
              type="button"
              className="inline-flex items-center rounded-md border border-accent/50 bg-accent-soft px-3 font-medium text-ink disabled:opacity-50"
              disabled={busy || active || !continueIds.length || !browserConnected}
              title={
                browserConnected
                  ? "Resume the selected fills in their open application tabs"
                  : "Connect the browser in Apply settings to fill"
              }
              onClick={() => void start("fill", continueIds, "continue")}
            >
              Continue fill selected ({continueIds.length})
            </button>
            <button
              type="button"
              className="inline-flex items-center rounded-md border border-line bg-panel px-3 font-medium text-ink hover:border-line-hover disabled:opacity-50"
              disabled={busy || active || !reopenRows.length || !browserConnected}
              title={
                browserConnected
                  ? "Open the selected postings in new tabs and fill them from the start"
                  : "Connect the browser in Apply settings to fill"
              }
              onClick={() => reopen(reopenRows, openTabs)}
            >
              Reopen and fill selected ({reopenRows.length})
            </button>
            {ids.length > continueIds.length && (
              <span className="ml-auto text-xs text-ink-muted">
                {ids.length - continueIds.length} selected cannot Continue
                {ids.length > reopenRows.length
                  ? "; " + (ids.length - reopenRows.length) + " cannot Reopen"
                  : ""}
              </span>
            )}
          </div>
        )}
        {!!ids.length && (
          <div className="flex flex-wrap items-center gap-3 rounded-md bg-accent-soft p-2 text-sm">
            <strong>{ids.length} selected</strong>
            <button onClick={() => state.setSelected(new Set())}>Clear</button>
            {archived ? (
              <button disabled={busy || active} onClick={() => void move(ids, false)}>
                Restore selected
              </button>
            ) : (
              <button disabled={busy || active} onClick={() => void move(ids, true)}>
                Archive selected
              </button>
            )}
          </div>
        )}
        {pagination}
        <DataTable
          rows={rows}
          id={(row) => row.source_job_id}
          columns={cols}
          selected={state.selected}
          onSelected={state.setSelected}
          sort={state.sort}
          direction={state.direction}
          onSort={(id) =>
            state.change({
              sort: id,
              direction: state.sort === id && state.direction === "asc" ? "desc" : "asc",
            })
          }
          loading={state.loading}
          error={state.error}
          empty={
            state.q || state.status ? (
              <>
                {archived
                  ? "No archived applications match these filters."
                  : scope === "review"
                    ? "No applications needing review match these filters."
                    : "No working applications match these filters."}{" "}
                <button
                  className="mt-2 block w-full text-accent underline"
                  onClick={() => state.change({ q: "", status: "" })}
                >
                  Clear filters
                </button>
              </>
            ) : archived ? (
              "Archived applications will appear here."
            ) : (
              <>
                No working applications.{" "}
                <button className="text-accent underline" onClick={() => void start("find")}>
                  Find jobs
                </button>
                {archiveTotal > 0 && (
                  <button
                    className="ml-2 text-accent underline"
                    onClick={() =>
                      setParams((previous) => {
                        const next = new URLSearchParams(previous);
                        next.set("archive_open", "1");
                        return next;
                      })
                    }
                  >
                    See archived applications
                  </button>
                )}
              </>
            )
          }
        />
        {pagination}
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-semibold">Applications</h1>
          <p className="text-sm text-ink-muted">
            Find jobs, prepare tailored files, and track each application.
          </p>
        </div>
      </header>
      <ProfileGapsNotice gaps={profileGaps} />
      <details className="rounded-lg border border-line bg-panel p-4">
        <summary className="cursor-pointer font-semibold">
          Apply settings ·{" "}
          {settings.apply.auto_submit_enabled ? "Auto-submit verified forms" : "Stop for review"} ·{" "}
          <ConnectionStatus connected={browserConnected} />
        </summary>
        <div className="mt-3 space-y-4 text-sm">
          <section className="border-t border-line pt-3">
            <h3 className="font-medium">Discovery</h3>
            <div className="mt-2 flex flex-wrap gap-4">
              <label>
                Discovery limit{" "}
                <input
                  className="ml-2 w-20 rounded border border-line px-2"
                  type="number"
                  min={1}
                  max={500}
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={dryRun}
                  onChange={(e) => setDryRun(e.target.checked)}
                />{" "}
                Dry run · record discoveries without preparing
              </label>
            </div>
          </section>
          <section className="border-t border-line pt-3">
            <h3 className="font-medium">Autofill</h3>
            <div className="mt-2 flex flex-wrap gap-4">
              <label>
                <input
                  type="checkbox"
                  checked={settings.apply.auto_submit_enabled}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      apply: { ...settings.apply, auto_submit_enabled: e.target.checked },
                    })
                  }
                />{" "}
                Auto-submit verified forms
              </label>
              <label>
                Submission cap{" "}
                <input
                  className="ml-2 w-20 rounded border border-line px-2"
                  type="number"
                  min={0}
                  max={500}
                  value={settings.apply.auto_submit_max_per_run}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      apply: { ...settings.apply, auto_submit_max_per_run: Number(e.target.value) },
                    })
                  }
                />
              </label>
              <label>
                Provider{" "}
                <select
                  className="ml-2 rounded border border-line bg-panel px-2"
                  value={settings.apply.model_provider}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      apply: {
                        ...settings.apply,
                        model_provider: e.target.value as typeof settings.apply.model_provider,
                      },
                    })
                  }
                >
                  <option value="ollama">Ollama</option>
                  <option value="lmstudio">LM Studio</option>
                  <option value="gemini">Gemini</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </label>
              <label>
                Model{" "}
                <input
                  className="ml-2 rounded border border-line px-2"
                  value={settings.apply.model_name}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      apply: { ...settings.apply, model_name: e.target.value },
                    })
                  }
                />
              </label>
            </div>
            <p className="mt-2 text-xs text-ink-muted">
              Tailoring:{" "}
              <Link className="text-accent underline" to="/">
                {tailorModelLabel(settings, config)}
              </Link>
              . This model is configured on Tailor.
            </p>
          </section>
          <section className="border-t border-line pt-3">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="font-medium">Browser connection</h3>
              <ConnectionStatus connected={browserConnected} />
              <button
                className="rounded-md border border-line px-3 text-sm"
                onClick={() =>
                  void getBrowserStatus()
                    .then((result) => setBrowserConnected(result.reachable))
                    .catch((reason) => setError(String(reason)))
                }
              >
                Check connection
              </button>
            </div>
            <BrowserCommand />
          </section>
        </div>
      </details>
      {error && (
        <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
          {error}
        </p>
      )}
      {notice && (
        <div role="status" className="rounded-md bg-accent-soft p-3 text-sm">
          {notice.ids.length} application{notice.ids.length === 1 ? "" : "s"}{" "}
          {notice.archived ? "archived" : "restored"}.{" "}
          <button
            className="underline"
            onClick={() => {
              void move(notice.ids, !notice.archived);
              setNotice(null);
            }}
          >
            Undo
          </button>
        </div>
      )}
      {active && (
        <p className="text-xs text-ink-muted">
          Archive, restore, and workflow actions become available when the current Apply operation
          finishes.
        </p>
      )}
      {operation && (
        <ApplicationProgress
          operation={operation}
          onControl={(action) => {
            void controlApplyOperation(operation.operation_id, action)
              .then(setOperation)
              .catch((reason) => setError(String(reason)))
              .finally(() => wakePollRef.current());
          }}
        />
      )}
      {reviewTable.data?.total || reviewTable.q || reviewTable.status ? (
        <CollapsibleSection
          className="border-warn/40 bg-warn-soft/30"
          title={`Needs your review (${reviewTable.data?.total ?? 0})`}
          description="Filled applications waiting on you: a flagged answer, a sign-in, or a final check before submitting."
          open={reviewOpen}
          onToggle={() => {
            if (reviewOpen) reviewTable.setSelected(new Set());
            toggleParam("review_closed", reviewOpen);
          }}
        >
          {renderTable("review")}
        </CollapsibleSection>
      ) : null}
      <CollapsibleSection
        className="border-line"
        title={`Working applications (${queue.data?.total ?? 0})`}
        open={queueOpen}
        onToggle={() => {
          if (queueOpen) queue.setSelected(new Set());
          toggleParam("queue_closed", queueOpen);
        }}
      >
        {renderTable("queue")}
      </CollapsibleSection>
      <CollapsibleSection
        className="border-line bg-panel"
        title={`Archived applications (${archiveTotal})`}
        open={archiveOpen}
        onToggle={() => {
          if (archiveOpen) archive.setSelected(new Set());
          toggleParam("archive_open", !archiveOpen);
        }}
      >
        {renderTable("archive")}
      </CollapsibleSection>
    </div>
  );
}

/** A table section whose header toggles its body; the heading (with its count) stays visible when closed. */
function CollapsibleSection({
  title,
  description,
  open,
  onToggle,
  className,
  children,
}: {
  title: string;
  description?: string;
  open: boolean;
  onToggle: () => void;
  className: string;
  children: ReactNode;
}) {
  return (
    <section className={`rounded-lg border p-4 ${className}`}>
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 text-left"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span>
          <span className="block text-lg font-semibold">{title}</span>
          {description && <span className="block text-sm text-ink-muted">{description}</span>}
        </span>
        <span aria-hidden className="text-lg font-semibold">
          {open ? "−" : "+"}
        </span>
      </button>
      {open && <div className="mt-4">{children}</div>}
    </section>
  );
}

/** Green/red connection dot with a text label — colour is never the only signal. */
function ConnectionStatus({ connected }: { connected: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-sm font-medium ${connected ? "text-success" : "text-danger"}`}
    >
      <span
        aria-hidden
        className={`size-2.5 rounded-full ${connected ? "bg-success" : "bg-danger"}`}
      />
      {connected ? "Connected" : "Disconnected"}
    </span>
  );
}

const OS_LABELS: Record<DesktopOs, string> = { windows: "Windows", mac: "macOS", linux: "Linux" };

/** The Edge remote-debugging command for the viewer's OS, with tabs for the others. */
function BrowserCommand() {
  const [os, setOs] = useState<DesktopOs>(() => detectOs());
  const { shell, command } = EDGE_DEBUG_COMMANDS[os];
  return (
    <>
      <div role="tablist" aria-label="Operating system" className="mt-2 flex gap-1">
        {(Object.keys(OS_LABELS) as DesktopOs[]).map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={os === key}
            className={`rounded-md px-2 py-0.5 text-xs ${os === key ? "bg-accent-soft font-medium" : "text-ink-muted"}`}
            onClick={() => setOs(key)}
          >
            {OS_LABELS[key]}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        For browser-assisted Fill, run this in {shell} to start Edge with remote debugging on port
        9222, then check the connection. Keep the browser open while reviewing forms, and use this
        Edge profile only for job-site logins.
      </p>
      <div className="mt-2 flex items-start gap-2">
        <code className="min-w-0 flex-1 rounded-md bg-paper px-3 py-2 font-mono text-xs [overflow-wrap:anywhere]">
          {command}
        </code>
        <CopyButton label="Copy command" text={command} />
      </div>
    </>
  );
}
