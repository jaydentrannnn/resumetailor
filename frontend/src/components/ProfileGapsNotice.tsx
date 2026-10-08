import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ProfileGap } from "../api";
import { buttonClass, StatusChip } from "./ui";

/**
 * An inline "needs you" row: an attention chip naming the subject, one line of text and
 * the action that fixes it. Set off by a blue left rule instead of a tinted box.
 */
export function AttentionRow({
  label,
  action,
  children,
  role,
}: {
  label: string;
  action?: ReactNode;
  children: ReactNode;
  role?: "status";
}) {
  return (
    <div
      role={role}
      className="flex flex-wrap items-center gap-x-3.5 gap-y-2.5 rounded-sm border border-l-2 border-line border-l-attn bg-panel px-4 py-3 text-[13px]"
    >
      <StatusChip tone="attention" className="shrink-0">
        {label}
      </StatusChip>
      <p className="min-w-0 flex-[1_1_260px] text-ink-2">{children}</p>
      {action}
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
      action={
        <Link
          className={buttonClass("secondary", "sm", "rt-row-action")}
          to={gaps[0].path}
          title="Set them in your profile"
        >
          Set up
        </Link>
      }
    >
      Autofill will skip questions your profile leaves blank: {shown}
      {more}.
    </AttentionRow>
  );
}
