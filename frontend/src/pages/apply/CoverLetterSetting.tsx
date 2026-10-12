import type { CoverLetterMode } from "../../api";
import { Segmented } from "../../components/ui";

const MODES: { id: CoverLetterMode; label: string; detail: string }[] = [
  {
    id: "off",
    label: "Off",
    detail: "Never written. A form that requires one waits for your review.",
  },
  {
    id: "required",
    label: "Required only",
    detail:
      "Written during Fill, only when a form requires a cover letter. Optional cover-letter fields stay empty.",
  },
  {
    id: "optional",
    label: "Required and optional",
    detail:
      "Written during Fill whenever a form has a cover-letter field. Adds about 15–30 seconds to those forms.",
  },
  {
    id: "every",
    label: "Every application",
    detail:
      "Written while preparing every application, so Fill is faster and you can read it first. Adds about 15–30 seconds to each item.",
  },
];

/**
 * Apply's cover-letter choice (`ApplySettings.cover_letter_mode`). It covers upload fields
 * and cover-letter text boxes alike; the Tailor tab's own switch is separate.
 */
export function CoverLetterSetting({
  value,
  onChange,
}: {
  value: CoverLetterMode;
  onChange: (mode: CoverLetterMode) => void;
}) {
  const current = MODES.find((mode) => mode.id === value) ?? MODES[1];
  return (
    <div>
      <Segmented
        label="When to write a cover letter"
        items={MODES.map(({ id, label }) => ({ id, label }))}
        value={current.id}
        onChange={(id) => onChange(id as CoverLetterMode)}
      />
      <p className="mt-2 text-xs text-ink-muted" aria-live="polite">
        {current.detail} Uploads and cover-letter text boxes follow the same choice.
      </p>
    </div>
  );
}
