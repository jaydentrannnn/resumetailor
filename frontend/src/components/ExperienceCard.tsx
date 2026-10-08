import { useEffect, useState } from "react";
import type { ExpandedEntry, Expansion } from "../api";
import { expansionUrl } from "../api";
import { buttonClass } from "../lib/buttonClass";
import { ResultFrame } from "../pages/run/ResultFrame";
import { CopyButton } from "./CopyButton";

function bulletsText(bullets: string[]): string {
  /** Join bullets the way most application forms expect pasted lists. */
  return bullets.map((b) => `• ${b}`).join("\n");
}

function headerText(entry: ExpandedEntry): string {
  /** Title / company / location / dates for the form's separate hard-fact fields. */
  const parts = [
    entry.title,
    entry.company,
    entry.location,
    `${entry.start} – ${entry.end}`,
  ].filter(Boolean);
  return parts.join(" · ");
}

function entryBlock(entry: ExpandedEntry): string {
  /** One entry as a self-contained paste block. */
  const body = bulletsText(entry.bullets);
  return body ? `${headerText(entry)}\n\n${body}` : headerText(entry);
}

function EntryBlock({
  entry,
  charLimit,
  open,
  onToggle,
}: {
  entry: ExpandedEntry;
  charLimit: number;
  open: boolean;
  onToggle: () => void;
}) {
  /** One experience entry as an accordion row; copy actions stay on the header. */
  const over = entry.char_count > charLimit;
  const meta = [entry.location, `${entry.start} – ${entry.end}`].filter(Boolean).join(" · ");

  return (
    <article className="border-t border-line first:border-t-0">
      <div className="flex flex-wrap items-start gap-2 py-3">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="min-w-0 flex-1 text-left"
        >
          <h4 className="font-medium leading-snug">
            <span className="mr-1.5 inline-block w-3 text-ink-muted" aria-hidden>
              {open ? "▾" : "▸"}
            </span>
            {entry.title}
            <span className="text-ink-muted"> · {entry.company}</span>
          </h4>
          <p className="mt-0.5 pl-4 text-xs text-ink-muted">
            {meta}
            {entry.on_resume ? " · on resume" : ""}
            {" · "}
            {entry.bullets.length} bullet{entry.bullets.length === 1 ? "" : "s"}
            {" · "}
            <span className={over ? "font-mono font-medium text-danger" : "font-mono"}>
              {entry.char_count}/{charLimit} chars
            </span>
          </p>
        </button>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <CopyButton label="Copy entry" text={entryBlock(entry)} />
          <CopyButton label="Copy header" text={headerText(entry)} />
          <CopyButton label="Copy bullets" text={bulletsText(entry.bullets)} />
        </div>
      </div>

      {open && (
        <div className="pb-4 pl-4">
          <ul className="space-y-1.5 text-sm leading-relaxed">
            {entry.bullets.map((b, i) => (
              <li key={`${entry.entry_key}-${i}`} className="flex gap-2">
                <span className="shrink-0 text-ink-muted">•</span>
                <span>{b}</span>
              </li>
            ))}
          </ul>

          {over && (
            <p className="mt-3 text-xs font-medium text-danger">
              Over the field limit — trim before pasting
            </p>
          )}

          {entry.warnings.map((w) => (
            <p key={w} className="mt-1 text-xs text-attn">
              {w}
            </p>
          ))}
        </div>
      )}
    </article>
  );
}

/**
 * Copy-paste tile for expanded application-form experience descriptions, spanning
 * the full results width above Skills to list and the report on the Tailor page.
 *
 * Entries collapse into an accordion (first open) so a long list does not stretch the page.
 */
export function ExperienceCard({
  expansion,
  jobId,
  embedded = false,
}: {
  expansion: Expansion;
  jobId: string;
  /** Inside the Tailor page's "Last result" tile: no box of its own. */
  embedded?: boolean;
}) {
  const firstKey = expansion.entries[0]?.entry_key ?? null;
  const [openKey, setOpenKey] = useState<string | null>(firstKey);

  // A new run's expansion replaces the previous one; reopen the first entry.
  useEffect(() => {
    setOpenKey(firstKey);
  }, [firstKey, expansion]);

  if (!expansion.entries.length) {
    return (
      <ResultFrame embedded={embedded} title="Application experience">
        <p className="text-sm text-ink-muted">No experience entries were expanded for this run.</p>
      </ResultFrame>
    );
  }

  const allText = expansion.entries.map(entryBlock).join("\n\n---\n\n");

  return (
    <ResultFrame
      embedded={embedded}
      title="Application experience"
      description="Expanded descriptions for application-form paste fields. Hard facts match the master resume; bullets are longer than the one-pager allows."
      actions={
        <>
          <CopyButton label="Copy all" text={allText} />
          <a href={expansionUrl(jobId)} className={buttonClass("secondary", "sm")}>
            Download .md
          </a>
        </>
      }
    >
      <div>
        {expansion.entries.map((entry) => (
          <EntryBlock
            key={entry.entry_key}
            entry={entry}
            charLimit={expansion.char_limit}
            open={openKey === entry.entry_key}
            onToggle={() =>
              setOpenKey((prev) => (prev === entry.entry_key ? null : entry.entry_key))
            }
          />
        ))}
      </div>

      {expansion.warnings.map((w) => (
        <p key={w} className="mt-3 text-sm text-attn">
          {w}
        </p>
      ))}

      <p className="mt-3 text-xs text-ink-muted">
        Model: <span className="font-mono">{expansion.model}</span>
      </p>
    </ResultFrame>
  );
}
