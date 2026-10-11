import { useId } from "react";
import type { CurrentLayout, TemplateFonts } from "../../../api";
import { fontHint, MARGIN_SIDES } from "../../../lib/templateAdjust";
import { Field, TileSection } from "../../ui";
import { FontPicker } from "./FontPicker";

const SIDE_LABEL = { top: "Top", bottom: "Bottom", left: "Left", right: "Right" };

type Props = { draft: CurrentLayout; onChange: (next: CurrentLayout) => void };

function number(value: string, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

/** Page margins in inches, two by two (the body of the Margins section). */
export function MarginFields({ draft, onChange, tableLayout }: Props & { tableLayout: boolean }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        {MARGIN_SIDES.map((side) => (
          <Field key={side} label={SIDE_LABEL[side]}>
            <input
              type="number"
              className="field w-full"
              min={0}
              max={3}
              step={0.05}
              value={draft.margins[side]}
              onChange={(e) =>
                onChange({
                  ...draft,
                  margins: {
                    ...draft.margins,
                    [side]: number(e.target.value, draft.margins[side]),
                  },
                })
              }
            />
          </Field>
        ))}
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        In inches.
        {tableLayout &&
          " This template is laid out in a table with a fixed width, so the table keeps its width when margins change. Use Edit layout in Word to resize it."}
      </p>
    </>
  );
}

/** The body typeface and text size. Always open: it is the change people make most.
 * `current` is the template as it is, whose body font the choice replaces. */
export function FontSection({
  draft,
  onChange,
  fonts,
  current,
}: Props & { fonts: TemplateFonts; current: CurrentLayout }) {
  const labelId = useId();
  return (
    <TileSection title="Font" className="pb-4">
      <div className="grid grid-cols-[minmax(0,1fr)_5.5rem] gap-3">
        <div className="min-w-0 text-sm">
          <span id={labelId} className="mb-1.5 block text-xs font-medium text-ink-2">
            Typeface
          </span>
          <FontPicker
            value={draft.font_family}
            fonts={fonts}
            labelId={labelId}
            onChange={(font_family) => onChange({ ...draft, font_family })}
          />
        </div>
        <Field label="Size (pt)">
          <input
            type="number"
            className="field w-full"
            min={6}
            max={20}
            step={0.5}
            value={draft.font_size}
            onChange={(e) =>
              onChange({ ...draft, font_size: number(e.target.value, draft.font_size) })
            }
          />
        </Field>
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        {fontHint(current.font_family, current.other_fonts)}
      </p>
    </TileSection>
  );
}
