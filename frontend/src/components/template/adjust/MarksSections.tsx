import type { CurrentLayout, SeparatorRow } from "../../../api";
import {
  BULLET_CHOICES,
  DATE_SEPARATOR_CHOICES,
  printedSeparatorRows,
  SEPARATOR_CHOICES,
  withCurrent,
} from "../../../lib/templateAdjust";

type Props = { draft: CurrentLayout; onChange: (next: CurrentLayout) => void };
type Choice = { value: string; label: string };

/** A label beside a native select: one row of the panel's settings lists. */
function SelectRow({
  label,
  value,
  choices,
  onChange,
}: {
  label: string;
  value: string;
  choices: Choice[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid grid-cols-[minmax(0,1fr)_11rem] items-center gap-3 text-sm">
      <span className="min-w-0 text-ink-2">{label}</span>
      <select className="field w-full" value={value} onChange={(e) => onChange(e.target.value)}>
        {withCurrent(choices, value).map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** One marker for every list, and one for skills lines (which keep their own list). */
export function BulletFields({ draft, onChange }: Props) {
  const set = (key: "list" | "skills", value: string) =>
    onChange({ ...draft, bullets: { ...draft.bullets, [key]: value } });
  return (
    <>
      <div className="space-y-2">
        <SelectRow
          label="Lists"
          value={draft.bullets.list}
          choices={BULLET_CHOICES}
          onChange={(v) => set("list", v)}
        />
        <SelectRow
          label="Skills lines"
          value={draft.bullets.skills}
          choices={BULLET_CHOICES}
          onChange={(v) => set("skills", v)}
        />
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        Lists are job, project and education bullets. None, indented keeps the text where it was.
      </p>
    </>
  );
}

/** One select per separator the template prints. */
export function SeparatorFields({ draft, onChange }: Props) {
  const set = (row: SeparatorRow, value: string) =>
    onChange({ ...draft, separators: { ...draft.separators, [row]: value } });
  return (
    <div className="space-y-2">
      {printedSeparatorRows(draft).map(({ row, label }) => (
        <SelectRow
          key={row}
          label={label}
          value={draft.separators[row] ?? ""}
          choices={row === "dates" ? DATE_SEPARATOR_CHOICES : SEPARATOR_CHOICES}
          onChange={(v) => set(row, v)}
        />
      ))}
    </div>
  );
}
