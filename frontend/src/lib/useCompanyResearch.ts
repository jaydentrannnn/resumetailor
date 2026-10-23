import { useCallback, useEffect, useState } from "react";
import {
  getCompanyResearch,
  removeCompanyFact,
  researchCompany,
  type CompanyResearchRequest,
  type CompanyResearchView,
} from "../api";

/**
 * One application's company research: the saved view, plus research, add and remove.
 * An action that fails throws, and the caller shows the error.
 */
export function useCompanyResearch(sourceJobId: string) {
  const [view, setView] = useState<CompanyResearchView | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getCompanyResearch(sourceJobId)
      .then((result) => live && setView(result))
      .catch(() => live && setView(null));
    return () => {
      live = false;
    };
  }, [sourceJobId]);

  const act = useCallback(async (action: () => Promise<CompanyResearchView>) => {
    setBusy(true);
    try {
      setView(await action());
    } finally {
      setBusy(false);
    }
  }, []);

  return {
    view,
    busy,
    research: (body: CompanyResearchRequest) => act(() => researchCompany(sourceJobId, body)),
    remove: (factId: string) => act(() => removeCompanyFact(sourceJobId, factId)),
  };
}
