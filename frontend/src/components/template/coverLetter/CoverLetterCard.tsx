import { useState } from "react";
import { coverSummary } from "../../../lib/coverLetterSettings";
import { useCoverLetterSettings } from "../../../lib/useCoverLetterSettings";
import { Button, Tile } from "../../ui";
import { CoverLetterDrawer } from "./CoverLetterDrawer";

/**
 * Template page › Cover letter: what the letter's letterhead shows and which blocks
 * print, opened in a right-hand drawer with a live preview. Layout only — tone and
 * angles stay per run on the Tailor page.
 */
export function CoverLetterCard({ reloadKey }: { reloadKey: unknown }) {
  const { settings, fields, error, save } = useCoverLetterSettings(reloadKey);
  const [open, setOpen] = useState(false);
  return (
    <Tile aria-label="Cover letter">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="rt-tile-title">Cover letter</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Cover letters use this template&apos;s fonts and header. Choose what the letterhead
            shows and which parts of the letter print.
          </p>
          {settings && (
            <p className="mt-3 text-sm text-ink" aria-live="polite">
              {coverSummary(settings, fields)}
            </p>
          )}
          {error && <p className="mt-3 text-sm text-danger">{error}</p>}
        </div>
        <Button variant="secondary" disabled={!settings} onClick={() => setOpen(true)}>
          Customize
        </Button>
      </div>
      {open && settings && (
        <CoverLetterDrawer
          initial={settings}
          fields={fields}
          onSave={save}
          onClose={() => setOpen(false)}
        />
      )}
    </Tile>
  );
}
