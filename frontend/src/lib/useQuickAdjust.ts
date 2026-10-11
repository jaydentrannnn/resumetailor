import { useEffect, useMemo, useState } from "react";
import {
  adjustTemplate,
  fetchEditedLayout,
  fetchTemplateAdjustments,
  fetchTemplateFonts,
  uploadTemplate,
  type CurrentLayout,
  type TemplateAnalyzeResponse,
  type TemplateFonts,
} from "../api";
import { describe } from "./errors";
import { changesFit, hasAdjustments, toAdjustments } from "./templateAdjust";

export type ApplyOutcome =
  | { kind: "installed" }
  /** The read-back needs a person to look at it: hand it to the template importer. */
  | { kind: "review"; file: File; analysis: TemplateAnalyzeResponse };

/**
 * Quick adjustments' draft: the template's current look, the edited copy, the
 * installed fonts, and Apply. Apply installs the adjusted layout as a template named
 * `label` (replacing an earlier template of that name), the current one staying in Your
 * templates, so switching back undoes it.
 * Page fit is re-measured when the change moves lines (`changesFit`).
 */
export function useQuickAdjust(label: string, afterInstall: () => Promise<void>) {
  const [current, setCurrent] = useState<CurrentLayout | null>(null);
  const [draft, setDraft] = useState<CurrentLayout | null>(null);
  const [tableLayout, setTableLayout] = useState(false);
  const [fonts, setFonts] = useState<TemplateFonts>({ families: [], common: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchTemplateAdjustments()
      .then((res) => {
        if (!live) return;
        setCurrent(res.current);
        setDraft(res.current);
        setTableLayout(res.table_layout);
      })
      .catch((reason) => live && setError(describe(reason).detail));
    // The box still works without the list (it then offers the font in use).
    fetchTemplateFonts()
      .then((res) => live && setFonts(res))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const adj = useMemo(
    () => (current && draft ? toAdjustments(current, draft) : null),
    [current, draft],
  );
  const dirty = adj !== null && hasAdjustments(adj);

  async function apply(): Promise<ApplyOutcome | null> {
    if (!adj || !dirty) return null;
    setBusy(true);
    setError(null);
    try {
      const analysis = await adjustTemplate(adj);
      const file = await fetchEditedLayout(analysis.source_sha256);
      if (!analysis.ready || !analysis.suggested_profile) return { kind: "review", file, analysis };
      await uploadTemplate(file, analysis.suggested_profile, {
        calibrate: changesFit(adj),
        label,
        replace: true,
      });
      await afterInstall();
      return { kind: "installed" };
    } catch (reason) {
      setError(describe(reason).detail);
      return null;
    } finally {
      setBusy(false);
    }
  }

  return { current, draft, setDraft, tableLayout, fonts, adj, dirty, busy, error, apply };
}
