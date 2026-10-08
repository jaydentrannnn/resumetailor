import type { ReactNode } from "react";
import { Link, type NavigateFunction } from "react-router-dom";
import type { ApplicationRow } from "../../api";
import { RowActionsMenu, type MenuItem, type TableColumn } from "../../components/TableControls";
import { buttonClass, Meter, StatusChip, type ButtonVariant } from "../../components/ui";
import { applicationStatusLabel, applicationStatusTone } from "../../lib/applicationStatus";
import {
  canContinueFill,
  canFillAfterReview,
  canReopenFill,
  isTabClosed,
  retryShortLabel,
  retryTitle,
} from "../../lib/applicationRows";
import { REVIEW_STATUSES, TERMINAL_STATUSES, canRetailor, reviewReason } from "../../lib/applyPage";
import { CapturedBadge } from "../CapturedStubs";
import type { TableActions } from "./ApplicationsTable";
import { PostedDate, WaitingSince } from "./PostedDate";
import type { Scope } from "./useApplicationTable";

// One fixed box for every row action, <button> or <Link>: same width so the column
// lines up, one line (short labels; the full wording is the tooltip), and the compact
// `rt-row-action` height.
const action = (variant: ButtonVariant) =>
  buttonClass(variant, "sm", "rt-row-action w-[5.5rem] shrink-0 whitespace-nowrap px-2");
// A retry after a failure is a red outline; the same button as a routine next step
// (e.g. "Fetch JD" on a newly discovered row) is an ordinary secondary button.
const retryVariant = (status: string): ButtonVariant =>
  applicationStatusTone(status) === "failed" ? "danger" : "secondary";

/** The row's overflow menu: files, links and every action that is not the primary one. */
function rowMenu(row: ApplicationRow, archived: boolean, actions: TableActions): MenuItem[] {
  const { busy, active, openTabs } = actions;
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
        label: row.status === "submitted" ? "Restore (undo submitted)" : "Restore",
        disabled: busy || active,
        action: () => actions.move([row.source_job_id], false),
        description: "Available when Apply is idle",
      },
    ];
  if (["submitted", "skipped"].includes(row.status))
    items.push({
      label: "Not submitted — move back",
      disabled: busy || active,
      action: () => actions.undo(row),
    });
  if (canRetailor(row))
    items.push({
      label: "Tailor files again",
      disabled: busy || active,
      action: () => actions.retailor([row]),
      description: "Available when Apply is idle",
    });
  const tabOpen = !!row.fill?.browser_target_id && !isTabClosed(row, openTabs);
  if (tabOpen) items.push({ label: "Open application tab", action: () => actions.focusTab(row) });
  if (tabOpen && !["submitted", "filling", "submit_unconfirmed"].includes(row.status))
    items.push({
      label: "Continue fill",
      disabled: busy || active || !canFillAfterReview(row),
      action: () => actions.start("fill", [row.source_job_id], "continue"),
    });
  if (canReopenFill(row))
    items.push({
      label: "Reopen and fill",
      disabled: busy || active,
      action: () => actions.reopen([row]),
    });
  if (["awaiting_review", "awaiting_otp", "submit_unconfirmed"].includes(row.status))
    items.push({ label: "Mark submitted", action: () => actions.mark(row, "submitted") });
  if (!TERMINAL_STATUSES.has(row.status))
    items.push({ label: "Skip", action: () => actions.mark(row, "skipped"), danger: true });
  return [
    ...items,
    {
      label: "Archive",
      disabled: busy || active,
      action: () => actions.move([row.source_job_id], true),
      description: "Available when Apply is idle",
    },
  ];
}

/** The row's next step as one button (Continue / Reopen / Fill / Retry / Review / View) plus its menu. */
function RowAction({
  row,
  archived,
  actions,
  navigate,
}: {
  row: ApplicationRow;
  archived: boolean;
  actions: TableActions;
  navigate: NavigateFunction;
}) {
  const { busy, active, browserConnected, openTabs } = actions;
  const needsYou = !archived && REVIEW_STATUSES.has(row.status);
  const reason = needsYou ? reviewReason(row) : null;
  const retryLabel =
    !archived &&
    !TERMINAL_STATUSES.has(row.status) &&
    !REVIEW_STATUSES.has(row.status) &&
    row.retry_kind
      ? retryShortLabel(row.retry_kind, row.status)
      : null;
  const kind: "continue" | "reopen" | "review" | "fill" | "retry" | "view" =
    archived || TERMINAL_STATUSES.has(row.status)
      ? "view"
      : needsYou
        ? canContinueFill(row, openTabs)
          ? "continue"
          : isTabClosed(row, openTabs) && canReopenFill(row)
            ? "reopen"
            : "review"
        : row.status === "ready" && canFillAfterReview(row)
          ? "fill"
          : retryLabel
            ? "retry"
            : "view";
  // The primary action is left out of the menu; Review stays one menu item away
  // when Continue or Reopen takes its place.
  const primaryLabel =
    kind === "continue"
      ? "Continue fill"
      : kind === "reopen"
        ? "Reopen and fill"
        : kind === "fill"
          ? "Fill"
          : null;
  const items = [
    ...(kind === "continue" || kind === "reopen"
      ? [{ label: "Review", action: () => navigate(actions.detail(row, "review")) }]
      : []),
    ...rowMenu(row, archived, actions).filter((item) => item.label !== primaryLabel),
  ];
  const needsBrowser = "Connect the browser in Apply settings first";
  let primary: ReactNode;
  if (kind === "continue")
    primary = (
      <button
        type="button"
        className={action("secondary")}
        title={browserConnected ? "Continue the fill in its open tab" : needsBrowser}
        disabled={busy || active || !browserConnected}
        onClick={() => actions.start("fill", [row.source_job_id], "continue")}
      >
        Continue
      </button>
    );
  else if (kind === "reopen")
    primary = (
      <button
        type="button"
        className={action("secondary")}
        title="The tab was closed: open the posting again and fill it from the start"
        disabled={busy || active || !browserConnected}
        onClick={() => actions.reopen([row])}
      >
        Reopen
      </button>
    );
  else if (kind === "fill")
    primary = (
      <button
        type="button"
        className={action("secondary")}
        title={browserConnected ? "Open the posting and fill the form" : needsBrowser}
        disabled={busy || active || !browserConnected}
        onClick={() => actions.start("fill", [row.source_job_id])}
      >
        Fill
      </button>
    );
  else if (kind === "retry")
    primary = (
      <button
        type="button"
        className={action(retryVariant(row.status))}
        title={row.retry_kind ? retryTitle(row.retry_kind) : undefined}
        disabled={busy || active}
        onClick={() => actions.retry(row)}
      >
        {retryLabel}
      </button>
    );
  else if (kind === "review" && reason?.profilePath)
    primary = (
      <Link to={reason.profilePath} title={reason.why} className={action("secondary")}>
        {reason.action}
      </Link>
    );
  else
    primary = (
      <Link
        to={actions.detail(row, kind === "review" ? "review" : "overview")}
        onClick={actions.rememberScroll}
        title={reason?.why}
        className={action(kind === "review" ? "secondary" : "ghost")}
      >
        {kind === "review" ? reason!.action : "View"}
      </Link>
    );
  return (
    <div className="flex flex-nowrap items-center justify-end gap-1">
      {primary}
      <RowActionsMenu label={`More actions for ${row.company} ${row.role}`} items={items} />
    </div>
  );
}

/** Matched skills as a number out of 100 with a mini meter; the raw count is the tooltip. */
function SkillMatch({ row }: { row: ApplicationRow }) {
  const total = row.screen?.coverage_total;
  if (!total) return <span className="text-xs text-ink-muted">Not checked</span>;
  const matched = row.screen!.coverage_matched;
  const pct = Math.round((matched / total) * 100);
  return (
    <span
      className="inline-flex items-center gap-2"
      title={`${matched} of ${total} skills matched`}
    >
      <span className="font-mono text-[13px] tabular-nums text-ink">{pct}</span>
      <Meter
        className="w-11"
        tone="ink"
        value={pct}
        label={`Skill match for ${row.company}`}
        valueText={`${matched} of ${total} skills matched`}
      />
    </span>
  );
}

const statusChip = (row: ApplicationRow) => (
  <StatusChip tone={applicationStatusTone(row.status)}>
    {applicationStatusLabel(row.status)}
  </StatusChip>
);

/**
 * The table's columns for one tab: company, posting, platform, status (or "Why it needs
 * you" on Needs you), skill match (In progress), the date, any optional columns picked,
 * and the next step.
 */
export function applicationColumns({
  scope,
  actions,
  extraColumns,
  navigate,
}: {
  scope: Scope;
  actions: TableActions;
  extraColumns: string[];
  navigate: NavigateFunction;
}): TableColumn<ApplicationRow>[] {
  const archived = scope === "archive";
  const dateColumn = archived ? "archived_at" : scope === "review" ? "status_at" : "posted_at";
  const coverage: TableColumn<ApplicationRow>[] =
    scope === "queue"
      ? [
          {
            id: "coverage",
            heading: "Skill match",
            sortable: true,
            className: "w-[10%]",
            cell: (row: ApplicationRow) => <SkillMatch row={row} />,
          },
        ]
      : [];
  const status: TableColumn<ApplicationRow> =
    scope === "review"
      ? {
          id: "status",
          heading: "Why it needs you",
          sortable: true,
          className: "w-[24%]",
          cell: (row) => (
            <>
              <p className="text-[13px] font-medium text-ink">{reviewReason(row).why}</p>
              <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                {statusChip(row)}
                {isTabClosed(row, actions.openTabs) && <span>Tab closed</span>}
              </p>
            </>
          ),
        }
      : {
          id: "status",
          heading: "Status",
          sortable: true,
          className: "w-[17%]",
          cell: (row) => (
            <>
              {statusChip(row)}
              {row.screen_label && (
                <p
                  className="mt-1 line-clamp-1 text-xs text-ink-muted"
                  title={row.screen?.reasons.join("; ")}
                >
                  {row.screen_label}
                </p>
              )}
              {row.error && !archived && (
                <p className="mt-1 line-clamp-1 text-xs text-danger" title={row.error}>
                  {row.error}
                </p>
              )}
            </>
          ),
        };
  const date: TableColumn<ApplicationRow> = {
    id: dateColumn,
    heading: archived ? "Done on" : scope === "review" ? "Waiting since" : "Posted",
    sortable: true,
    className: "w-[10%] font-mono text-xs text-ink-muted",
    cell: (row) => {
      if (scope === "review") return <WaitingSince at={row.status_at || row.discovered_at} />;
      if (!archived) return <PostedDate row={row} />;
      return row.archived_at ? new Date(row.archived_at).toLocaleDateString() : "—";
    },
  };
  return [
    {
      id: "company",
      heading: "Company",
      sortable: true,
      className: "w-[16%]",
      cell: (row) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <strong className="font-medium text-ink">{row.company}</strong>
          {!!row.resume_review?.warnings.length && (
            <p className="w-full text-xs text-attn" title={row.resume_review.warnings.join("\n")}>
              {row.resume_review.required ? "Resume needs review" : "Resume warnings reviewed"} ·{" "}
              {row.resume_review.warnings.join(" ")}
            </p>
          )}
          <CapturedBadge row={row} />
        </div>
      ),
    },
    {
      id: "role",
      heading: "Job posting",
      sortable: true,
      className: "w-[22%]",
      cell: (row) => (
        <>
          <Link
            className="text-ink-2 underline-offset-2 hover:text-ink hover:underline"
            to={actions.detail(row)}
            onClick={actions.rememberScroll}
          >
            {row.role}
          </Link>
          {row.location && <p className="text-xs text-ink-muted">{row.location}</p>}
        </>
      ),
    },
    {
      id: "ats",
      heading: "Platform",
      sortable: true,
      className: "w-[9%]",
      cell: (row) => <span className="text-ink-muted">{row.ats || "—"}</span>,
    },
    ...(scope === "review" ? [status, date] : [date, ...coverage, status]),
    ...extraColumns.map((id) => ({
      id,
      heading:
        id === "coverage"
          ? "Skill match"
          : id === "discovered_at"
            ? "Found"
            : id[0].toUpperCase() + id.slice(1),
      sortable: true,
      className: "w-[10%]",
      cell: (row: ApplicationRow) =>
        id === "sources" ? (
          [...new Set(row.sources)].join(", ")
        ) : id === "coverage" ? (
          <SkillMatch row={row} />
        ) : id === "discovered_at" ? (
          <span className="font-mono text-xs text-ink-muted">
            {row.discovered_at ? new Date(row.discovered_at).toLocaleDateString() : "—"}
          </span>
        ) : (
          String(row[id as "salary"] || "—")
        ),
    })),
    {
      id: "actions",
      heading: "Next step",
      className: "w-[19%] text-right",
      cell: (row) => (
        <RowAction row={row} archived={archived} actions={actions} navigate={navigate} />
      ),
    },
  ];
}
