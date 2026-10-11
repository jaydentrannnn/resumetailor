import type { CurrentLayout } from "../../../api";
import { FONT_CHOICES, MARGIN_SIDES } from "../../../lib/templateAdjust";
import { Field } from "../../ui";

const SIDE_LABEL = { top: "Top", bottom: "Bottom", left: "Left", right: "Right" };

/** Margins (inches), font family and body text size. */
export function PageAndFontSection({
  draft,
  tableLayout,
  onChange,
}: {
  draft: CurrentLayout;
  tableLayout: boolean;
  onChange: (next: CurrentLayout) => void;
}) {
  const fonts = FONT_CHOICES.includes(draft.font_family)
    ? FONT_CHOICES
    : [draft.font_family, ...FONT_CHOICES];
  const number = (value: string, fallback: number) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  };
  return (
    <>
      <section>
        <h3 className="text-xs font-medium text-ink-2">Margins (inches)</h3>
        <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
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
        {tableLayout && (
          <p className="mt-2 text-xs text-ink-muted">
            This template is laid out in a table with a fixed width, so the table keeps its width
            when margins change. Use Edit layout in Word to resize it.
          </p>
        )}
      </section>
      <section className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
        <Field label="Font" help="Every line, headings included.">
          <select
            className="field w-full"
            value={draft.font_family}
            onChange={(e) => onChange({ ...draft, font_family: e.target.value })}
          >
            {fonts.map((font) => (
              <option key={font} value={font}>
                {font}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Text size (pt)" help="Headings keep their difference.">
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
      </section>
    </>
  );
}
