import { useState } from "react";
import { Link } from "react-router-dom";
import { putApplicantProfile, type ApplicantProfile } from "../../api";
import { Switch } from "../../components/ui";
import { useApplicantProfile } from "../../state/applicantProfileState";

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
      <label className="flex items-center justify-between gap-3">
        <span>Agree to required notices and consents</span>
        <Switch
          checked={profile.saved.auto_accept_routine_acknowledgements ?? true}
          onChange={(value) => void save({ auto_accept_routine_acknowledgements: value })}
        />
      </label>
      <p className="text-xs text-ink-muted">
        Required privacy, screening, and similar notices. Advertising opt-ins stay No.
      </p>
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
