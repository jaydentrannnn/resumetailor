import { useEffect, useState } from "react";
import { type CurrentLayout, fetchTemplateAdjustments } from "../api";

/** `0.6"` for a margin in inches, without trailing zeros. */
function inches(value: number): string {
  return `${Number(value.toFixed(2))}"`;
}

/** "Georgia · 10.5 pt · 0.6" margins" — the look Quick adjustments would start from. */
export function lookSummary(layout: CurrentLayout): string {
  const { top, bottom, left, right } = layout.margins;
  const margins =
    top === bottom && bottom === left && left === right
      ? `${inches(top)} margins`
      : `margins ${inches(top)} / ${inches(left)}`;
  return [layout.font_family || "Default font", `${layout.font_size} pt`, margins].join(" · ");
}

/** The active template's font, size, margins and whether it is a table layout;
 * refetched when `revision` changes (an install or switch). Null until known. */
export function useLayoutSummary(revision: unknown) {
  const [state, setState] = useState<{ summary: string; table: boolean } | null>(null);
  useEffect(() => {
    let live = true;
    fetchTemplateAdjustments()
      .then(
        (res) => live && setState({ summary: lookSummary(res.current), table: res.table_layout }),
      )
      .catch(() => live && setState(null));
    return () => {
      live = false;
    };
  }, [revision]);
  return state;
}
