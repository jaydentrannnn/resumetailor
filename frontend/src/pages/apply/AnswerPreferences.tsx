import { useState } from "react";
import { Link } from "react-router-dom";
import { putApplicantProfile, type ApplicantProfile } from "../../api";
import { Switch } from "../../components/ui";
import { useApplicantProfile } from "../../state/applicantProfileState";

/** The two standing consents (audit #32): what each covers, and its default. */
const CONSENTS = [
  [
    "auto_accept_notices",
    "Agree to required notices",
    "Privacy, EEO and data notices, and consent to background and drug screening. Advertising opt-ins stay No.",
    true,
  ],
  [
    "auto_accept_agreements",
    "Agree to terms, certifications and signatures",
    "Terms and conditions, arbitration, statements that your application is true and complete, and typed e-signatures. Off: Fill leaves them for you.",
    false,
  ],
] as const;

export function AnswerPreferences() {
  const profile = useApplicantProfile();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!profile.saved) return <p className="text-xs text-ink-muted">Loading answer preferences…</p>;
  async function save(patch: Partial<ApplicantProfile>) {
    if (!profile.saved) return;
    setBusy(true);
    setError("");
    try {
      const pending = profile.dirty ? profile.draft : null;
      profile.accept(await putApplicantProfile({ ...profile.saved, ...patch }));
      if (pending) profile.setDraft({ ...pending, ...patch });
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <fieldset disabled={busy} className="space-y-3">
      {CONSENTS.map(([key, label, covers, fallback]) => (
        <div key={key} className="space-y-1">
          <label className="flex items-center justify-between gap-3">
            <span>{label}</span>
            <Switch
              checked={profile.saved![key] ?? fallback}
              onChange={(value) => void save({ [key]: value })}
            />
          </label>
          <p className="text-xs text-ink-muted">{covers}</p>
        </div>
      ))}
      {(
        [
          ["consider_other_positions", "Consider me for other positions"],
          ["minimum_qualifications_answer", "General minimum-qualification questions"],
        ] as const
      ).map(([key, label]) => (
        <label key={key} className="block">
          <span className="mb-1 block">{label}</span>
          <select
            className="field"
            aria-label={label}
            value={profile.saved![key] == null ? "" : profile.saved![key] ? "yes" : "no"}
            onChange={(e) =>
              void save({ [key]: e.target.value === "" ? null : e.target.value === "yes" })
            }
          >
            <option value="">Ask me</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
      ))}
      <p className="text-xs text-ink-muted">
        The qualification answer is your declaration. Specific school, date, authorization, and
        skill questions use their corresponding answers.
      </p>
      <p className="text-sm">
        Advertising-partner sharing: <strong>No</strong>
      </p>
      <Link className="rt-link text-xs" to="/profile/application">
        Edit experience, information sources, and application details
      </Link>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}
