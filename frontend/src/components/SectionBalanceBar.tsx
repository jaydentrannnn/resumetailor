import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { type BalanceSection, STEP, moveDivider, setDivider } from "../lib/sectionBalance";

/** Segment fills: ink mixed into the sunken surface, darkest first (no accent fills). */
const SHADES = [78, 48, 26, 12];

function shade(i: number): string {
  return `color-mix(in srgb, var(--color-ink) ${SHADES[i % SHADES.length]}%, var(--color-sunken))`;
}

/**
 * One bar split into a segment per section, with a divider between each pair. Dragging
 * (or arrow-keying) a divider trades share only between the two sections beside it.
 */
export function SectionBalanceBar({
  sections,
  shares,
  onChange,
}: {
  sections: BalanceSection[];
  shares: number[];
  onChange: (shares: number[]) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const edges = shares
    .slice(0, -1)
    .map((_, i) => shares.slice(0, i + 1).reduce((a, b) => a + b, 0));

  function drag(i: number, e: PointerEvent<HTMLDivElement>) {
    if (!e.currentTarget.hasPointerCapture(e.pointerId) || !track.current) return;
    const rect = track.current.getBoundingClientRect();
    const position = ((e.clientX - rect.left) / rect.width) * 100;
    const next = setDivider(shares, i, position);
    if (next !== shares) onChange(next);
  }

  function key(i: number, e: KeyboardEvent<HTMLDivElement>) {
    const deltas: Record<string, number> = {
      ArrowLeft: -STEP,
      ArrowDown: -STEP,
      ArrowRight: STEP,
      ArrowUp: STEP,
      Home: STEP - shares[i],
      End: shares[i + 1] - STEP,
    };
    const delta = deltas[e.key];
    if (delta === undefined) return;
    e.preventDefault();
    const next = moveDivider(shares, i, delta);
    if (next !== shares) onChange(next);
  }

  return (
    <div>
      <div
        ref={track}
        className="relative flex h-7 touch-none select-none overflow-hidden rounded-sm border border-line"
      >
        {sections.map((s, i) => (
          <div key={s.id} style={{ width: `${shares[i]}%`, background: shade(i) }} />
        ))}
      </div>
      <div className="relative -mt-7 h-7">
        {edges.map((edge, i) => (
          <div
            key={sections[i].id}
            role="slider"
            tabIndex={0}
            aria-label={`Between ${sections[i].title} and ${sections[i + 1].title}`}
            aria-valuemin={edge - shares[i] + STEP}
            aria-valuemax={edge + shares[i + 1] - STEP}
            aria-valuenow={edge}
            aria-valuetext={`${sections[i].title} ${shares[i]}%, ${sections[i + 1].title} ${shares[i + 1]}%`}
            onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
            onPointerMove={(e) => drag(i, e)}
            onKeyDown={(e) => key(i, e)}
            style={{ left: `${edge}%` }}
            className="group absolute top-0 flex h-7 w-6 -translate-x-1/2 cursor-ew-resize touch-none items-center justify-center rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
          >
            <span className="h-9 w-2 rounded-full border-2 border-paper bg-ink shadow-sm transition-transform group-hover:scale-x-125 group-active:scale-x-125" />
          </div>
        ))}
      </div>
      <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        {sections.map((s, i) => (
          <li key={s.id} className="flex min-w-0 items-center gap-1.5">
            <span
              aria-hidden
              className="size-2.5 shrink-0 rounded-[2px] border border-line"
              style={{ background: shade(i) }}
            />
            <span className="truncate">{s.title}</span>
            <span className="tabular-nums text-ink-muted">about {shares[i]}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
