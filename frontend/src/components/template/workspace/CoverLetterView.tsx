import { type ReactNode, useState } from "react";
import type { CoverLetterSettings } from "../../../api";
import { useCoverAutosave } from "../../../lib/useCoverAutosave";
import { useCoverLetterSettings } from "../../../lib/useCoverLetterSettings";
import { CoverLetterPreviewPane } from "./CoverLetterPreviewPane";
import { LetterDesignSection } from "./LetterDesignSection";
import { LetterPartsSection } from "./LetterPartsSection";
import { DOCUMENT_CELL, SWITCH_CELL, TOOLS_CELL, WORKSPACE_GRID } from "./workspaceLayout";

/**
 * Template page › Cover letter view: the sample letter on the right; its design and parts
 * on the left, saved as they change. No look controls here — a generated letter takes
 * the resume template's look and an own letter's look is its file.
 */
export function CoverLetterView({
  reloadKey,
  switcher,
}: {
  reloadKey: unknown;
  switcher: ReactNode;
}) {
  const { settings, fields, ownLetter, error, save, uploadOwn, removeOwn } =
    useCoverLetterSettings(reloadKey);
  const autosave = useCoverAutosave(settings, save);
  // "Your own letter" picked before one is uploaded: shown, but not saved yet.
  const [pickingOwn, setPickingOwn] = useState(false);
  const draft = autosave.draft;

  if (!draft)
    return (
      <div className={WORKSPACE_GRID}>
        <div className={SWITCH_CELL}>{switcher}</div>
        <p
          role={error ? "alert" : "status"}
          className={`${DOCUMENT_CELL} py-8 text-sm ${error ? "text-danger" : "text-ink-muted"}`}
        >
          {error ?? "Loading cover letter settings…"}
        </p>
      </div>
    );

  const shown: CoverLetterSettings = pickingOwn ? { ...draft, design: "own" } : draft;
  const changeDesign = (next: CoverLetterSettings) => {
    if (next.design === "own" && !ownLetter && draft.design !== "own") {
      setPickingOwn(true);
      return;
    }
    setPickingOwn(false);
    autosave.change(next);
  };

  return (
    <div className={WORKSPACE_GRID} role="region" aria-label="Cover letter">
      <div className={SWITCH_CELL}>{switcher}</div>
      <div className={DOCUMENT_CELL}>
        <CoverLetterPreviewPane settings={draft} />
      </div>
      <div className={`${TOOLS_CELL} text-sm`}>
        <div>
          <h2 className="rt-tile-title">Cover letter</h2>
          <p className="mt-1 text-ink-muted">
            Applies to every letter written from now on and saves as you change it. Tone and angles
            are chosen per run on the Tailor page.
          </p>
          {autosave.error && (
            <p role="alert" className="mt-2 text-danger">
              Couldn&apos;t save: {autosave.error}
            </p>
          )}
        </div>
        <LetterDesignSection
          settings={shown}
          ownLetter={ownLetter}
          onChange={changeDesign}
          onUpload={uploadOwn}
          onRemove={removeOwn}
        />
        <LetterPartsSection settings={shown} fields={fields} onChange={autosave.change} />
      </div>
    </div>
  );
}
