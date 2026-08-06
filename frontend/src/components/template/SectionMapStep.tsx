import type {
  TemplateAnalyzeResponse,
  TemplateHeadingKind,
  TemplateSection,
} from "../../api";

type Enabled = {
  education: boolean;
  experience: boolean;
  projects: boolean;
  skills: boolean;
  list_section: boolean;
};

const SECTION_ROWS: readonly [keyof Enabled, string][] = [
  ["experience", "Experience (required)"],
  ["education", "Education"],
  ["projects", "Projects"],
  ["skills", "Skills"],
  ["list_section", "Simple list (certifications, awards, …)"],
];

//: Wire kind -> the label shown in the per-heading remap `<select>`. `null` reads as
//: "Not a section" — the user telling the analyzer a candidate heading is actually
//: body text (a job title, an entry header that happens to contain a keyword, …).
const KIND_OPTIONS: readonly [TemplateHeadingKind, string][] = [
  ["experience", "Experience"],
  ["education", "Education"],
  ["projects", "Projects"],
  ["skills", "Skills"],
  ["list", "Simple list"],
  [null, "Not a section"],
];

type Props = {
  analysis: TemplateAnalyzeResponse;
  profile: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  headingOverrides: Record<number, TemplateHeadingKind>;
  remapBusy: boolean;
  onRemapHeading: (paragraphId: number, kind: TemplateHeadingKind) => void;
};

/**
 * Confirm what the analyzer detected, one heading at a time, then which kinds to keep.
 *
 * Two controls, deliberately kept separate:
 * - **Detected headings** (below) is the primary confirmation step — one `<select>`
 *   per heading the analyzer actually found in the document, defaulting to its
 *   detected kind. Reassigning one is a real server round trip (`onRemapHeading`):
 *   changing what a heading *is* can change entry splitting, field reconciliation,
 *   and date detection for the rest of the document, not just that row, so the
 *   result the user sees always reflects the analyzer's own downstream logic rather
 *   than a client-side guess.
 * - **Sections to include** is a coarser, kind-level on/off toggle — useful when a
 *   kind was detected correctly but the user simply does not want it in the
 *   template (e.g. omit Projects even though a Projects heading exists). Experience
 *   cannot be disabled. Multiple headings of one kind, or a plain-list section,
 *   upgrade the template to "generic" mode automatically.
 */
export function SectionMapStep({
  analysis,
  profile,
  onChange,
  headingOverrides,
  remapBusy,
  onRemapHeading,
}: Props) {
  const enabled = (profile.enabled as Enabled | undefined) ?? {
    education: true,
    experience: true,
    projects: true,
    skills: true,
    list_section: false,
  };
  const contact = (profile.contact as { separator?: string } | undefined) ?? {};

  // `analysis.sections` is every detected heading, in document order — no longer one
  // per key, since a resume can have several headings of the same kind (e.g. WORK
  // EXPERIENCE + LEADERSHIP EXPERIENCE both classify as "experience").
  const sectionsByKey = new Map<string, TemplateSection[]>();
  for (const s of analysis.sections) {
    const list = sectionsByKey.get(s.key) ?? [];
    list.push(s);
    sectionsByKey.set(s.key, list);
  }

  const sectionMode = (profile.section_mode as string | undefined) ?? "fixed";
  const isGeneric = sectionMode === "generic";

  const setEnabled = (key: keyof Enabled, value: boolean) => {
    /** Toggle a section kind and drop/restore its mapping blob. */
    if (key === "experience") return;
    const nextEnabled = { ...enabled, [key]: value };
    const next: Record<string, unknown> = {
      ...profile,
      enabled: nextEnabled,
    };
    const profileKey = key === "list_section" ? "list_section" : key;
    if (!value) {
      next[profileKey] = null;
    } else if (analysis.suggested_profile && analysis.suggested_profile[profileKey]) {
      next[profileKey] = analysis.suggested_profile[profileKey];
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
          Detected headings
        </p>
        <p className="mt-1 text-xs text-ink-muted">
          Confirm what each heading is, or correct it — reassigning one re-runs
          detection for the rest of the document.
        </p>
        <div className="mt-2 space-y-1.5">
          {analysis.sections.length === 0 ? (
            <p className="rounded-lg border border-line/80 bg-paper/40 px-3 py-2 text-ink-muted">
              No headings detected.
            </p>
          ) : (
            analysis.sections.map((s) => {
              const overridden = headingOverrides[s.heading_paragraph_id];
              const currentKind: TemplateHeadingKind =
                overridden !== undefined ? overridden : (s.key as TemplateHeadingKind);
              return (
                <div
                  key={s.heading_paragraph_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line/80 bg-paper/40 px-3 py-2"
                >
                  <div className="min-w-0">
                    <span className="font-medium text-ink">“{s.heading_text}”</span>
                    <span className="ml-2 text-xs text-ink-muted">
                      paragraph {s.heading_paragraph_id} · {(s.confidence * 100).toFixed(0)}%
                      conf.
                    </span>
                  </div>
                  <select
                    value={currentKind ?? ""}
                    disabled={remapBusy}
                    onChange={(e) =>
                      onRemapHeading(
                        s.heading_paragraph_id,
                        (e.target.value || null) as TemplateHeadingKind,
                      )
                    }
                    className="rounded-md border border-line bg-paper px-2 py-1 text-xs text-ink disabled:opacity-50"
                  >
                    {KIND_OPTIONS.map(([kind, label]) => (
                      <option key={label} value={kind ?? ""}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })
          )}
        </div>
      </div>

      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
          Sections to include
        </p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {SECTION_ROWS.map(([key, label]) => {
            const detected = sectionsByKey.get(key) ?? [];
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
                  disabled={key === "experience" || detected.length === 0}
                  onChange={(e) => setEnabled(key, e.target.checked)}
                />
                <span>
                  <span className="font-medium text-ink">{label}</span>
                  <span className="block text-xs text-ink-muted">
                    {detected.length === 0
                      ? "Not detected in upload"
                      : detected.length === 1
                        ? `Heading: “${detected[0].heading_text}”`
                        : `${detected.length} headings: ${detected
                            .map((s) => `“${s.heading_text}”`)
                            .join(", ")}`}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      {isGeneric && (
        <div className="rounded-lg border border-accent/40 bg-accent-soft px-3 py-2 text-xs text-ink">
          <p className="font-medium text-accent">
            This template will support multiple &amp; custom sections.
          </p>
          <p className="mt-1 text-ink-muted">
            Detection found more sections than a fixed layout can represent (either two
            headings of the same kind, or a plain-list section), so the tagged template
            will render whatever sections exist on the Master Resume tab — in their own
            order, under their own titles — with no rebuild needed to add, rename, or
            reorder one there later.
          </p>
        </div>
      )}

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
