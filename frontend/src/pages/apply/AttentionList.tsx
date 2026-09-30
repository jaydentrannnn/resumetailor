import { Link } from "react-router-dom";
import type { AttentionItem } from "../../api";

const names: Record<AttentionItem["kind"], string> = {
  failed: "error",
  needs_input: "needs review",
  ready_for_review: "ready for final check",
  blocked: "blocked",
};

export function AttentionList({ items = [] }: { items?: AttentionItem[] }) {
  const ordered = [...items].sort((a, b) => b.at.localeCompare(a.at));
  const counts = ordered.reduce(
    (result, item) => {
      result[item.kind] = (result[item.kind] ?? 0) + 1;
      return result;
    },
    {} as Partial<Record<AttentionItem["kind"], number>>,
  );
  const breakdown = (["failed", "needs_input", "ready_for_review", "blocked"] as const)
    .filter((kind) => counts[kind])
    .map(
      (kind) =>
        `${counts[kind]} ${kind === "failed" ? (counts[kind] === 1 ? "error" : "errors") : kind === "needs_input" ? "need review" : kind === "ready_for_review" ? "ready for final check" : "blocked"}`,
    )
    .join(" · ");
  return (
    <details
      className={`mt-3 border-t pt-2 text-xs ${ordered.length ? "border-warn/50 bg-warn-soft/30 text-ink" : "border-line text-ink-muted"}`}
    >
      <summary className="cursor-pointer font-medium">
        Needs attention ({ordered.length}){breakdown ? ` · ${breakdown}` : ""}
      </summary>
      {ordered.length > 0 && (
        <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto">
          {ordered.map((item) => (
            <li key={item.application_id}>
              <Link
                className="text-accent hover:underline"
                to={`/applications/${encodeURIComponent(item.application_id)}?tab=review`}
              >
                {item.label}
              </Link>
              {" — "}
              {names[item.kind]}
              {item.kind !== "ready_for_review" && item.message ? `: ${item.message}` : ""}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
