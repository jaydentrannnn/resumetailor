import { useState } from "react";
import {
  inspectSource,
  resolveBoard,
  type ResolvedBoard,
  type SourceConfig,
  type SourceInspection,
} from "../../api";
import { Button, Modal } from "../../components/ui";
import { describe } from "../../lib/errors";
import { sourceDisplayName } from "../../lib/sources";
export { CatalogDialog } from "./CatalogDialog";
export { ConnectDialog } from "./ConnectDialog";

/**
 * The dialogs around the source panel: the catalog (with a paste-a-link field) for job
 * lists, the chooser for which watchlist a pasted careers link joins, and Connect for a
 * search engine's keys. Adding a source itself happens in `SourcePanel`.
 */

/** An inspection that recognised a README format. */
export type KnownInspection = SourceInspection & { kind: NonNullable<SourceInspection["kind"]> };

export function NameField({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (name: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block text-xs">
      <span className="font-medium">Name</span>
      <input
        className="field mt-1 w-full text-sm"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

/**
 * "Paste a link to any GitHub job list": a README is read first (its format is detected),
 * then the link is tried as a company careers page. Whichever it is, the matching add
 * panel opens prefilled.
 */
export function PasteLinkField({
  sources,
  onReadme,
  onBoard,
}: {
  sources: SourceConfig[];
  onReadme: (url: string, inspection: KnownInspection) => void;
  onBoard: (board: ResolvedBoard) => void;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    const link = url.trim();
    if (!link) return;
    const same = (a: string) => a.replace(/\/+$/, "") === link.replace(/\/+$/, "");
    const dup = sources.find((s) => s.url && same(s.url));
    if (dup) {
      setError(`Already in your sources as ${sourceDisplayName(dup)}.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      let inspection = null;
      try {
        inspection = await inspectSource(link);
      } catch {
        /* not a README we can read; try it as a careers page */
      }
      if (inspection?.kind) {
        onReadme(link, inspection as KnownInspection);
        return;
      }
      try {
        onBoard(await resolveBoard({ url: link }));
      } catch (reason) {
        const detail = describe(reason)
          .detail.replace(/\s*For more information check:.*$/s, "")
          .replace(/^Could not read the careers page:\s*/, "");
        setError(`That link is not a job list or a careers page we can read (${detail}).`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      aria-label="Paste a link"
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label htmlFor="sources-paste-link" className="text-sm font-medium">
        Paste a link to any job list
      </label>
      <p className="text-xs text-ink-muted">
        A GitHub repo or README with a table of postings. A company careers page works too.
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          id="sources-paste-link"
          className="field min-w-0 flex-1 text-sm"
          placeholder="https://github.com/owner/repo"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Button type="submit" size="sm" variant="secondary" loading={busy} disabled={!url.trim()}>
          Add
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </form>
  );
}

/** A pasted careers link resolved to a company: add it to a watchlist you have, or start one. */
export function BoardTargetDialog({
  board,
  watchlists,
  onAddTo,
  onNew,
  onClose,
}: {
  board: ResolvedBoard;
  watchlists: SourceConfig[];
  onAddTo: (id: string) => void;
  onNew: () => void;
  onClose: () => void;
}) {
  const [target, setTarget] = useState(watchlists[0]?.id ?? "");
  return (
    <Modal title="Add this company" onClose={onClose}>
      <div className="mt-4 space-y-3 text-sm">
        <p>
          Found <strong>{board.company || board.slug}</strong> on {board.ats} · {board.jobs} open
          posting{board.jobs === 1 ? "" : "s"}.
        </p>
        <label className="block text-xs">
          <span className="font-medium">Add it to</span>
          <select
            className="field mt-1 w-full text-sm"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            {watchlists.map((w) => (
              <option key={w.id} value={w.id}>
                {sourceDisplayName(w)}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap justify-between gap-2">
          <Button variant="secondary" size="sm" onClick={onNew}>
            Start a new watchlist
          </Button>
          <Button variant="primary" size="sm" disabled={!target} onClick={() => onAddTo(target)}>
            Add company
          </Button>
        </div>
      </div>
    </Modal>
  );
}
