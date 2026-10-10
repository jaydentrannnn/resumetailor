import type { ContactField, JobSettings, ResumeOutline } from "../api";
import { orderedSections } from "../lib/includeSections";
import { moveItem } from "../lib/resumeEdit";
import { effectiveSectionOrder } from "../lib/sectionOrder";
import { useResumeOutline } from "../lib/useResumeOutline";
import { Toggle } from "./Field";
import { SectionIncludeRow } from "./SectionIncludeRow";

const ALL_CONTACT_FIELDS: ContactField[] = ["location", "email", "phone", "linkedin", "github"];

const CONTACT_FIELD_LABELS: Record<ContactField, string> = {
  location: "Location",
  email: "Email",
  phone: "Phone",
  linkedin: "LinkedIn",
  github: "GitHub",
};

const ARROW =
  "flex min-h-6 min-w-6 items-center justify-center rounded-sm border border-line-hover bg-field text-xs hover:border-ink disabled:opacity-30";

type IncludePatch = (patch: Partial<JobSettings["include"]>) => void;

/**
 * Centralized "what to leave out" tile: contact field order/visibility, then one list of
 * sections in print order — each a collapsible row with its include switch, reorder
 * arrows and per-entry switches (skill groups and education entries too).
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
  const { outline, error } = useResumeOutline();

  const setInclude: IncludePatch = (patch) =>
    onChange({ ...settings, include: { ...settings.include, ...patch } });

  if (error || !outline) {
    return (
      <section className="min-w-0">
        <h3 className="rt-tile-title">What to include</h3>
        <p className={`mt-2 text-sm ${error ? "text-danger" : "text-ink-muted"}`}>
          {error ?? "Loading…"}
        </p>
      </section>
    );
  }

  return (
    <section className="min-w-0">
      <h3 className="rt-tile-title">What to include</h3>
      <ContactFields outline={outline} settings={settings} setInclude={setInclude} />
      <SectionList outline={outline} settings={settings} setInclude={setInclude} />
    </section>
  );
}

type PartProps = { outline: ResumeOutline; settings: JobSettings; setInclude: IncludePatch };

function ContactFields({ outline, settings, setInclude }: PartProps) {
  const available = new Set(outline.available_contact_fields);
  const requestedOrder =
    settings.include.contact_fields ?? outline.default_contact_order ?? ALL_CONTACT_FIELDS;
  const includedOrder = (requestedOrder as ContactField[]).filter((f) => available.has(f));
  const excludedFields = ALL_CONTACT_FIELDS.filter((f) => !includedOrder.includes(f));
  const setOrder = (next: ContactField[]) => setInclude({ contact_fields: next });

  return (
    <fieldset className="mt-4 space-y-2">
      <legend className="text-sm font-semibold text-ink">Contact (name always shown first)</legend>
      <ul className="space-y-1">
        {includedOrder.map((field, i) => (
          <li key={field} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked
              onChange={() => setOrder(includedOrder.filter((f) => f !== field))}
              className="accent-[var(--color-accent)]"
            />
            <span className="flex-1">{CONTACT_FIELD_LABELS[field]}</span>
            <button
              type="button"
              title="Move up"
              aria-label={`Move ${CONTACT_FIELD_LABELS[field]} up`}
              disabled={i === 0}
              onClick={() => setOrder(moveItem(includedOrder, i, i - 1))}
              className={ARROW}
            >
              ↑
            </button>
            <button
              type="button"
              title="Move down"
              aria-label={`Move ${CONTACT_FIELD_LABELS[field]} down`}
              disabled={i >= includedOrder.length - 1}
              onClick={() => setOrder(moveItem(includedOrder, i, i + 1))}
              className={ARROW}
            >
              ↓
            </button>
          </li>
        ))}
      </ul>
      {excludedFields.length > 0 && (
        <ul className="space-y-1 border-t border-line pt-2">
          {excludedFields.map((field) => {
            const isAvailable = available.has(field);
            return (
              <li key={field} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={false}
                  disabled={!isAvailable}
                  onChange={() => setOrder([...includedOrder, field])}
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
  );
}

/** Every section in print order, one collapsible row each. */
function SectionList({ outline, settings, setInclude }: PartProps) {
  const projectsEnabled = outline.sections_enabled.projects !== false;
  const isGeneric = outline.section_mode === "generic";
  const sections = orderedSections(outline, settings.include).filter(
    (s) => s.kind !== "project" || projectsEnabled,
  );
  const firstEducationId = sections.find((s) => s.kind === "education")?.id;

  function moveSection(index: number, direction: -1 | 1) {
    // Rows are a filtered view; reorder the full per-run order so hidden ids keep their place.
    const order = effectiveSectionOrder(settings.include.section_order, outline.sections);
    const from = order.indexOf(sections[index].id);
    const to = order.indexOf(sections[index + direction].id);
    setInclude({ section_order: moveItem(order, from, to) });
  }

  return (
    <fieldset className="mt-5 space-y-2">
      <legend className="text-sm font-semibold text-ink">Sections</legend>
      {!isGeneric && <FixedOrderNote />}
      <ul className="space-y-1">
        {sections.map((section, i) => (
          <SectionIncludeRow
            key={section.id}
            section={section}
            include={settings.include}
            onInclude={setInclude}
            canMoveUp={isGeneric && i > 0}
            canMoveDown={isGeneric && i < sections.length - 1}
            onMove={(d) => moveSection(i, d)}
            extra={
              section.id === firstEducationId ? (
                <EducationExtras outline={outline} settings={settings} setInclude={setInclude} />
              ) : undefined
            }
          />
        ))}
      </ul>
    </fieldset>
  );
}

/** Why the arrows are disabled under a fixed template. */
function FixedOrderNote() {
  return (
    <details className="group text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-attn">
        <span>Reordering here has no effect on this template.</span>
        <span className="text-ink-muted underline-offset-2 group-open:hidden">Why?</span>
        <span className="hidden text-ink-muted underline-offset-2 group-open:inline">Hide</span>
      </summary>
      <p className="mt-1.5 text-ink-muted">
        This template renders sections in a fixed order baked into the file — reordering here is
        a per-run override and has no effect until the template is re-imported through the
        Template tab in multi-section (&quot;generic&quot;) mode. Stored section order lives on
        the Master resume tab.
      </p>
    </details>
  );
}

/** GPA and coursework switches, shown inside the (first) Education row. */
function EducationExtras({ outline, settings, setInclude }: PartProps) {
  return (
    <div className="space-y-2 border-b border-line pb-2.5">
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
    </div>
  );
}
