import { useState } from "react";
import type { SourceConfig } from "../../api";
import { Button, Modal } from "../../components/ui";
import {
  githubPageUrl,
  PROVIDER_LABELS,
  providerOf,
  sourceDisplayName,
  splitPhrases,
  type SearchProvider,
} from "../../lib/sources";
import { NameField } from "./AddFlows";
import { CategoryPicker, FiltersEditor, JobSearchEditor, WatchlistEditor } from "./SourceEditors";
import { SourceTest } from "./SourceTest";

export type SaveState = "saved" | "unsaved" | "saving" | "failed";

/** Why a source cannot be saved yet ("" when it can). */
export function notReadyReason(source: SourceConfig): string {
  if (source.kind === "job_search" && splitPhrases(source.query ?? "").length === 0)
    return "Add at least one search phrase first";
  if (source.kind === "ats_board" && (source.boards ?? []).length === 0)
    return "Add at least one company first";
  return "";
}

function titleFor(source: SourceConfig, mode: "new" | "edit"): string {
  if (mode === "edit") return sourceDisplayName(source);
  if (source.kind === "job_search") return `New ${PROVIDER_LABELS[providerOf(source)]} search`;
  if (source.kind === "ats_board") return "New company watchlist";
  return "New job list";
}

function addLabel(source: SourceConfig): string {
  if (source.kind === "job_search") return "Add search";
  if (source.kind === "ats_board") return "Add watchlist";
  return "Add job list";
}

/**
 * The right-hand panel for one source, used for every kind and both ways in. Opening a
 * saved source (`mode="edit"`) autosaves each edit through `onChange` (the page debounces)
 * and closing flushes what is pending. A source being added (`mode="new"`) is a draft that
 * only `onAdd` saves; Cancel drops it. Either way the body is the same: name, what to
 * read, filters and a live test.
 */
export function SourcePanel({
  mode = "edit",
  source,
  initialSections = null,
  saveState = "saved",
  saveError = null,
  connections,
  onConnect,
  onChange,
  onRemove,
  onAdd,
  onClose,
}: {
  mode?: "new" | "edit";
  source: SourceConfig;
  /** README headings already read (a pasted link that was just inspected). */
  initialSections?: string[] | null;
  saveState?: SaveState;
  saveError?: string | null;
  /** Which search engines have their keys saved (null while unknown). */
  connections: Record<SearchProvider, boolean> | null;
  onConnect: (provider: SearchProvider) => void;
  /** Edit mode: every change to the saved source. */
  onChange?: (next: SourceConfig) => void;
  onRemove?: () => void;
  /** New mode: save the draft. */
  onAdd?: (source: SourceConfig) => void;
  onClose: () => void;
}) {
  const [touched, setTouched] = useState(false);
  const [draft, setDraft] = useState(source);
  const current = mode === "new" ? draft : source;
  const edit = (next: SourceConfig) => {
    if (mode === "new") setDraft(next);
    else {
      setTouched(true);
      onChange?.(next);
    }
  };
  const close = () => {
    // A text box commits on blur; closing would otherwise drop what is still being typed.
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    onClose();
  };
  const blocker = notReadyReason(current);
  const provider = providerOf(current);
  const indicator =
    saveState === "failed"
      ? "Not saved"
      : saveState === "saved"
        ? touched
          ? "Saved"
          : ""
        : "Saving…";
  const github = githubPageUrl(current.url);
  const isReadme = current.kind !== "ats_board" && current.kind !== "job_search";

  return (
    <Modal title={titleFor(current, mode)} onClose={close} placement="right">
      <div className="mt-3 space-y-4 text-sm">
        {mode === "edit" && (
          <p
            role="status"
            aria-live="polite"
            className={`h-4 text-xs ${saveState === "failed" ? "text-danger" : "text-ink-muted"}`}
          >
            {indicator}
          </p>
        )}
        {saveError && mode === "edit" && (
          <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
            Could not save: {saveError}
          </p>
        )}
        <NameField
          value={current.name ?? ""}
          placeholder={sourceDisplayName({ ...current, name: "" })}
          onChange={(name) => edit({ ...current, name })}
        />

        {current.kind === "ats_board" ? (
          <WatchlistEditor source={current} onChange={edit} />
        ) : current.kind === "job_search" ? (
          <JobSearchEditor
            source={current}
            onChange={edit}
            connected={connections ? connections[provider] : null}
            onConnect={() => onConnect(provider)}
            onProvider={mode === "new" ? (next) => edit({ ...current, provider: next }) : undefined}
          />
        ) : (
          <div className="space-y-2">
            {github && (
              <p className="text-xs">
                <a className="text-accent underline" href={github} target="_blank" rel="noreferrer">
                  View on GitHub
                </a>
              </p>
            )}
            <CategoryPicker source={current} initialSections={initialSections} onChange={edit} />
          </div>
        )}

        <FiltersEditor
          source={current}
          onChange={edit}
          defaultDays={current.kind === "ats_board" ? 7 : current.kind === "job_search" ? 14 : null}
        />

        <SourceTest source={current} disabled={!!blocker} autoRun={mode === "edit" || isReadme} />

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
          {mode === "new" ? (
            <>
              <Button variant="ghost" size="sm" onClick={close}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!!blocker}
                title={blocker || undefined}
                onClick={() => onAdd?.(draft)}
              >
                {addLabel(current)}
              </Button>
            </>
          ) : (
            <Button variant="ghost" size="sm" onClick={onRemove}>
              Remove this source
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
