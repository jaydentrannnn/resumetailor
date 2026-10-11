import type { CurrentLayout, SeparatorRow } from "../../../api";
import {
  BULLET_CHOICES,
  DATE_SEPARATOR_CHOICES,
  SEPARATOR_CHOICES,
  SEPARATOR_ROWS,
  withCurrent,
} from "../../../lib/templateAdjust";
import { Segmented, Switch, TileSection } from "../../ui";

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
export function BulletsSection({ draft, onChange }: Props) {
  const set = (key: "list" | "skills", value: string) =>
    onChange({ ...draft, bullets: { ...draft.bullets, [key]: value } });
  return (
    <TileSection title="Bullets">
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
    </TileSection>
  );
}

/** The separators this template prints, one row each. */
export function SeparatorsSection({ draft, onChange }: Props) {
  const rows = SEPARATOR_ROWS.filter(({ row }) => draft.separators[row] !== undefined);
  if (!rows.length) return null;
  const set = (row: SeparatorRow, value: string) =>
    onChange({ ...draft, separators: { ...draft.separators, [row]: value } });
  return (
    <TileSection title="Separators">
      <div className="space-y-2">
        {rows.map(({ row, label }) => (
          <SelectRow
            key={row}
            label={label}
            value={draft.separators[row] ?? ""}
            choices={row === "dates" ? DATE_SEPARATOR_CHOICES : SEPARATOR_CHOICES}
            onChange={(v) => set(row, v)}
          />
        ))}
      </div>
    </TileSection>
  );
}

/** How links (LinkedIn, GitHub, project links) look; only when the template has any. */
export function LinksSection({ draft, onChange }: Props) {
  const links = draft.links;
  if (!links) return null;
  return (
    <TileSection title="Links">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          label="Link colour"
          items={[
            { id: "blue", label: "Blue" },
            { id: "text", label: "Text colour" },
          ]}
          value={links.color}
          onChange={(id) =>
            onChange({ ...draft, links: { ...links, color: id === "text" ? "text" : "blue" } })
          }
        />
        <label className="flex items-center gap-2 text-sm text-ink-2">
          <Switch
            checked={links.underline}
            onChange={(underline) => onChange({ ...draft, links: { ...links, underline } })}
          />
          Underline
        </label>
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        Links stay clickable either way. Bold or italic is under Field emphasis.
      </p>
    </TileSection>
  );
}
