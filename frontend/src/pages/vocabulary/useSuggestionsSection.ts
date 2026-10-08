import { useEffect, useMemo, useState } from "react";
import { type LibraryAliasImpact, LibraryApprovalConflict } from "../../api";
import { useLibraryState } from "../../state/libraryState";
export function useSuggestionsSection() {
  const {
    packs,
    proposals,
    proposalWarning,
    busy,
    generating,
    error,
    previewImpact,
    generateProposals,
    approveProposals,
    rejectProposals,
  } = useLibraryState();

  const [jdText, setJdText] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(25);
  const [sort, setSort] = useState("server");
  const [impactByAlias, setImpactByAlias] = useState<Record<string, LibraryAliasImpact>>({});
  const [conflict, setConflict] = useState<{
    ids: string[];
    targetPackId: string;
    message: string;
    impact: LibraryAliasImpact[];
  } | null>(null);

  const targetPacks = packs;
  const [targetPackId, setTargetPackId] = useState("");
  const sortedProposals = useMemo(
    () =>
      [...proposals].sort((a, b) => {
        if (sort === "server") return 0;
        if (sort === "kind") return a.kind.localeCompare(b.kind);
        if (sort === "impact")
          return (
            (impactByAlias[b.alias ?? ""]?.affected_tags.length ?? 0) -
            (impactByAlias[a.alias ?? ""]?.affected_tags.length ?? 0)
          );
        return (a.alias || a.verb || "").localeCompare(b.alias || b.verb || "");
      }),
    [proposals, sort, impactByAlias],
  );
  const pageProposals = useMemo(
    () => sortedProposals.slice(page * size, (page + 1) * size),
    [sortedProposals, page, size],
  );
  useEffect(() => {
    if (page > 0 && page >= Math.ceil(proposals.length / size))
      setPage(Math.max(0, Math.ceil(proposals.length / size) - 1));
  }, [page, size, proposals.length]);
  useEffect(() => {
    const visible = new Set(pageProposals.map((proposal) => proposal.id));
    setSelected((previous) => {
      const next = new Set([...previous].filter((id) => visible.has(id)));
      return next.size === previous.size && [...previous].every((id) => next.has(id))
        ? previous
        : next;
    });
  }, [pageProposals]);

  useEffect(() => {
    if (!targetPackId && targetPacks.length > 0) setTargetPackId(targetPacks[0].id);
  }, [targetPacks, targetPackId]);

  useEffect(() => {
    // Additive-vs-rewrite impact only applies to tag-alias proposals; verb-family
    // proposals never rewrite existing content, so they carry no badge to compute.
    const aliasEntries = proposals
      .filter((p) => p.kind === "tag_alias" && p.alias && p.canonical)
      .map((p) => [p.alias as string, p.canonical as string] as const);
    if (aliasEntries.length === 0) {
      setImpactByAlias({});
      return;
    }
    let cancelled = false;
    void previewImpact(Object.fromEntries(aliasEntries)).then((impacts) => {
      if (cancelled) return;
      setImpactByAlias(Object.fromEntries(impacts.map((i) => [i.alias, i])));
    });
    return () => {
      cancelled = true;
    };
  }, [proposals, previewImpact]);

  async function doApprove(ids: string[], acknowledgeRewrites: boolean) {
    if (!targetPackId) return;
    try {
      await approveProposals(ids, targetPackId, acknowledgeRewrites);
      setSelected(new Set());
      setConflict(null);
    } catch (err) {
      if (err instanceof LibraryApprovalConflict) {
        setConflict({ ids, targetPackId, message: err.message, impact: err.impact });
      }
    }
  }

  return {
    packs,
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
  };
}
