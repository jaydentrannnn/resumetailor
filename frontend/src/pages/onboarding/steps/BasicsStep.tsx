import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Field } from "../../../components/ui";
import { useApplicantProfile } from "../../../state/applicantProfileState";
import { useEditorState } from "../../../state/editorState";
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
      <div>
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
      </div>
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
