import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ProfileGap } from "../api";
import { buttonClass, StatusChip, TruncatedText } from "./ui";

/**
 * An inline "needs you" row: an attention chip naming the subject, one line of text (the
 * rest a click away) and the action that fixes it, kept on the right. Set off by an
 * orange left rule instead of a tinted box.
 */
export function AttentionRow({
  label,
  action,
  text,
  role,
}: {
  label: string;
  action?: ReactNode;
  text: string;
  role?: "status";
}) {
  return (
    <div
      role={role}
      className="flex items-center gap-3.5 rounded-sm border border-l-2 border-line border-l-attn bg-panel px-4 py-3 text-[13px]"
    >
      <StatusChip tone="attention" className="shrink-0">
        {label}
      </StatusChip>
      <div className="min-w-0 flex-1">
        <TruncatedText className="text-ink-2" text={text} label={label} />
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
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
    <AttentionRow
      role="status"
      label="Profile gaps"
      text={`Autofill will skip questions your profile leaves blank: ${shown}${more}.`}
      action={
        <Link
          className={buttonClass("secondary", "sm", "rt-row-action")}
          to={gaps[0].path}
          title="Set them in your profile"
        >
          Set up
        </Link>
      }
    />
  );
}
