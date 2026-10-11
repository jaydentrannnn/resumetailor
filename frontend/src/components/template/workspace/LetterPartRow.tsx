import { useId, type ReactNode } from "react";
import type { CoverLetterField, CoverLetterSettings } from "../../../api";
import { type LetterPart, partSummary } from "../../../lib/coverLetterSettings";
import { Switch } from "../../ui";

/**
 * One part of the letter: its name and what it prints, its on/off switch (always
 * visible), and — for a part with options, while it is on — a disclosure that opens them.
 */
export function LetterPartRow({
  part,
  settings,
  fields,
  open,
  onOpen,
  onChange,
  children,
}: {
  part: LetterPart;
  settings: CoverLetterSettings;
  fields: CoverLetterField[];
  open: boolean;
  onOpen: (open: boolean) => void;
  onChange: (next: CoverLetterSettings) => void;
  children?: ReactNode;
}) {
  const bodyId = useId();
  const block = part.block;
  const on = block ? settings.blocks[block] : true;
  const expandable = part.expands && on && Boolean(children);
  const shown = expandable && open;
  const name = (
    <span className="min-w-0">
      <span className={`block font-medium ${on ? "text-ink" : "text-ink-muted"}`}>
        {part.label}
      </span>
      <span className="block truncate text-xs text-ink-muted">
        {on ? partSummary(part, settings, fields) : "Not printed"}
      </span>
    </span>
  );
  return (
    <li className="border-t border-line py-3 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex items-center gap-3">
        {expandable ? (
          <button
            type="button"
            aria-expanded={shown}
            aria-controls={bodyId}
            onClick={() => onOpen(!open)}
            className="flex min-w-0 flex-1 items-start gap-2 text-left"
          >
            <span
              aria-hidden
              className={`mt-1 w-3 shrink-0 text-[10px] leading-none text-ink transition-transform ${shown ? "rotate-90" : ""}`}
            >
              ▶
            </span>
            {name}
          </button>
        ) : (
          <div className="flex min-w-0 flex-1 items-start gap-2">
            <span aria-hidden className="w-3 shrink-0" />
            {name}
          </div>
        )}
        {block && (
          <Switch
            label={part.label}
            checked={on}
            onChange={(next) =>
              onChange({ ...settings, blocks: { ...settings.blocks, [block]: next } })
            }
          />
        )}
      </div>
      {shown && (
        <div id={bodyId} className="mt-3 pl-5">
          {children}
        </div>
      )}
    </li>
  );
}
