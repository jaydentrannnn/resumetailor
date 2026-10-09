import { useId, useState } from "react";
import type { LibraryProposal } from "../../api";
import { buttonClass } from "../../components/ui";
import { termNames } from "../../lib/vocabularySearch";
import { useLibraryState } from "../../state/libraryState";

/** What approving `p` does, in words: add to a term, create a term, or add a verb. */
function describe(p: LibraryProposal, target: string) {
  if (p.kind === "verb_family")
    return (
      <>
        Add <b>{p.verb}</b> to the <b>{p.family}</b> opening verbs
      </>
    );
  return target !== p.canonical || p.target_exists ? (
    <>
      Add <b>{p.alias}</b> as another name for <b>{target}</b>
    </>
  ) : (
    <>
      Create the term <b>{target}</b> with <b>{p.alias}</b> as another name
    </>
  );
}

/** One suggestion: a one-click add, a "different term" redirect, and reject. */
export function SuggestionRow({ proposal }: { proposal: LibraryProposal }) {
  const { entries, busy, approveProposals, rejectProposals } = useLibraryState();
  const [editing, setEditing] = useState(false);
  const [target, setTarget] = useState(proposal.canonical ?? "");
  const listId = useId();
  const isAlias = proposal.kind === "tag_alias";
  const targets = isAlias && target !== proposal.canonical ? { [proposal.id]: target } : {};

  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 text-sm">
          <p>{describe(proposal, target)}</p>
          {proposal.rationale && (
            <p className="mt-0.5 text-xs text-ink-muted">{proposal.rationale}</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy || !target.trim()}
            onClick={() => void approveProposals([proposal.id], targets)}
            className={buttonClass("primary", "sm")}
          >
            {isAlias && !proposal.target_exists && target === proposal.canonical ? "Create" : "Add"}
          </button>
          {isAlias && (
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(!editing)}
              className={buttonClass("plain", "sm")}
            >
              Different term
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => void rejectProposals([proposal.id])}
            className={buttonClass("ghost", "sm")}
          >
            Dismiss
          </button>
        </div>
      </div>
      {editing && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <label htmlFor={`${listId}-input`} className="text-ink-muted">
            Another name for
          </label>
          <input
            id={`${listId}-input`}
            list={listId}
            value={target}
            onChange={(e) => setTarget(e.target.value.toLowerCase())}
            className="field w-52"
          />
          <datalist id={listId}>
            {termNames(entries).map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </div>
      )}
    </li>
  );
}
