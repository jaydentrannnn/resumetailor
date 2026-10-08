import type { SourceConfig, SourcesStatus } from "../../api";
import { RowActionsMenu } from "../../components/TableControls";
import { sourcesHeadline } from "../../lib/sources";
import { writeDismissed, type useSourcesController } from "./sourceHooks";
import type { ReactNode } from "react";
import { Tile } from "../../components/ui";

/** A source family: one tile, with hairlines between its rows. */
export function SourceGroup({
  id,
  title,
  explanation,
  action,
  extra,
  empty,
  rows,
}: {
  id: string;
  title: string;
  explanation: string;
  action: ReactNode;
  extra?: ReactNode;
  empty: string;
  rows: ReactNode[];
}) {
  return (
    <Tile
      aria-labelledby={`sources-group-${id}`}
      title={<span id={`sources-group-${id}`}>{title}</span>}
      meta={<span className="font-mono">{rows.length}</span>}
      actions={action}
    >
      <p className="sr-only">{explanation}</p>
      {extra && <div className="mb-4">{extra}</div>}
      {rows.length === 0 ? (
        <p className="py-2 text-sm text-ink-muted">{empty}</p>
      ) : (
        <ul className="divide-y divide-line">{rows}</ul>
      )}
    </Tile>
  );
}

export function SourceToolbar({
  sources,
  status,
  controller,
  canChangeFields,
}: {
  sources: SourceConfig[];
  status: SourcesStatus | null;
  controller: ReturnType<typeof useSourcesController>;
  canChangeFields: boolean;
}) {
  const { selectedIds, setSelected, restore, setDismissed, setPickingFields } = controller;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="font-mono text-xs text-ink-muted" aria-live="polite">
          {sourcesHeadline(sources, status?.last_run_at)}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {sources.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              aria-label="Select all sources"
              className="h-4 w-4 accent-[var(--color-accent)]"
              checked={selectedIds.size === sources.length}
              onChange={(e) =>
                setSelected(e.target.checked ? new Set(sources.map((s) => s.id)) : new Set())
              }
            />
            Select all
          </label>
        )}
        <RowActionsMenu
          label="More source actions"
          items={[
            { label: "Restore defaults", action: restore },
            ...(canChangeFields
              ? [
                  {
                    label: "Change fields",
                    action: () => {
                      setDismissed(false);
                      writeDismissed(false);
                      setPickingFields(true);
                    },
                  },
                  {
                    label: "Show recommendations",
                    action: () => {
                      setDismissed(false);
                      writeDismissed(false);
                    },
                  },
                ]
              : []),
          ]}
        />
      </div>
    </div>
  );
}
