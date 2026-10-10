import type { JobSettings } from "../../api";
import { Toggle } from "../../components/Field";
import { SectionBalanceBar } from "../../components/SectionBalanceBar";
import { activeSections, evenWeights, fromShares, toShares } from "../../lib/sectionBalance";
import { useResumeOutline } from "../../lib/useResumeOutline";

/**
 * "Section weights": how the bullet budget splits across the included experience and
 * project sections. Off is one shared pool where the most relevant bullets win. A saved
 * legacy experience share shows as its split and is replaced on the first edit.
 */
export function SectionBalance({
  settings,
  onChange,
}: {
  settings: JobSettings;
  onChange: (s: JobSettings) => void;
}) {
  const { outline, error } = useResumeOutline();
  const active = outline ? activeSections(outline, settings.include) : [];
  const canBalance = active.length >= 2;
  const on = settings.section_weights !== null || settings.experience_bullet_share !== null;
  const shares = toShares(active, settings.section_weights, settings.experience_bullet_share);

  function save(section_weights: Record<string, number> | null) {
    onChange({ ...settings, section_weights, experience_bullet_share: null });
  }

  let hint = "Needs two or more included sections with bullets.";
  if (error) hint = "Your resume sections could not be loaded.";
  else if (!outline) hint = "Loading your sections…";

  return (
    <div className="space-y-3">
      <Toggle
        label="Section weights"
        help="Give some sections more bullets than others."
        disabledHint={hint}
        disabled={!canBalance}
        checked={on && canBalance}
        onChange={(v) => save(v ? evenWeights(active) : null)}
      />
      {on && canBalance && (
        <SectionBalanceBar
          sections={active}
          shares={shares}
          onChange={(next) => save(fromShares(active, next, settings.section_weights))}
        />
      )}
    </div>
  );
}
