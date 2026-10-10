import { type ReactNode, useId, useState } from "react";
import type { IncludeOptions, ResumeOutlineSection } from "../api";
import {
  isEntryIncluded,
  isSectionIncluded,
  sectionSummary,
  toggleEntry,
  toggleSection,
} from "../lib/includeSections";
import { type SectionKind, SECTION_KIND_LABELS } from "../lib/resumeEdit";
import { Toggle } from "./Field";

const ARROW =
  "flex min-h-6 min-w-6 items-center justify-center rounded-sm border border-line-hover bg-field text-xs hover:border-ink disabled:opacity-30";

function entryHelp(kind: string, bullets: number, detail?: string): string | undefined {
  if (kind === "experience" || kind === "project") {
    return `${bullets} bullet${bullets === 1 ? "" : "s"}`;
  }
  return detail || undefined;
}

/**
 * One section in "What to include": a header row (expand chevron, title, summary,
 * include checkbox, reorder arrows) over its per-entry switches. Starts collapsed on
 * every mount; the summary keeps what is switched off visible while collapsed.
 * `extra` renders above the entries when expanded (Education's GPA/coursework).
 */
export function SectionIncludeRow({
  section,
  include,
  onInclude,
  canMoveUp,
  canMoveDown,
  onMove,
  extra,
}: {
  section: ResumeOutlineSection;
  include: IncludeOptions;
  onInclude: (patch: Partial<IncludeOptions>) => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMove: (direction: -1 | 1) => void;
  extra?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const included = isSectionIncluded(include, section.id);
  const expandable = section.entries.length > 0 || Boolean(extra);
  const summary = sectionSummary(include, section);
  const kindLabel = SECTION_KIND_LABELS[section.kind as SectionKind] ?? section.kind;

  return (
    <li>
      <div className="flex items-center gap-2 py-2 text-sm">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          disabled={!expandable}
          aria-expanded={expandable ? open : undefined}
          aria-controls={expandable ? bodyId : undefined}
          className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-default"
        >
          <span
            aria-hidden
            className={`w-3 shrink-0 text-[10px] leading-none text-ink transition-transform ${
              open ? "rotate-90" : ""
            }`}
          >
            {expandable ? "▶" : ""}
          </span>
          <span className={`truncate font-medium ${included ? "text-ink" : "text-ink-muted"}`}>
            {section.title}
          </span>
          {kindLabel.toLowerCase() !== section.title.trim().toLowerCase() && (
            <span className="shrink-0 text-xs text-ink-muted">{kindLabel}</span>
          )}
          {summary && (
            <span className="truncate text-xs text-ink-muted">· {summary}</span>
          )}
        </button>
        <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-ink-muted">
          <input
            type="checkbox"
            checked={included}
            onChange={(e) => onInclude(toggleSection(include, section.id, e.target.checked))}
            className="accent-[var(--color-accent)]"
          />
          Include
        </label>
        <button
          type="button"
          title="Move up"
          aria-label={`Move ${section.title} up`}
          disabled={!canMoveUp}
          onClick={() => onMove(-1)}
          className={ARROW}
        >
          ↑
        </button>
        <button
          type="button"
          title="Move down"
          aria-label={`Move ${section.title} down`}
          disabled={!canMoveDown}
          onClick={() => onMove(1)}
          className={ARROW}
        >
          ↓
        </button>
      </div>
      {open && expandable && (
        <div
          id={bodyId}
          className={`space-y-2 pb-3 pl-5 ${included ? "" : "opacity-60"}`}
        >
          {extra}
          {section.entries.map((entry) => {
            const help = entryHelp(section.kind, entry.bullets, entry.detail);
            return (
              <Toggle
                key={entry.id}
                label={entry.label}
                help={help}
                disabledHint={help}
                checked={isEntryIncluded(include, section.kind, entry.id)}
                disabled={!included}
                onChange={(v) => onInclude(toggleEntry(include, section.kind, entry.id, v))}
              />
            );
          })}
        </div>
      )}
    </li>
  );
}
