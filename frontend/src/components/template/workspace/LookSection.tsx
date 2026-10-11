import { Button, TileSection } from "../../ui";
import { LayoutEditSection } from "./LayoutEditSection";

/**
 * The resume's look: the current font and margins, Quick adjustments (which turns this
 * view into its adjust mode, with a live draft preview) and, in the desktop app, Edit
 * layout in Word. Neither changes the installed template until it is applied.
 */
export function LookSection({
  summary,
  onAdjust,
}: {
  summary: string | null;
  onAdjust: () => void;
}) {
  return (
    <TileSection title="Look">
      {summary && <p className="font-mono text-xs text-ink">{summary}</p>}
      <p className="mt-1 text-xs text-ink-muted">
        Change margins, the font, bullets, separators, links, or which fields are bold, italic or
        underlined.
      </p>
      <Button className="mt-2" variant="secondary" onClick={onAdjust}>
        Quick adjustments
      </Button>
      <div className="mt-4">
        <LayoutEditSection />
      </div>
    </TileSection>
  );
}
