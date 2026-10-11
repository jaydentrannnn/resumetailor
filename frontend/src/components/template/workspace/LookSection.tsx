import { useState } from "react";
import { Button, TileSection } from "../../ui";
import { QuickAdjustDrawer } from "../adjust/QuickAdjustDrawer";
import { LayoutEditSection } from "./LayoutEditSection";

/**
 * The resume's look: the current font and margins, Quick adjustments (a right-hand panel
 * — its per-field table needs more room than this column) and, in the desktop app,
 * Edit layout in Word. Both end in the template wizard below, never a silent change.
 */
export function LookSection({ summary }: { summary: string | null }) {
  const [adjusting, setAdjusting] = useState(false);
  return (
    <TileSection title="Look">
      {summary && <p className="font-mono text-xs text-ink">{summary}</p>}
      <p className="mt-1 text-xs text-ink-muted">
        Change margins, the font, text size, or which fields are bold, italic or underlined.
      </p>
      <Button className="mt-2" variant="secondary" onClick={() => setAdjusting(true)}>
        Quick adjustments
      </Button>
      <div className="mt-4">
        <LayoutEditSection />
      </div>
      {adjusting && <QuickAdjustDrawer onClose={() => setAdjusting(false)} />}
    </TileSection>
  );
}
