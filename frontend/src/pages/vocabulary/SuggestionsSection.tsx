import { useState } from "react";
import { Tile, buttonClass } from "../../components/ui";
import { useLibraryState } from "../../state/libraryState";
import { SuggestionRow } from "./SuggestionRow";

/** Model-drafted additions from this profile's near-miss keywords and unknown verbs. */
export function SuggestionsSection() {
  const {
    proposals,
    proposalWarning,
    busy,
    generating,
    error,
    generateProposals,
    approveProposals,
  } = useLibraryState();
  const [jdText, setJdText] = useState("");

  return (
    <Tile
      title="Suggestions"
      description="Spellings a posting used that mean a skill you already have, and opening verbs no family covers yet. Nothing changes until you add one."
      actions={
        proposals.length > 1 && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void approveProposals(proposals.map((p) => p.id))}
            className={buttonClass("plain", "sm")}
          >
            Add all
          </button>
        )
      }
    >
      <div className="space-y-2">
        <label className="block text-sm">
          <span className="mb-1 block text-ink-muted">Job description (optional)</span>
          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            rows={3}
            placeholder="Paste a posting to check its wording against your resume…"
            className="field"
          />
        </label>
        <button
          type="button"
          onClick={() => void generateProposals(jdText)}
          disabled={generating}
          className={buttonClass("secondary", "sm")}
        >
          {generating ? "Looking for suggestions…" : "Find suggestions"}
        </button>
      </div>

      {error && (
        <p className="mt-3 whitespace-pre-line rounded-sm bg-danger-soft px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}
      {proposalWarning && (
        <p className="mt-3 rounded-sm bg-attn-soft px-3 py-2 text-xs text-attn">
          {proposalWarning}
        </p>
      )}

      {proposals.length > 0 ? (
        <ul aria-label="Suggestions" className="mt-4 border-t border-line">
          {proposals.map((proposal) => (
            <SuggestionRow key={proposal.id} proposal={proposal} />
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-ink-muted">No suggestions waiting.</p>
      )}
    </Tile>
  );
}
