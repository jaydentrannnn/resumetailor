import { useState } from "react";
import type { CatalogEntry, SourceConfig, SourceRunStatus } from "../../api";
import { RowActionsMenu } from "../../components/TableControls";
import { Button } from "../../components/ui";
import {
  applyCatalogUpdate,
  catalogDiff,
  FIELD_LABELS,
  sourceDisplayName,
  sourceBadge,
  sourceHealth,
  sourceSummary,
} from "../../lib/sources";

const HEALTH_TONE = {
  ok: "text-success",
  error: "text-danger",
  muted: "text-ink-muted",
} as const;

/**
 * One source, identical for every kind and every age of entry: select box, on/off switch,
 * name, a one-line summary, how its last run went, and a ⋯ menu (Edit, Rename,
 * Duplicate, Remove). Editing happens in the side panel, never inline.
 */
export function SourceRow({
  source,
  run,
  selected,
  update,
  notice,
  keysSaved = null,
  onSelect,
  onChange,
  onEdit,
  onDuplicate,
  onRemove,
}: {
  source: SourceConfig;
  /** How the source did on its latest run; undefined when it has never run. */
  run: SourceRunStatus | undefined;
  selected: boolean;
  update: CatalogEntry | null;
  /** A problem known without running (a search engine that is not connected). */
  notice?: string;
  /** Whether this search's engine has its keys saved now (null: not a search, or unknown). */
  keysSaved?: boolean | null;
  onSelect: (on: boolean) => void;
  onChange: (next: SourceConfig) => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  const name = sourceDisplayName(source);
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(name);
  const [reviewing, setReviewing] = useState(false);
  const health = sourceHealth(source, run, Date.now(), keysSaved);

  function commitName() {
    setRenaming(false);
    const next = draftName.trim();
    if (next && next !== name) onChange({ ...source, name: next });
    else setDraftName(name);
  }

  return (
    <li className="rounded-lg border border-line bg-panel p-3">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          aria-label={`Select ${name}`}
          className="mt-1 h-4 w-4 accent-[var(--color-accent)]"
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
        />
        {/* A pill switch, not a second checkbox: the row's select box sits right beside it. */}
        <button
          type="button"
          role="switch"
          aria-label={`${name} on`}
          aria-checked={source.enabled}
          title={source.enabled ? "On: searched every run" : "Off: skipped"}
          // The button keeps the global 36px touch floor; the pill is drawn inside it.
          className="-my-2 inline-flex shrink-0 items-center"
          onClick={() => onChange({ ...source, enabled: !source.enabled })}
        >
          <span
            aria-hidden="true"
            className={`inline-flex h-5 w-9 items-center rounded-full border transition-colors ${
              source.enabled ? "border-accent bg-accent" : "border-line bg-paper"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${
                source.enabled ? "translate-x-[17px]" : "translate-x-0.5"
              }`}
            />
          </span>
        </button>
        <div className="min-w-0 flex-1">
          {renaming ? (
            <input
              autoFocus
              aria-label={`Name for ${name}`}
              className="field w-full max-w-sm text-sm"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onBlur={commitName}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitName();
                if (e.key === "Escape") {
                  setDraftName(name);
                  setRenaming(false);
                }
              }}
            />
          ) : (
            <p className="flex flex-wrap items-center gap-2 font-medium">
              <button
                type="button"
                title="Edit"
                className={`min-w-0 max-w-full truncate text-left hover:text-accent ${source.enabled ? "" : "text-ink-muted"}`}
                onClick={onEdit}
              >
                {name}
              </button>
              <span className="rounded-full bg-paper px-2 py-0.5 text-micro font-normal text-ink-muted">
                {sourceBadge(source)}
              </span>
              {update && (
                <span className="rounded-full bg-warn-soft px-2 py-0.5 text-micro font-semibold text-warn">
                  Update available
                </span>
              )}
            </p>
          )}
          <p className="mt-0.5 truncate text-xs text-ink-muted">{sourceSummary(source)}</p>
          <p className={`mt-0.5 text-xs ${HEALTH_TONE[health.tone]}`}>
            <span className="sr-only">Last run: </span>
            {health.text}
          </p>
          {notice && source.enabled && <p className="mt-0.5 text-xs text-warn">{notice}</p>}
        </div>
        <RowActionsMenu
          label={`Actions for ${name}`}
          items={[
            { label: "Edit", action: onEdit },
            {
              label: "Rename",
              action: () => {
                setDraftName(name);
                setRenaming(true);
              },
            },
            { label: "Duplicate", action: onDuplicate },
            { label: "Remove", action: onRemove, danger: true },
          ]}
        />
      </div>

      {update && (
        <div className="mt-2 pl-14">
          {reviewing ? (
            <UpdateDiff
              source={source}
              entry={update}
              onCancel={() => setReviewing(false)}
              onApply={() => {
                onChange(applyCatalogUpdate(source, update));
                setReviewing(false);
              }}
            />
          ) : (
            <button
              type="button"
              className="text-xs text-accent underline"
              onClick={() => setReviewing(true)}
            >
              Review update
            </button>
          )}
        </div>
      )}
    </li>
  );
}

function UpdateDiff({
  source,
  entry,
  onApply,
  onCancel,
}: {
  source: SourceConfig;
  entry: CatalogEntry;
  onApply: () => void;
  onCancel: () => void;
}) {
  const diff = catalogDiff(source, entry);
  const nothing = !diff.url && diff.added.length === 0 && diff.removed.length === 0;
  return (
    <div
      role="region"
      aria-label={`Update for ${sourceDisplayName(source)}`}
      className="space-y-2 rounded-md border border-line bg-paper p-3 text-xs"
    >
      <p className="font-medium">
        Version {source.catalog_version || "?"} → {entry.version}
        {entry.fields.length > 0 && (
          <span className="ml-2 font-normal text-ink-muted">
            {entry.fields.map((f) => FIELD_LABELS[f] ?? f).join(" · ")}
          </span>
        )}
      </p>
      {diff.url && (
        <p className="break-all">
          <span className="font-medium">Link:</span> <s className="text-danger">{diff.url.from}</s>{" "}
          → <span className="text-accent">{diff.url.to}</span>
        </p>
      )}
      {diff.added.length > 0 && <p className="text-accent">+ {diff.added.join(" · ")}</p>}
      {diff.removed.length > 0 && <p className="text-danger">− {diff.removed.join(" · ")}</p>}
      {nothing && <p className="text-ink-muted">Only the version number changes.</p>}
      <div className="flex gap-2">
        <Button size="sm" variant="primary" onClick={onApply}>
          Update
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Not now
        </Button>
      </div>
    </div>
  );
}
