import { useEffect, useState } from "react";
import type { ExpandedEntry, Expansion } from "../api";
import { expansionUrl } from "../api";

/**
 * Copy `text` to the clipboard, with a hidden-textarea fallback for non-secure contexts.
 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.left = "-9999px";
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand("copy");
  } finally {
    document.body.removeChild(area);
  }
}

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

function CopyButton({
  label,
  text,
}: {
  label: string;
  text: string;
}) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    /** Copy `text` and briefly confirm success on the button. */
    const ok = await copyText(text);
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      type="button"
      onClick={() => void onCopy()}
      className="shrink-0 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink-muted hover:border-accent hover:text-accent"
    >
      {copied ? "Copied" : label}
    </button>
  );
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
  const meta = [entry.location, `${entry.start} – ${entry.end}`]
    .filter(Boolean)
    .join(" · ");

  return (
    <article className="rounded-lg border border-line bg-paper/40">
      <div className="flex items-start gap-2 p-4">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="min-w-0 flex-1 text-left"
        >
          <h3 className="font-medium leading-snug">
            <span className="mr-1.5 inline-block w-3 text-ink-muted" aria-hidden>
              {open ? "▾" : "▸"}
            </span>
            {entry.title}
            <span className="text-ink-muted"> · {entry.company}</span>
          </h3>
          <p className="mt-0.5 pl-4 text-xs text-ink-muted">
            {meta}
            {entry.on_resume ? " · on resume" : ""}
            {" · "}
            {entry.bullets.length} bullet{entry.bullets.length === 1 ? "" : "s"}
            {" · "}
            <span className={over ? "font-medium text-danger" : undefined}>
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
        <div className="border-t border-line px-4 pb-4 pt-3">
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
            <p key={w} className="mt-1 text-xs text-warn">
              {w}
            </p>
          ))}
        </div>
      )}
    </article>
  );
}

/**
 * Copy-paste tile for expanded application-form experience descriptions, sitting
 * beside the report on the Tailor page's final row.
 *
 * Entries collapse into an accordion (first open) so a long list does not stretch the page.
 */
export function ExperienceCard({
  expansion,
  jobId,
}: {
  expansion: Expansion;
  jobId: string;
}) {
  const firstKey = expansion.entries[0]?.entry_key ?? null;
  const [openKey, setOpenKey] = useState<string | null>(firstKey);

  // A new run's expansion replaces the previous one; reopen the first entry.
  useEffect(() => {
    setOpenKey(firstKey);
  }, [firstKey, expansion]);

  if (!expansion.entries.length) {
    return (
      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
        <h2 className="font-display text-xl font-semibold">Application experience</h2>
        <p className="mt-2 text-sm text-ink-muted">
          No experience entries were expanded for this run.
        </p>
      </section>
    );
  }

  const allText = expansion.entries.map(entryBlock).join("\n\n---\n\n");

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Application experience</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Expanded descriptions for application-form paste fields. Hard facts match
            the master resume; bullets are longer than the one-pager allows.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <CopyButton label="Copy all" text={allText} />
          <a
            href={expansionUrl(jobId)}
            className="shrink-0 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink-muted hover:border-accent hover:text-accent"
          >
            Download .md
          </a>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {expansion.entries.map((entry) => (
          <EntryBlock
            key={entry.entry_key}
            entry={entry}
            charLimit={expansion.char_limit}
            open={openKey === entry.entry_key}
            onToggle={() =>
              setOpenKey((prev) =>
                prev === entry.entry_key ? null : entry.entry_key,
              )
            }
          />
        ))}
      </div>

      {expansion.warnings.map((w) => (
        <p key={w} className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
          {w}
        </p>
      ))}

      <p className="mt-3 text-xs text-ink-muted">Model: {expansion.model}</p>
    </section>
  );
}
