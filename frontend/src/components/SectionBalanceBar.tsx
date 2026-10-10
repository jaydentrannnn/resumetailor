import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { type BalanceSection, STEP, moveDivider, setDivider } from "../lib/sectionBalance";

/**
 * A slider track with one thumb between each pair of sections, styled like the native
 * range inputs beside it. Dragging (or arrow-keying) a thumb trades share only between
 * the two sections either side of it; each section's name and share sit under its span.
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
      <div ref={track} className="relative h-6 touch-none select-none">
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-line-hover" />
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
            className="group absolute top-1/2 flex size-6 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize touch-none items-center justify-center rounded-sm"
          >
            <span className="size-4 rounded-full bg-accent" />
          </div>
        ))}
      </div>
      <div className="mt-1 flex text-xs">
        {sections.map((s, i) => (
          <div key={s.id} style={{ width: `${shares[i]}%` }} className="min-w-0 px-0.5 text-center">
            <span className="block truncate text-ink-2" title={s.title}>
              {s.title}
            </span>
            <span className="block truncate tabular-nums text-ink-muted">~{shares[i]}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
