import { useId } from "react";
import { Link } from "react-router-dom";
import type { AttentionItem } from "../../api";
import { buttonClass, StatusChip, type Tone } from "../../components/ui";
import { attentionSummary } from "../../lib/applyPage";

const names: Record<AttentionItem["kind"], string> = {
  failed: "error",
  needs_input: "needs review",
  ready_for_review: "ready for final check",
  blocked: "blocked",
};

const tones: Record<AttentionItem["kind"], Tone> = {
  failed: "failed",
  needs_input: "attention",
  ready_for_review: "attention",
  blocked: "attention",
};

const when = (at: string) => {
  const date = new Date(at);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
};

/**
 * What a run left for the user, newest first: the posting, why it needs them (a status
 * chip plus the run's message), since when, and Review (its review tab). Renders nothing
 * when the run left nothing. `collapsible` (the sticky operation banner) folds it into a
 * closed "Needs attention (n)" disclosure with a height cap, so a long list never
 * covers the page under the banner.
 */
export function AttentionList({
  items = [],
  collapsible = false,
}: {
  items?: AttentionItem[];
  collapsible?: boolean;
}) {
  const summaryId = useId();
  if (!items.length) return null;
  const ordered = [...items].sort((a, b) => b.at.localeCompare(a.at));
  const summary = attentionSummary(ordered);
  if (!collapsible) return <AttentionTable items={ordered} caption={summary} />;
  return (
    <details>
      <summary
        id={summaryId}
        className="rt-row-action -ml-2 inline-flex cursor-pointer items-center rounded-sm px-2 text-xs font-medium text-ink-2 hover:bg-sunken hover:text-ink"
      >
        {summary}
      </summary>
      <div className="mt-2 max-h-56 overflow-y-auto">
        <AttentionTable items={ordered} labelledBy={summaryId} />
      </div>
    </details>
  );
}

function AttentionTable({
  items,
  caption,
  labelledBy,
}: {
  items: AttentionItem[];
  caption?: string;
  labelledBy?: string;
}) {
  return (
    <table className="w-full table-fixed text-left text-[13px]" aria-labelledby={labelledBy}>
      {caption && <caption className="mb-2 text-left text-xs text-ink-muted">{caption}</caption>}
      <thead className="border-b border-line-hover">
        <tr>
          <th className="rt-eyebrow w-[34%] py-2 pr-3">Application</th>
          <th className="rt-eyebrow py-2 pr-3">Why it needs you</th>
          <th className="rt-eyebrow hidden w-40 py-2 pr-3 sm:table-cell">Waiting since</th>
          <th className="w-24 py-2">
            <span className="sr-only">Action</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.application_id} className="border-b border-line last:border-0">
            <td className="py-2.5 pr-3 align-top font-medium text-ink [overflow-wrap:anywhere]">
              {item.label}
            </td>
            <td className="py-2.5 pr-3 align-top">
              <StatusChip tone={tones[item.kind]}>{names[item.kind]}</StatusChip>
              {item.kind !== "ready_for_review" && item.message && (
                <p className="mt-1 text-xs text-ink-muted [overflow-wrap:anywhere]">
                  {item.message}
                </p>
              )}
            </td>
            <td className="hidden py-2.5 pr-3 align-top font-mono text-xs text-ink-muted sm:table-cell">
              {when(item.at)}
            </td>
            <td className="py-2 text-right align-top">
              <Link
                aria-label={`Review ${item.label}`}
                className={buttonClass("secondary", "sm", "rt-row-action")}
                to={`/applications/${encodeURIComponent(item.application_id)}?tab=review`}
              >
                Review
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
