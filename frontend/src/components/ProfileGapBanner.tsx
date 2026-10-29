import { StatusMark, Tile } from "./ui";
import { buttonClass } from "../lib/buttonClass";
import type { ProfileGap } from "../api";

/** Blank profile fields application forms ask for; each opens the group that holds it. */
export function ProfileGapBanner({
  gaps,
  onOpen,
}: {
  gaps: ProfileGap[];
  onOpen: (section: string) => void;
}) {
  if (!gaps.length) return null;
  return (
    <Tile aria-label="Blank profile fields" className="text-sm">
      <p className="mb-1 flex items-center gap-2 font-semibold">
        <StatusMark tone="attention" />
        Forms ask for these, and your profile leaves them blank
      </p>
      <p className="text-xs text-ink-muted">
        Leave questions blank to answer them yourself on each form. Add an answer here to reuse it.
        For voluntary information, you can choose Decline to answer.
      </p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {gaps.map((gap) => (
          <li key={gap.key}>
            <button
              type="button"
              className={buttonClass("plain", "sm", "h-auto flex-wrap justify-start text-left")}
              onClick={() => onOpen(gap.section)}
            >
              {gap.label}
              <span className="text-ink-muted">
                {" "}
                · {gap.section}
                {gap.seen_in > 0
                  ? ` · met in ${gap.seen_in} application${gap.seen_in === 1 ? "" : "s"}`
                  : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Tile>
  );
}
