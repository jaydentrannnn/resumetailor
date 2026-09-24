import type { ProfileGap } from "../api";

/** Blank profile fields application forms ask for; each opens the group that holds it. */
export function ProfileGapBanner({ gaps, onOpen }: { gaps: ProfileGap[]; onOpen: (section: string) => void }) {
  if (!gaps.length) return null;
  return <section aria-label="Blank profile fields" className="rounded-lg border border-warn/50 bg-panel p-4 text-sm">
    <p className="font-semibold">Forms ask for these, and your profile leaves them blank</p>
    <p className="text-xs text-ink-muted">Autofill skips a question whose answer is blank here. Set each one once and every form that asks it is answered. Decline is a valid voluntary-information answer; blank is not.</p>
    <ul className="mt-2 flex flex-wrap gap-2">{gaps.map(gap => <li key={gap.key}>
      <button type="button" className="rounded-md border border-line px-2 py-1 text-xs hover:bg-accent-soft" onClick={() => onOpen(gap.section)}>
        {gap.label}<span className="text-ink-muted"> · {gap.section}{gap.seen_in > 0 ? ` · met in ${gap.seen_in} application${gap.seen_in === 1 ? "" : "s"}` : ""}</span>
      </button>
    </li>)}</ul>
  </section>;
}
