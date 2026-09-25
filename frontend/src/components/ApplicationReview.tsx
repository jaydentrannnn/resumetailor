import { useState } from "react";
import type { ApplicationRow, ApplyFieldOutcome, ApplyReviewField } from "../api";
import { AttachmentResults } from "./AttachmentResults";
import { FieldCorrectionRow } from "./FieldCorrectionRow";
import { MissingProfileFields } from "./MissingProfileFields";
import { Pagination } from "./TableControls";
import { answerSourceLabel } from "../lib/answerSource";
import { reviewGroup, type ReviewGroup } from "../lib/reviewGroups";

type ReviewEntry = { key: string; field?: ApplyReviewField; outcome?: ApplyFieldOutcome };
const groupLabels: Record<ReviewGroup, string> = {
  attention: "Needs attention",
  optional: "Optional unanswered",
  generated: "Generated answers",
  verified: "Verified / preserved",
  unknown: "Verification not recorded",
};

export function reviewErrorMessage(message: string): string {
  if (message.includes("stale_snapshot"))
    return "This field changed in the browser. Refresh fields, review its current answer, then try the correction again.";
  if (/worker.*busy|operation.*active|already.*running/i.test(message))
    return "Another Apply operation is running. Refresh and correction actions become available when it finishes.";
  return message;
}

export function ApplicationReview({
  application,
  disabled,
  error,
  onRefresh,
  onCorrect,
  tabClosed = false,
}: {
  application: ApplicationRow;
  disabled: boolean;
  /** The recorded tab is known to be closed: nothing left to refresh. */
  tabClosed?: boolean;
  error?: string | null;
  onRefresh: () => void;
  onCorrect: (field: ApplyReviewField, value: string | null, optionIds: string[]) => void;
}) {
  const [filter, setFilter] = useState<ReviewGroup | "all" | null>(null);
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(25);
  const fill = application.fill;
  if (!fill) return null;
  const outcomes = fill.field_outcomes ?? [];
  const fields = fill.review_fields ?? [];
  const usedOutcomes = new Set<ApplyFieldOutcome>();
  const entries: ReviewEntry[] = fields.map((field) => {
    const matching = outcomes.filter(
      (item) =>
        item.field_id === field.field_id &&
        (!field.frame_id || !item.frame_id || field.frame_id === item.frame_id),
    );
    const outcome = matching.length === 1 ? matching[0] : undefined;
    if (outcome) usedOutcomes.add(outcome);
    return {
      key: `${fill.review_snapshot_id}:${field.frame_id}:${field.field_id}:${field.expected_state_hash}`,
      field,
      outcome,
    };
  });
  outcomes.forEach((outcome, index) => {
    if (!usedOutcomes.has(outcome))
      entries.push({
        key: `outcome:${outcome.step_id}:${outcome.frame_id}:${outcome.field_id}:${index}`,
        outcome,
      });
  });
  const attentionCount = entries.filter(
    (entry) => reviewGroup(entry.field, entry.outcome) === "attention",
  ).length;
  const activeFilter = filter ?? (attentionCount ? "attention" : "all");
  const visible =
    activeFilter === "all"
      ? entries
      : entries.filter((entry) => reviewGroup(entry.field, entry.outcome) === activeFilter);
  const pageRows = visible.slice(page * size, (page + 1) * size);
  function renderEntry(entry: ReviewEntry) {
    if (entry.field && fill?.review_snapshot_id)
      return (
        <FieldCorrectionRow
          key={entry.key}
          field={entry.field}
          outcome={entry.outcome}
          disabled={disabled}
          onCorrect={onCorrect}
        />
      );
    const item = entry.outcome;
    return (
      <li key={entry.key} className="rounded border border-line p-2 text-xs text-ink-muted">
        <p className="font-medium text-ink">
          {item?.label || entry.field?.label || "Unlabeled field"} ·{" "}
          {(item?.required ?? entry.field?.required) == null
            ? "Requirement not recorded"
            : (item?.required ?? entry.field?.required)
              ? "Required"
              : "Optional"}
        </p>
        <p className="mt-1 line-clamp-3 whitespace-pre-wrap">
          {item?.observed_value || item?.value || entry.field?.current_value || "Blank"} ·{" "}
          {item?.reason_text ||
            item?.reason_code?.replaceAll("_", " ") ||
            item?.state?.replaceAll("_", " ") ||
            "Verification not recorded"}
        </p>
        {item?.answer_source && <p>Source: {answerSourceLabel(item.answer_source)}</p>}
        <details>
          <summary>Full recorded answer</summary>
          <p className="whitespace-pre-wrap">
            {item?.observed_value || item?.value || entry.field?.current_value || "Blank"}
          </p>
        </details>
      </li>
    );
  }
  const confirmed = application.status === "submitted";
  const summary = confirmed
    ? "Submitted"
    : application.status === "submit_unconfirmed"
      ? "Submission unconfirmed — check the browser before taking another action"
      : fill.ready_to_submit
        ? "Ready for review"
        : "Review needed";
  return (
    <div className="rounded-md border border-line bg-bg p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
          Observed Fill Result
        </h3>
        {fill.browser_target_id && !tabClosed && (
          <button
            type="button"
            className="rounded border border-line px-2 py-1 text-xs disabled:opacity-50"
            disabled={disabled}
            onClick={onRefresh}
          >
            Refresh fields
          </button>
        )}
      </div>
      {disabled && (
        <p className="mt-2 text-xs text-ink-muted">
          Refresh fields and corrections are available when the current Apply operation finishes.
          You can still use Review tab for completed applications.
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {reviewErrorMessage(error)}
        </p>
      )}
      <p className="mt-2 text-sm font-medium text-ink">{summary}</p>
      {(fill.error || fill.handoff_reason) && (
        <details className="mt-1 text-xs text-ink-muted">
          <summary>Recorded attempt notes</summary>
          <p>{fill.error || fill.handoff_reason}</p>
        </details>
      )}
      <MissingProfileFields items={fill.missing_profile ?? []} />
      {entries.length > 0 ? (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap gap-2 text-xs">
            <button
              className={activeFilter === "all" ? "font-semibold text-accent" : ""}
              onClick={() => {
                setFilter("all");
                setPage(0);
              }}
            >
              All recorded fields ({entries.length})
            </button>
            {(Object.keys(groupLabels) as ReviewGroup[]).map((group) => {
              const count = entries.filter(
                (entry) => reviewGroup(entry.field, entry.outcome) === group,
              ).length;
              return count ? (
                <button
                  key={group}
                  className={activeFilter === group ? "font-semibold text-accent" : ""}
                  onClick={() => {
                    setFilter(group);
                    setPage(0);
                  }}
                >
                  {groupLabels[group]} ({count})
                </button>
              ) : null;
            })}
          </div>
          <Pagination
            page={page}
            size={size}
            total={visible.length}
            onPage={setPage}
            onSize={(value) => {
              setSize(value);
              setPage(0);
            }}
          />
          <ul className="space-y-2">{pageRows.map(renderEntry)}</ul>
          <Pagination
            page={page}
            size={size}
            total={visible.length}
            onPage={setPage}
            onSize={(value) => {
              setSize(value);
              setPage(0);
            }}
          />
        </div>
      ) : (
        <div className="mt-2 space-y-1 text-xs text-ink-muted">
          {(fill.required_empty?.length ?? 0) > 0 && (
            <p className="text-danger">Missing: {fill.required_empty?.join(", ")}</p>
          )}
          {fill.leftovers?.map((item, index) => (
            <p key={`${item.label}-${index}`}>
              {item.required ? "Required" : "Optional"}: {item.label || "Unlabeled field"} —{" "}
              {item.reason || "Needs review"}
            </p>
          ))}
          {!fill.leftovers?.length && !fill.required_empty?.length && (
            <p>
              No field-level verification was recorded for this attempt. Refresh fields to inspect
              the current page.
            </p>
          )}
        </div>
      )}
      <AttachmentResults uploads={fill.uploads ?? []} />
    </div>
  );
}
