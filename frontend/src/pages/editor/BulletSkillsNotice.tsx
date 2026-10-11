import { useBulletSkills } from "../../state/bulletSkillsState";

/**
 * A quiet note when skill detection failed and bullets still lack it. Never blocks
 * saving or moving on: the next save, editor visit or tailoring run retries it.
 */
export function BulletSkillsNotice() {
  const skills = useBulletSkills();
  if (!skills?.error || skills.running || skills.waiting === 0) return null;
  return (
    <p role="status" className="text-sm text-ink-muted">
      Skill detection didn&apos;t finish ({skills.error}). It retries automatically on your next
      save or tailoring run.
    </p>
  );
}
