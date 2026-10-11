import { useState } from "react";
import { Button, Tile } from "../../ui";
import { QuickAdjustDrawer } from "./QuickAdjustDrawer";

/** Template page › Quick adjustments: margins, font and field emphasis without Word. */
export function QuickAdjustCard() {
  const [open, setOpen] = useState(false);
  return (
    <Tile aria-label="Quick adjustments">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="rt-tile-title">Quick adjustments</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Change margins, the font, text size, or which fields are bold, italic or underlined —
            then preview and install it as a new template.
          </p>
        </div>
        <Button variant="secondary" onClick={() => setOpen(true)}>
          Adjust
        </Button>
      </div>
      {open && <QuickAdjustDrawer onClose={() => setOpen(false)} />}
    </Tile>
  );
}
