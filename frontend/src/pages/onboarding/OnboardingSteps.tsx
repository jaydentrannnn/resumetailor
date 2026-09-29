import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchSetupStatus,
  fetchSourceCatalog,
  type OnboardingField,
  type SetupStatus,
  type SourceCatalog,
  type SourceField,
} from "../../api";
import { ImportResumePanel } from "../../components/ImportResumePanel";
import { TemplateImportWizard } from "../../components/template/TemplateImportWizard";
import { StarterTemplatesPanel } from "../../components/template/StarterTemplatesPanel";
import { Button, Card, Field } from "../../components/ui";
import { describe } from "../../lib/errors";
import {
  FIELDS,
  packsForField,
  reviewResume,
  sourceFieldsFor,
  sourcesForField,
  sourcesFromCatalogPicks,
  suggestedEntries,
} from "../../lib/onboarding";
import { FIELD_LABELS, SOURCE_FIELDS } from "../../lib/sources";
import { useToast } from "../../lib/toast";
import { useApplicantProfile } from "../../state/applicantProfileState";
import { useEditorState } from "../../state/editorState";
import { useLibraryState } from "../../state/libraryState";
import { useRunState } from "../../state/runState";

/** Step 1: the student's field sets the skill vocabularies and job-board categories. */
export function FieldStep({
  field,
  saving,
  onChoose,
}: {
  field: OnboardingField;
  saving: boolean;
  onChoose: (field: OnboardingField) => void;
}) {
  const toast = useToast();
  const { packs, enabledPacks, setEnabled } = useLibraryState();
  const { settings, setSettings, settingsLoaded } = useRunState();
  const [picked, setPicked] = useState<OnboardingField>(field);
  const [applying, setApplying] = useState(false);
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [catalogFailed, setCatalogFailed] = useState(false);
  const [jobFields, setJobFields] = useState<SourceField[]>(() => sourceFieldsFor(field));
  const [skipped, setSkipped] = useState<Set<string>>(new Set());

  useEffect(() => {
    let live = true;
    fetchSourceCatalog()
      .then((c) => live && setCatalog(c))
      .catch(() => live && setCatalogFailed(true));
    return () => {
      live = false;
    };
  }, []);

  function pickField(next: Exclude<OnboardingField, "">) {
    setPicked(next);
    setJobFields(sourceFieldsFor(next));
    setSkipped(new Set());
  }

  const suggestions = catalog ? suggestedEntries(catalog, jobFields) : [];

  async function choose() {
    if (!picked) return;
    // Re-choosing the same field keeps any tuning done since; only a change resets it.
    if (picked !== field) {
      setApplying(true);
      try {
        await setEnabled(
          packsForField(
            enabledPacks,
            picked,
            packs.map((p) => p.id),
          ),
        );
        const sources =
          catalog && !catalogFailed
            ? sourcesFromCatalogPicks(
                settings.apply.sources,
                suggestions.filter((entry) => !skipped.has(entry.id)),
                picked,
              )
            : sourcesForField(settings.apply.sources, picked);
        setSettings({ ...settings, apply: { ...settings.apply, sources } });
      } catch (err) {
        toast.error("Could not apply your field", describe(err).detail);
        return;
      } finally {
        setApplying(false);
      }
    }
    onChoose(picked);
  }

  return (
    <section aria-labelledby="field-title" className="space-y-4">
      <div>
        <h2 id="field-title" className="text-xl font-semibold text-ink">
          What are you studying?
        </h2>
        <p className="mt-1 text-sm text-ink-muted">
          This picks the skill words ResumeTailor recognises (for example “DCF” and “discounted cash
          flow”) and which job lists to search.
        </p>
      </div>
      <div role="radiogroup" aria-labelledby="field-title" className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((option) => (
          <label
            key={option.id}
            className={`flex cursor-pointer gap-3 rounded-xl border p-4 ${
              picked === option.id ? "border-accent bg-accent-soft/40" : "border-line bg-panel"
            }`}
          >
            <input
              type="radio"
              name="field"
              className="mt-1"
              checked={picked === option.id}
              onChange={() => pickField(option.id)}
            />
            <span>
              <span className="block font-semibold text-ink">{option.label}</span>
              <span className="block text-sm text-ink-muted">{option.description}</span>
            </span>
          </label>
        ))}
      </div>
      {picked && catalog && !catalogFailed && (
        <JobSourcePicker
          fields={jobFields}
          onFields={(next) => {
            setJobFields(next);
            setSkipped(new Set());
          }}
          suggestions={suggestions}
          skipped={skipped}
          onToggle={(id) =>
            setSkipped((prev) => {
              const next = new Set(prev);
              if (!next.delete(id)) next.add(id);
              return next;
            })
          }
        />
      )}
      <div className="flex justify-end border-t border-line pt-4">
        <Button
          variant="primary"
          onClick={choose}
          disabled={!picked || !settingsLoaded}
          loading={applying || saving}
        >
          Next
        </Button>
      </div>
    </section>
  );
}

/** Which job fields to search and the catalog sources that come with them, for review. */
function JobSourcePicker({
  fields,
  onFields,
  suggestions,
  skipped,
  onToggle,
}: {
  fields: SourceField[];
  onFields: (next: SourceField[]) => void;
  suggestions: ReturnType<typeof suggestedEntries>;
  skipped: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-line bg-panel p-4">
      <fieldset>
        <legend className="text-sm font-semibold text-ink">Which jobs should we look for?</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {SOURCE_FIELDS.map((f) => (
            <label
              key={f}
              className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
                fields.includes(f) ? "border-accent bg-accent-soft/40" : "border-line"
              }`}
            >
              <input
                type="checkbox"
                checked={fields.includes(f)}
                onChange={(e) =>
                  onFields(e.target.checked ? [...fields, f] : fields.filter((x) => x !== f))
                }
              />
              {FIELD_LABELS[f]}
            </label>
          ))}
        </div>
      </fieldset>
      {suggestions.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No job lists selected. You can add some later on the Applications page.
        </p>
      ) : (
        <fieldset>
          <legend className="text-sm font-medium text-ink">Job lists to search</legend>
          <ul className="mt-1 space-y-1">
            {suggestions.map((entry) => (
              <li key={entry.id}>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={!skipped.has(entry.id)}
                    onChange={() => onToggle(entry.id)}
                  />
                  <span>
                    {entry.name}
                    <span className="block text-xs text-ink-muted">{entry.description}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}
    </div>
  );
}

/** Step 3: upload the .docx; its design becomes the template and its words the content.
 * A PDF gives the content only, so a starter template supplies the design. */
export function ResumeStep({ onScratch }: { onScratch: () => void }) {
  const [pdf, setPdf] = useState(false);
  return (
    <div className="space-y-4">
      <TemplateImportWizard title="Upload your resume" />
      {pdf ? (
        <ImportResumePanel
          title="Import the content of a PDF"
          intro="A PDF can't become your template, but its words can fill your master resume. Import them here, then pick a starter template below for the design."
        />
      ) : (
        <p className="text-sm text-ink-muted">
          Only have a PDF?{" "}
          <button
            type="button"
            onClick={() => setPdf(true)}
            className="font-semibold text-accent underline-offset-2 hover:underline"
          >
            Import its content
          </button>
          .
        </p>
      )}
      <p className="text-sm text-ink-muted">
        No Word file?{" "}
        <button
          type="button"
          onClick={onScratch}
          className="font-semibold text-accent underline-offset-2 hover:underline"
        >
          Start from scratch
        </button>{" "}
        and add your experience in the editor; you can upload a template later on the Template page.
      </p>
      <StarterTemplatesPanel />
    </div>
  );
}

/** Step 4: a summary of the imported content and anything worth fixing. */
export function ReviewStep() {
  const { resume, dirty, save, busy } = useEditorState();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  useEffect(() => {
    fetchSetupStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  const review = reviewResume(resume);
  const fit = status?.items.find((i) => i.id === "calibration");
  const template = status?.items.find((i) => i.id === "template");

  return (
    <div className="space-y-4">
      {dirty && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-warn-soft px-4 py-3 text-sm text-warn">
          <span>The imported content is not saved yet.</span>
          <Button variant="primary" size="sm" onClick={() => void save()} loading={busy}>
            Save it
          </Button>
        </div>
      )}
      <Card title="Your content">
        {review.entries === 0 ? (
          <p className="text-sm text-ink-muted">
            Nothing yet. Add your jobs, projects and activities in the{" "}
            <Link to="/profile/resume" className="font-semibold text-accent">
              resume editor
            </Link>
            ; tailoring picks from what you add there.
          </p>
        ) : (
          <>
            <p className="text-sm text-ink">
              {review.entries} entries and {review.bullets} bullet points.
            </p>
            <ul className="mt-2 flex flex-wrap gap-2 text-xs">
              {review.sections.map((s, i) => (
                <li key={i} className="rounded-full bg-paper px-2 py-1 text-ink-muted">
                  {s.title} · {s.count}
                </li>
              ))}
            </ul>
          </>
        )}
        {review.warnings.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-warn">
            {review.warnings.slice(0, 8).map((w) => (
              <li key={w}>{w}</li>
            ))}
            {review.warnings.length > 8 && <li>…and {review.warnings.length - 8} more.</li>}
          </ul>
        )}
        <Link
          to="/profile/resume"
          className="mt-3 inline-block text-sm font-semibold text-accent underline-offset-2 hover:underline"
        >
          Open the resume editor
        </Link>
      </Card>
      {status && (
        <Card title="Template and page fit">
          <p className="text-sm text-ink">
            {template?.ok ? "Your template is installed." : "No template yet."}{" "}
            {fit?.ok
              ? "Page fit is measured for it."
              : "Page fit uses estimates until it is tuned on the Template page."}
          </p>
        </Card>
      )}
    </div>
  );
}

/** Step 5: the handful of facts almost every application form asks for. */
export function BasicsStep({
  onDone,
  onSkip,
  onBack,
}: {
  onDone: () => void;
  onSkip: () => void;
  onBack: () => void;
}) {
  const { draft, setDraft, save, saving, error } = useApplicantProfile();
  const { resume } = useEditorState();
  const [prefilled, setPrefilled] = useState(false);

  // Seed empty fields from the resume's contact block once, so most students only confirm.
  useEffect(() => {
    if (prefilled || !draft || !resume) return;
    setPrefilled(true);
    const contact = resume.contact;
    const [first, ...rest] =
      contact.name && contact.name !== "Your Name" ? contact.name.trim().split(/\s+/) : [];
    const patch = {
      first_name: draft.first_name || first || "",
      last_name: draft.last_name || rest.join(" "),
      email: draft.email || (contact.email !== "you@example.com" ? contact.email : ""),
      phone: draft.phone || contact.phone || "",
    };
    if (Object.entries(patch).some(([k, v]) => v !== draft[k as keyof typeof draft]))
      setDraft({ ...draft, ...patch });
  }, [draft, resume, prefilled, setDraft]);

  if (!draft) return <p className="text-sm text-ink-muted">Loading…</p>;
  const set = (key: keyof typeof draft, value: string) => setDraft({ ...draft, [key]: value });

  return (
    <div className="space-y-4">
      <Card>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First name">
            <input
              className="field"
              autoComplete="given-name"
              value={draft.first_name}
              onChange={(e) => set("first_name", e.target.value)}
            />
          </Field>
          <Field label="Last name">
            <input
              className="field"
              autoComplete="family-name"
              value={draft.last_name}
              onChange={(e) => set("last_name", e.target.value)}
            />
          </Field>
          <Field label="Email">
            <input
              className="field"
              type="email"
              autoComplete="email"
              value={draft.email}
              onChange={(e) => set("email", e.target.value)}
            />
          </Field>
          <Field label="Phone">
            <input
              className="field"
              type="tel"
              autoComplete="tel"
              value={draft.phone}
              onChange={(e) => set("phone", e.target.value)}
            />
          </Field>
          <Field
            label="Work authorization"
            help="Visa questions are never guessed; unanswered ones wait for you."
          >
            <select
              className="field"
              value={draft.work_authorization}
              onChange={(e) => set("work_authorization", e.target.value)}
            >
              <option value="">Not set</option>
              <option value="citizen">Citizen</option>
              <option value="permanent_resident">Permanent resident</option>
              <option value="visa_holder">Visa holder</option>
              <option value="other">Other</option>
            </select>
          </Field>
        </div>
        <p className="mt-4 text-sm text-ink-muted">
          More (address, links, demographics) lives on{" "}
          <Link to="/profile/application" className="font-semibold text-accent">
            Profile → Application details
          </Link>
          .
        </p>
      </Card>
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button variant="ghost" onClick={onBack} disabled={saving}>
          Back
        </Button>
        <Button variant="ghost" className="ml-auto" onClick={onSkip} disabled={saving}>
          Skip
        </Button>
        <Button
          variant="primary"
          loading={saving}
          onClick={async () => {
            if (await save()) onDone();
          }}
        >
          Save and finish
        </Button>
      </div>
    </div>
  );
}

/** Step 6: all set. */
export function DoneStep({ onFinish, saving }: { onFinish: () => void; saving: boolean }) {
  return (
    <Card>
      <div className="space-y-3 py-4 text-center">
        <p className="text-4xl" aria-hidden="true">
          🎉
        </p>
        <h2 className="text-xl font-semibold text-ink">You're set up</h2>
        <p className="mx-auto max-w-md text-sm text-ink-muted">
          Paste a job posting on the Tailor page and get a resume matched to it, in your own design,
          in about a minute.
        </p>
        <Button variant="primary" size="lg" onClick={onFinish} loading={saving}>
          Tailor your first resume
        </Button>
      </div>
    </Card>
  );
}
