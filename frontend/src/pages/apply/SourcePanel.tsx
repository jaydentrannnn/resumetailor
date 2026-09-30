import { useState } from "react";
import type { SourceConfig } from "../../api";
import { Button, Modal } from "../../components/ui";
import { sourceDisplayName, splitPhrases } from "../../lib/sources";
import { NameField } from "./AddFlows";
import { CategoryPicker, JobSearchEditor, WatchlistEditor } from "./SourceEditors";
import { SourceTest } from "./SourceTest";

export type SaveState = "saved" | "unsaved" | "saving" | "failed";

/**
 * The right-hand panel that edits one source: its name, the editor for its kind and a
 * live test. Edits go straight to `onChange`, which the page autosaves (debounced); the
 * indicator follows that save, a server validation error shows inline, and closing
 * flushes whatever is still pending.
 */
export function SourcePanel({
  source,
  saveState,
  saveError,
  connected,
  onConnect,
  onChange,
  onRemove,
  onClose,
}: {
  source: SourceConfig;
  saveState: SaveState;
  saveError: string | null;
  /** Whether a keyword search's provider has its keys (null while unknown). */
  connected: boolean | null;
  onConnect: () => void;
  onChange: (next: SourceConfig) => void;
  onRemove: () => void;
  onClose: () => void;
}) {
  const [touched, setTouched] = useState(false);
  const edit = (next: SourceConfig) => {
    setTouched(true);
    onChange(next);
  };
  const close = () => {
    // A text box commits on blur; closing would otherwise drop what is still being typed.
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    onClose();
  };
  const ready = source.kind !== "job_search" || splitPhrases(source.query ?? "").length > 0;
  const indicator =
    saveState === "failed"
      ? "Not saved"
      : saveState === "saved"
        ? touched
          ? "Saved"
          : ""
        : "Saving…";

  return (
    <Modal title={sourceDisplayName(source)} onClose={close} placement="right">
      <div className="mt-3 space-y-4 text-sm">
        <p
          role="status"
          aria-live="polite"
          className={`h-4 text-xs ${saveState === "failed" ? "text-danger" : "text-ink-muted"}`}
        >
          {indicator}
        </p>
        {saveError && (
          <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
            Could not save: {saveError}
          </p>
        )}
        <NameField
          value={source.name ?? ""}
          placeholder={sourceDisplayName({ ...source, name: "" })}
          onChange={(name) => edit({ ...source, name })}
        />
        {source.kind === "ats_board" ? (
          <WatchlistEditor source={source} onChange={edit} />
        ) : source.kind === "job_search" ? (
          <JobSearchEditor
            source={source}
            onChange={edit}
            connected={connected}
            onConnect={onConnect}
          />
        ) : (
          <>
            <p className="break-all text-xs text-ink-muted">{source.url}</p>
            <CategoryPicker source={source} onChange={edit} />
          </>
        )}
        <SourceTest source={source} disabled={!ready} autoRun />
        <div className="border-t border-line pt-3">
          <Button variant="ghost" size="sm" onClick={onRemove}>
            Remove this source
          </Button>
        </div>
      </div>
    </Modal>
  );
}
