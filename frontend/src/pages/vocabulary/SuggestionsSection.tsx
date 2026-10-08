import { Pagination } from "../../components/TableControls";
import { Tile } from "../../components/ui";
import { buttonClass } from "../../lib/buttonClass";
import { useSuggestionsSection } from "./useSuggestionsSection";
import { SuggestionTable } from "./SuggestionTable";
import { SuggestionConflict } from "./SuggestionConflict";
export function SuggestionsSection() {
  const {
    proposals,
    proposalWarning,
    busy,
    generating,
    error,
    generateProposals,
    rejectProposals,
    jdText,
    setJdText,
    selected,
    setSelected,
    page,
    setPage,
    size,
    setSize,
    sort,
    setSort,
    impactByAlias,
    conflict,
    setConflict,
    targetPacks,
    targetPackId,
    setTargetPackId,
    pageProposals,
    doApprove,
  } = useSuggestionsSection();
  return (
    <Tile>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="rt-tile-title">Suggestions</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Drafted from your resume's own near-miss keyword gaps and opening verbs no family
            claims. Nothing here takes effect until you approve it into a pack above.
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        <label className="block text-sm">
          <span className="mb-1 block text-ink-muted">Job description (optional)</span>
          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            rows={3}
            placeholder="Paste a posting to also check its keywords against your tags…"
            className="field"
          />
        </label>
        <button
          type="button"
          onClick={() => void generateProposals(jdText)}
          disabled={generating}
          className={buttonClass("secondary", "sm")}
        >
          {generating ? "Drafting suggestions…" : "Generate suggestions"}
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

      {proposals.length > 0 && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
            <label>
              Sort suggestions{" "}
              <select
                className="ml-2 rounded border border-line bg-panel px-2"
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value);
                  setPage(0);
                  setSelected(new Set());
                }}
              >
                <option value="server">Server order</option>
                <option value="suggestion">Suggestion</option>
                <option value="kind">Kind</option>
                <option value="impact">Impact</option>
              </select>
            </label>
            <button
              className={buttonClass("ghost", "sm")}
              onClick={() => {
                const next = new Set(selected);
                pageProposals.forEach((proposal) => next.add(proposal.id));
                setSelected(next);
              }}
            >
              Select this page
            </button>
            <button className={buttonClass("ghost", "sm")} onClick={() => setSelected(new Set())}>
              Clear selection
            </button>
          </div>
          <Pagination
            page={page}
            size={size}
            total={proposals.length}
            onPage={(value) => {
              setPage(value);
              setSelected(new Set());
            }}
            onSize={(value) => {
              setSize(value);
              setPage(0);
              setSelected(new Set());
            }}
          />
          <SuggestionTable
            pageProposals={pageProposals}
            selected={selected}
            setSelected={setSelected}
            busy={busy}
            impactByAlias={impactByAlias}
          />
          <Pagination
            page={page}
            size={size}
            total={proposals.length}
            onPage={(value) => {
              setPage(value);
              setSelected(new Set());
            }}
            onSize={(value) => {
              setSize(value);
              setPage(0);
              setSelected(new Set());
            }}
          />

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <label className="text-sm">
              <span className="mr-2 text-ink-muted">Approve into</span>
              <select
                value={targetPackId}
                onChange={(e) => setTargetPackId(e.target.value)}
                className="field inline-block w-auto"
              >
                {targetPacks.length === 0 && <option value="">No packs available</option>}
                {targetPacks.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => void doApprove([...selected], false)}
              disabled={busy || selected.size === 0 || !targetPackId}
              className={buttonClass("primary", "sm")}
            >
              Approve selected
            </button>
            <button
              type="button"
              onClick={() => void rejectProposals([...selected]).then(() => setSelected(new Set()))}
              disabled={busy || selected.size === 0}
              className={buttonClass("danger", "sm")}
            >
              Reject selected
            </button>
          </div>
        </>
      )}

      <SuggestionConflict conflict={conflict} setConflict={setConflict} doApprove={doApprove} />
    </Tile>
  );
}
