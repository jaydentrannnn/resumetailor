import { useCallback, useEffect, useState } from "react";
import {
  addEvidenceToResume,
  addFileEvidence,
  addGitHubEvidence,
  addTextEvidence,
  dismissEvidence,
  getEvidence,
  keepEvidenceForMatching,
  removeEvidenceSource,
  reopenEvidence,
  scanEvidenceSource,
  type EvidenceAddRequest,
  type EvidenceSourceKind,
  type EvidenceView,
} from "../api";
import type { MasterResume } from "./resumeEdit";

/**
 * The evidence page's state: sources, proposals and every action on them. `busy` names
 * what is running ("github", "add-source", a source id while it scans, a proposal id).
 * A failing action throws; the caller shows the error.
 */
export function useEvidence(onResumeSaved: (resume: MasterResume) => void) {
  const [view, setView] = useState<EvidenceView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);

  useEffect(() => {
    let live = true;
    getEvidence()
      .then((result) => live && setView(result))
      .catch((reason) => live && setLoadError(reason));
    return () => {
      live = false;
    };
  }, []);

  const act = useCallback(async (key: string, action: () => Promise<EvidenceView>) => {
    setBusy(key);
    try {
      const next = await action();
      setView(next);
      return next;
    } finally {
      setBusy(null);
    }
  }, []);

  return {
    view,
    busy,
    loadError,
    addGitHub: (target: string) => act("github", () => addGitHubEvidence(target)),
    addText: (kind: EvidenceSourceKind, title: string, text: string) =>
      act("add-source", () => addTextEvidence(kind, title, text)),
    addFile: (kind: EvidenceSourceKind, title: string, file: File) =>
      act("add-source", () => addFileEvidence(kind, title, file)),
    scan: (sourceId: string) => act(sourceId, () => scanEvidenceSource(sourceId)),
    removeSource: (sourceId: string) => act(sourceId, () => removeEvidenceSource(sourceId)),
    add: (proposalId: string, body: EvidenceAddRequest) =>
      act(proposalId, async () => {
        const result = await addEvidenceToResume(proposalId, body);
        onResumeSaved(result.resume as unknown as MasterResume);
        return result.evidence;
      }),
    keepForMatching: (proposalId: string, targetEntryId?: string) =>
      act(proposalId, () => keepEvidenceForMatching(proposalId, targetEntryId)),
    dismiss: (proposalId: string) => act(proposalId, () => dismissEvidence(proposalId)),
    reopen: (proposalId: string) => act(proposalId, () => reopenEvidence(proposalId)),
  };
}

export type EvidenceActions = ReturnType<typeof useEvidence>;
