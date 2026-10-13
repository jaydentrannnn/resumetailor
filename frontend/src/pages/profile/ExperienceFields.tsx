import { useEffect } from "react";
import type { ExperienceBasis } from "../../api";
import { useApplicantProfile } from "../../state/applicantProfileState";
import type { FieldContext } from "./fieldContext";

const BASES: { value: ExperienceBasis; label: string }[] = [
  { value: "experience", label: "Experience" },
  { value: "experience_projects", label: "Experience and projects" },
  { value: "experience_projects_education", label: "Experience, projects, and education" },
  { value: "custom", label: "Custom years" },
];

export function ExperienceFields({ ctx }: { ctx: FieldContext }) {
  const { experienceSummaries, refreshSummaries } = useApplicantProfile();
  useEffect(() => {
    void refreshSummaries?.().catch(() => undefined);
  }, [refreshSummaries]);
  const basis = ctx.draft.experience_basis ?? "experience";
  const summary = experienceSummaries?.[basis];
  return (
    <div className="mt-3 space-y-3">
      <label className="block text-sm">
        <span className="mb-1 block text-ink-muted">Years of experience from</span>
        <select
          className="field"
          aria-label="Years of experience from"
          value={basis}
          onChange={(e) => ctx.set("experience_basis", e.target.value)}
        >
          {BASES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {basis === "custom" ? (
        <label className="block text-sm">
          <span className="mb-1 block text-ink-muted">Custom years of experience</span>
          <input
            className="field"
            aria-label="Custom years of experience"
            type="number"
            min={0}
            step="any"
            aria-invalid={!!ctx.errors.experience_years_custom}
            value={ctx.draft.experience_years_custom ?? ""}
            onChange={(e) =>
              ctx.set(
                "experience_years_custom",
                e.target.value === "" ? null : Number(e.target.value),
              )
            }
          />
          {ctx.errors.experience_years_custom && (
            <span role="alert" className="mt-1 block text-xs text-danger">
              {ctx.errors.experience_years_custom}
            </span>
          )}
        </label>
      ) : (
        <>
          <p className="text-sm font-medium text-ink">
            {summary?.years == null
              ? "No dated subtotal available"
              : `${summary.years.toFixed(2)} years from dated entries`}
          </p>
          {!!summary?.excluded_entries.length && (
            <div className="text-xs text-ink-muted">
              <p>Excluded from this subtotal:</p>
              <ul className="mt-1 list-disc pl-4">
                {summary.excluded_entries.map((entry, i) => (
                  <li key={i}>
                    {entry.label}: {entry.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
      <p className="text-xs text-ink-muted">
        Used for general and professional experience questions. Overlapping dates count once.
        Questions about a specific technology use its own evidence.
      </p>
    </div>
  );
}
