import type { ReactNode } from "react";
import { hiddenInSimple, useUiMode } from "../lib/uiMode";

/**
 * Renders `children` in Full view, and in Simple only when `keep` is true: the value was
 * changed from its default, it reports a problem, or a link revealed it (`lib/uiMode.ts`).
 * Every block Simple leaves out goes through here, so one search finds them all.
 */
export function FullOnly({ keep = false, children }: { keep?: boolean; children: ReactNode }) {
  const { simple } = useUiMode();
  return hiddenInSimple(simple, keep) ? null : <>{children}</>;
}
