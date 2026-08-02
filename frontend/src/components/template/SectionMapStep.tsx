import type { TemplateAnalyzeResponse } from "../../api";

type Enabled = {
  education: boolean;
  experience: boolean;
  projects: boolean;
  skills: boolean;
};

type Props = {
  analysis: TemplateAnalyzeResponse;
  profile: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
};

/**
 * Confirm which optional sections to keep and show contact separator / headings.
 *
 * Experience cannot be disabled. Omitting Education / Projects / Skills clears their
 * mapping objects so the builder skips those sections.
 */
export function SectionMapStep({ analysis, profile, onChange }: Props) {
  const enabled = (profile.enabled as Enabled | undefined) ?? {
    education: true,
    experience: true,
    projects: true,
    skills: true,
  };
  const contact = (profile.contact as { separator?: string } | undefined) ?? {};
  const sectionByKey = Object.fromEntries(
    analysis.sections.map((s) => [s.key, s]),
  );

  const setEnabled = (key: keyof Enabled, value: boolean) => {
    /** Toggle an optional section and drop/restore its mapping blob. */
    if (key === "experience") return;
    const nextEnabled = { ...enabled, [key]: value };
    const next: Record<string, unknown> = {
      ...profile,
      enabled: nextEnabled,
    };
    if (!value) {
      next[key] = null;
    } else if (analysis.suggested_profile && analysis.suggested_profile[key]) {
      next[key] = analysis.suggested_profile[key];
    }
    onChange(next);
  };

  const setSeparator = (separator: string) => {
    /** Update the contact-line separator in the draft profile. */
    onChange({
      ...profile,
      contact: { ...(profile.contact as object), separator },
    });
  };

  return (
    <div className="mt-4 space-y-4 text-sm">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
          Sections to include
        </p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {(
            [
              ["experience", "Experience (required)"],
              ["education", "Education"],
              ["projects", "Projects"],
              ["skills", "Skills"],
            ] as const
          ).map(([key, label]) => {
            const detected = sectionByKey[key];
            const checked = enabled[key];
            return (
              <label
                key={key}
                className="flex items-start gap-2 rounded-lg border border-line/80 bg-paper/40 px-3 py-2"
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={checked}
                  disabled={key === "experience" || !detected}
                  onChange={(e) => setEnabled(key, e.target.checked)}
                />
                <span>
                  <span className="font-medium text-ink">{label}</span>
                  <span className="block text-xs text-ink-muted">
                    {detected
                      ? `Heading: “${detected.heading_text}”`
                      : "Not detected in upload"}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      <div>
        <label className="text-xs font-medium uppercase tracking-wide text-ink-muted">
          Contact separator
        </label>
        <input
          type="text"
          value={contact.separator ?? " • "}
          onChange={(e) => setSeparator(e.target.value)}
          className="mt-1 w-full rounded-md border border-line bg-paper px-3 py-2 font-mono text-sm"
        />
        <p className="mt-1 text-xs text-ink-muted">
          Literal text between location / email / phone / LinkedIn / GitHub.
        </p>
      </div>

      <div className="rounded-lg border border-line/80 bg-paper/40 px-3 py-2">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
          Name &amp; contact paragraphs
        </p>
        <p className="mt-1 text-ink">
          Name → paragraph {String(profile.name_paragraph_id ?? "—")}; contact →{" "}
          paragraph{" "}
          {String(
            (profile.contact as { paragraph_id?: number } | undefined)?.paragraph_id ??
              "—",
          )}
        </p>
        <p className="mt-1 text-xs text-ink-muted">
          Auto-detected from the first content lines. Field spans for headers were
          suggested from separators and tab stops in the prototype rows.
        </p>
      </div>
    </div>
  );
}
