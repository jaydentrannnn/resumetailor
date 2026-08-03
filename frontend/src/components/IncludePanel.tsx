import { useEffect, useState } from "react";
import {
  type ContactField,
  type JobSettings,
  type ResumeOutline,
  fetchResumeOutline,
} from "../api";
import { moveItem } from "../lib/resumeEdit";

const ALL_CONTACT_FIELDS: ContactField[] = [
  "location",
  "email",
  "phone",
  "linkedin",
  "github",
];

const CONTACT_FIELD_LABELS: Record<ContactField, string> = {
  location: "Location",
  email: "Email",
  phone: "Phone",
  linkedin: "LinkedIn",
  github: "GitHub",
};

/**
 * Centralized "what to leave out" tile: contact field order/visibility, GPA and
 * coursework, and per-entry experience/project exclusion — one place instead of
 * scattered across the Tailor settings panel and the Master resume editor.
 *
 * Fetches its own copy of `/api/resume-outline` on mount rather than relying on
 * `AppConfig` (which `RunProvider` fetches once and holds for the profile's whole
 * mount) — an edit made on the Master resume tab must show up here the next time the
 * Tailor tab is visited, and this component remounts on every navigation to it.
 */
export function IncludePanel({
  settings,
  onChange,
}: {
  settings: JobSettings;
  onChange: (s: JobSettings) => void;
}) {
  const [outline, setOutline] = useState<ResumeOutline | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchResumeOutline()
      .then((o) => {
        if (!cancelled) setOutline(o);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function setInclude(patch: Partial<JobSettings["include"]>) {
    onChange({ ...settings, include: { ...settings.include, ...patch } });
  }

  if (error) {
    return (
      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
        <h2 className="font-display text-xl font-semibold">What to include</h2>
        <p className="mt-2 text-sm text-danger">{error}</p>
      </section>
    );
  }

  if (!outline) {
    return (
      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
        <h2 className="font-display text-xl font-semibold">What to include</h2>
        <p className="mt-2 text-sm text-ink-muted">Loading…</p>
      </section>
    );
  }

  const available = new Set(outline.available_contact_fields);
  const requestedOrder =
    settings.include.contact_fields ?? outline.default_contact_order ?? ALL_CONTACT_FIELDS;
  const includedOrder = (requestedOrder as ContactField[]).filter((f) => available.has(f));
  const excludedFields = ALL_CONTACT_FIELDS.filter((f) => !includedOrder.includes(f));

  function setContactOrder(next: ContactField[]) {
    setInclude({ contact_fields: next });
  }

  function includeContactField(field: ContactField) {
    setContactOrder([...includedOrder, field]);
  }

  function excludeContactField(field: ContactField) {
    setContactOrder(includedOrder.filter((f) => f !== field));
  }

  function moveContactField(index: number, direction: -1 | 1) {
    setContactOrder(moveItem(includedOrder, index, index + direction));
  }

  const projectsEnabled = outline.sections_enabled.projects !== false;

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <h2 className="font-display text-xl font-semibold">What to include</h2>

      <fieldset className="mt-4 space-y-2">
        <legend className="text-sm font-semibold text-ink">
          Contact (name always shown first)
        </legend>
        <ul className="space-y-1">
          {includedOrder.map((field, i) => (
            <li key={field} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked
                onChange={() => excludeContactField(field)}
                className="accent-[var(--color-accent)]"
              />
              <span className="flex-1">{CONTACT_FIELD_LABELS[field]}</span>
              <button
                type="button"
                title="Move up"
                disabled={i === 0}
                onClick={() => moveContactField(i, -1)}
                className="rounded border border-line px-2 py-0.5 text-xs disabled:opacity-30"
              >
                ↑
              </button>
              <button
                type="button"
                title="Move down"
                disabled={i >= includedOrder.length - 1}
                onClick={() => moveContactField(i, 1)}
                className="rounded border border-line px-2 py-0.5 text-xs disabled:opacity-30"
              >
                ↓
              </button>
            </li>
          ))}
        </ul>
        {excludedFields.length > 0 && (
          <ul className="space-y-1 border-t border-dashed border-line pt-2">
            {excludedFields.map((field) => {
              const isAvailable = available.has(field);
              return (
                <li key={field} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={false}
                    disabled={!isAvailable}
                    onChange={() => includeContactField(field)}
                    className="accent-[var(--color-accent)] disabled:opacity-50"
                  />
                  <span className={isAvailable ? "" : "text-ink-muted"}>
                    {CONTACT_FIELD_LABELS[field]}
                    {!isAvailable && " (not set)"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </fieldset>

      <fieldset className="mt-5 space-y-2">
        <legend className="text-sm font-semibold text-ink">Education</legend>
        <Toggle
          label="Show GPA"
          checked={settings.include.gpa}
          disabled={!outline.has_gpa}
          disabledHint={!outline.has_gpa ? "No GPA set on any education entry." : undefined}
          onChange={(v) => setInclude({ gpa: v })}
        />
        <Toggle
          label="Show relevant coursework"
          checked={settings.include.coursework}
          disabled={!outline.has_coursework}
          disabledHint={
            !outline.has_coursework ? "No coursework listed on any education entry." : undefined
          }
          onChange={(v) => setInclude({ coursework: v })}
        />
      </fieldset>

      {outline.experience.length > 0 && (
        <fieldset className="mt-5 space-y-2">
          <legend className="text-sm font-semibold text-ink">Experience</legend>
          {outline.experience.map((entry) => (
            <Toggle
              key={entry.id}
              label={entry.label}
              help={`${entry.bullets} bullet${entry.bullets === 1 ? "" : "s"}`}
              checked={!settings.include.exclude_experience.includes(entry.id)}
              onChange={(v) =>
                setInclude({
                  exclude_experience: v
                    ? settings.include.exclude_experience.filter((id) => id !== entry.id)
                    : [...settings.include.exclude_experience, entry.id],
                })
              }
            />
          ))}
        </fieldset>
      )}

      {projectsEnabled && outline.projects.length > 0 && (
        <fieldset className="mt-5 space-y-2">
          <legend className="text-sm font-semibold text-ink">Projects</legend>
          {outline.projects.map((entry) => (
            <Toggle
              key={entry.id}
              label={entry.label}
              help={`${entry.bullets} bullet${entry.bullets === 1 ? "" : "s"}`}
              checked={!settings.include.exclude_projects.includes(entry.id)}
              onChange={(v) =>
                setInclude({
                  exclude_projects: v
                    ? settings.include.exclude_projects.filter((id) => id !== entry.id)
                    : [...settings.include.exclude_projects, entry.id],
                })
              }
            />
          ))}
          <Toggle
            label="Show project links"
            help="Github label and hyperlink in each project's header line."
            checked={!settings.no_project_links}
            onChange={(v) => onChange({ ...settings, no_project_links: !v })}
          />
        </fieldset>
      )}
    </section>
  );
}

function Toggle({
  label,
  help,
  checked,
  disabled,
  disabledHint,
  onChange,
}: {
  label: string;
  help?: string;
  checked: boolean;
  disabled?: boolean;
  disabledHint?: string;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 accent-[var(--color-accent)] disabled:opacity-50"
      />
      <span>
        <span className="font-medium">{label}</span>
        {(disabled ? disabledHint : help) && (
          <span className="mt-0.5 block text-xs text-ink-muted">
            {disabled ? disabledHint : help}
          </span>
        )}
      </span>
    </label>
  );
}
