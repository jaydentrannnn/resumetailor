import { Link, useLocation } from "react-router-dom";
import { useState, type ReactNode } from "react";
import { type ApplicantProfile } from "../api";
import { ProfileGapBanner as GapBanner } from "../components/ProfileGapBanner";
import { useApplicantProfile } from "../state/applicantProfileState";
import { useEditorState } from "../state/editorState";
import { EditorPage } from "./EditorPage";
import { LanguagesEditor } from "../components/LanguagesEditor";

const labels: Partial<Record<keyof ApplicantProfile, string>> = {
  first_name: "Legal first name",
  middle_name: "Middle name",
  last_name: "Legal last name",
  preferred_name: "Preferred name",
  pronouns: "Pronouns",
  email: "Email",
  phone: "Phone",
  linkedin_url: "LinkedIn URL",
  github_url: "GitHub URL",
  portfolio_url: "Portfolio URL",
  address_line1: "Address line 1",
  address_line2: "Address line 2",
  city: "City",
  state: "State or province",
  postal_code: "Postal code",
  country: "Country",
  phone_country_code: "Phone country code",
  phone_country_region: "Phone country or region",
  phone_device_type: "Phone device type",
  authorization_country: "Authorization country",
  earliest_start: "Earliest start",
  notice_period: "Notice period",
  location_preference: "Location preference",
  highest_education_obtained: "Highest education obtained",
  salary_expectation: "Salary expectation (text)",
  salary_hourly_min: "Hourly minimum ($)",
  salary_hourly_max: "Hourly maximum ($)",
  salary_yearly_min: "Yearly minimum ($)",
  salary_yearly_max: "Yearly maximum ($)",
  referred_by: "Referred by",
  how_heard: "How heard",
  workday_email: "Workday email",
  workday_password: "Workday password",
};
const groups: Array<{ title: string; fields: (keyof ApplicantProfile)[] }> = [
  {
    title: "Address and phone details",
    fields: [
      "address_line1",
      "address_line2",
      "city",
      "state",
      "postal_code",
      "country",
      "phone_country_code",
      "phone_country_region",
      "phone_device_type",
    ],
  },
  {
    title: "Work authorization and sponsorship",
    fields: [
      "work_authorization",
      "authorization_country",
      "authorized_to_work",
      "requires_sponsorship_now",
      "requires_sponsorship_future",
      "f1_opt_eligible",
    ],
  },
  {
    title: "Availability and location preferences",
    fields: ["earliest_start", "notice_period", "willing_to_relocate", "location_preference"],
  },
  {
    title: "Salary",
    fields: [
      "salary_hourly_min",
      "salary_hourly_max",
      "salary_yearly_min",
      "salary_yearly_max",
      "salary_expectation",
    ],
  },
  { title: "Education", fields: ["highest_education_obtained"] },
  { title: "Voluntary information", fields: ["pronouns", "over_18", "relatives_at_company"] },
  { title: "Languages", fields: [] },
  { title: "Application accounts", fields: ["workday_email", "workday_password"] },
  {
    title: "Saved answers and other preferences",
    fields: ["referred_by", "how_heard", "portfolio_url", "portfolio_only_when_asked"],
  },
];
const contactPairs: Array<{
  resume: "email" | "phone" | "linkedin" | "github";
  applicant: "email" | "phone" | "linkedin_url" | "github_url";
  label: string;
}> = [
  { resume: "email", applicant: "email", label: "Email" },
  { resume: "phone", applicant: "phone", label: "Phone" },
  { resume: "linkedin", applicant: "linkedin_url", label: "LinkedIn URL" },
  { resume: "github", applicant: "github_url", label: "GitHub URL" },
];
const numberFields = new Set<keyof ApplicantProfile>([
  "salary_hourly_min",
  "salary_hourly_max",
  "salary_yearly_min",
  "salary_yearly_max",
]);
/** Canonical fill keys whose profile field is named differently (`packet.PROFILE_FIELDS`). */
const profileKey: Record<string, string> = { requires_sponsorship: "requires_sponsorship_now" };
function format(field: string) {
  return (
    labels[field as keyof ApplicantProfile] ??
    field.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase())
  );
}
export function ProfilePage() {
  const path = useLocation().pathname;
  const section = path.endsWith("/resume")
    ? "resume"
    : path.endsWith("/application")
      ? "application"
      : "personal";
  const { resume, setResume, dirty: resumeDirty, save: saveResume } = useEditorState();
  const applicant = useApplicantProfile();
  const draft = applicant.draft;
  const educationSection = resume?.sections.find((section) => section.kind === "education");
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const gapFields = new Set(applicant.gaps.map((gap) => profileKey[gap.key] ?? gap.key));
  function openGroup(section: string) {
    setOpenGroups((current) => new Set(current).add(section));
    document.getElementById(`profile-group-${section}`)?.scrollIntoView({ block: "start" });
  }
  function set(field: keyof ApplicantProfile, value: string | number | boolean | null) {
    if (draft) applicant.setDraft({ ...draft, [field]: value });
  }
  /** A saved-profile gap note under a field that forms ask for. */
  function gapNote(key: string): ReactNode {
    return gapFields.has(key) ? (
      <span className="mt-1 block text-xs text-warn">
        Forms ask for this; blank means autofill skips it.
      </span>
    ) : null;
  }
  function field(key: keyof ApplicantProfile) {
    if (!draft) return null;
    const value = draft[key];
    if (numberFields.has(key))
      return (
        <label key={key} className="block text-sm">
          {format(key)}
          <input
            className="field mt-1"
            type="number"
            min={0}
            step="any"
            inputMode="decimal"
            value={value == null ? "" : String(value)}
            onChange={(e) => set(key, e.target.value === "" ? null : Number(e.target.value))}
          />
          {gapNote(key)}
        </label>
      );
    if (key === "work_authorization")
      return (
        <label key={key} className="block text-sm">
          Work authorization
          <select
            className="field mt-1"
            value={draft.work_authorization}
            onChange={(e) => set(key, e.target.value)}
          >
            <option value="">Not set</option>
            <option value="citizen">Citizen</option>
            <option value="permanent_resident">Permanent resident</option>
            <option value="visa_holder">Visa holder</option>
            <option value="other">Other</option>
          </select>
          {gapNote(key)}
        </label>
      );
    if (
      typeof value === "boolean" ||
      (value == null &&
        [
          "authorized_to_work",
          "requires_sponsorship_now",
          "requires_sponsorship_future",
          "f1_opt_eligible",
          "willing_to_relocate",
          "over_18",
          "relatives_at_company",
        ].includes(key))
    )
      return (
        <label key={key} className="block text-sm">
          {format(key)}
          <select
            className="field mt-1"
            value={value == null ? "" : String(value)}
            onChange={(e) => set(key, e.target.value === "" ? null : e.target.value === "true")}
          >
            <option value="">Not set</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
          {gapNote(key)}
        </label>
      );
    const fallback = applicant.defaults[key];
    const placeholder =
      key === "workday_password" && applicant.passwordSet
        ? "Saved password · leave blank to keep"
        : fallback
          ? `Default: ${fallback}`
          : undefined;
    return (
      <label key={key} className="block text-sm">
        {format(key)}
        <input
          className="field mt-1"
          type={key === "workday_password" ? "password" : "text"}
          autoComplete={key === "workday_password" ? "new-password" : undefined}
          value={String(value ?? "")}
          placeholder={placeholder}
          onChange={(e) => set(key, e.target.value)}
        />
        {gapNote(key)}
      </label>
    );
  }
  return (
    <div className="space-y-5">
      <header>
        <h1 className="font-display text-[28px] font-semibold">Profile</h1>
        <p className="text-sm text-ink-muted">
          Resume facts and application details are saved separately.
        </p>
      </header>
      <nav className="flex flex-wrap gap-2 border-b border-line pb-2">
        {[
          ["personal", "Personal information"],
          ["resume", "Resume content"],
          ["application", "Application details"],
        ].map(([id, label]) => (
          <Link
            key={id}
            to={`/profile/${id}`}
            className={`rounded-md px-3 py-2 text-sm ${section === id ? "bg-accent text-on-accent" : "text-ink-muted hover:bg-accent-soft"}`}
          >
            {label}
          </Link>
        ))}
      </nav>
      {section === "resume" && (
        <div className="space-y-4">
          <GapBanner
            gaps={applicant.gaps.filter((gap) => gap.path === "/profile/resume")}
            onOpen={() =>
              educationSection &&
              document
                .getElementById(`resume-section-${educationSection.id}`)
                ?.scrollIntoView({ block: "start" })
            }
          />
          <EditorPage showContact={false} />
        </div>
      )}
      {section === "personal" && (
        <div className="space-y-4">
          <GapBanner
            gaps={applicant.gaps.filter((gap) => gap.path === "/profile/personal")}
            onOpen={() =>
              document.getElementById("application-contact")?.scrollIntoView({ block: "start" })
            }
          />
          <section className="rounded-lg border border-line bg-panel p-5">
            <h2 className="text-lg font-semibold">Resume contact</h2>
            <p className="text-xs text-ink-muted">
              These fields appear on your resume. Save resume changes separately.
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {(["name", "email", "phone", "location", "linkedin", "github"] as const).map(
                (key) => (
                  <label key={key} className="text-sm">
                    {format(key)}
                    <input
                      className="field mt-1"
                      value={resume?.contact[key] ?? ""}
                      onChange={(e) =>
                        resume &&
                        setResume({
                          ...resume,
                          contact: { ...resume.contact, [key]: e.target.value },
                        })
                      }
                    />
                  </label>
                ),
              )}
            </div>
            <button
              className="mt-3 rounded-md bg-accent px-3 text-sm text-on-accent"
              disabled={!resumeDirty}
              onClick={() => void saveResume()}
            >
              Save resume contact
            </button>
          </section>
          <section id="application-contact" className="rounded-lg border border-line bg-panel p-5">
            <h2 className="text-lg font-semibold">Application contact</h2>
            <p className="text-xs text-ink-muted">
              An empty application value uses the saved resume value. Overrides remain explicit
              until cleared.
            </p>
            {resumeDirty && (
              <p className="mt-2 text-xs text-warn">
                Resume contact has unsaved edits. Save those changes before relying on the resume
                fallback in a future application.
              </p>
            )}
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {contactPairs.map((pair) => (
                <div key={pair.applicant}>
                  <label className="text-sm">
                    {pair.label} ·{" "}
                    {draft?.[pair.applicant] ? "Application override" : "From resume"}
                    <input
                      className="field mt-1"
                      value={draft?.[pair.applicant] ?? ""}
                      placeholder={resume?.contact[pair.resume] ?? ""}
                      onChange={(e) => set(pair.applicant, e.target.value)}
                    />
                  </label>
                  <button
                    className="mt-1 text-xs text-accent underline"
                    onClick={() => set(pair.applicant, "")}
                  >
                    Use resume value
                  </button>
                </div>
              ))}
            </div>
            <h3 className="mt-4 font-semibold">Names used on applications</h3>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              {(["first_name", "middle_name", "last_name", "preferred_name"] as const).map(field)}
            </div>
          </section>
        </div>
      )}
      {section === "application" && (
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">
            Saved changes apply from the next fill: each fill rebuilds the application kit from this
            profile and your resume.
          </p>
          <GapBanner
            gaps={applicant.gaps.filter((gap) => gap.path === "/profile/application")}
            onOpen={openGroup}
          />
          {groups.map((group) => (
            <details
              key={group.title}
              id={`profile-group-${group.title}`}
              open={openGroups.has(group.title)}
              onToggle={(e) => {
                const isOpen = e.currentTarget.open;
                setOpenGroups((current) => {
                  const next = new Set(current);
                  if (isOpen) next.add(group.title);
                  else next.delete(group.title);
                  return next;
                });
              }}
              className="rounded-lg border border-line bg-panel p-4"
            >
              <summary className="cursor-pointer font-semibold">{group.title}</summary>
              {group.title === "Education" && (
                <div className="mt-3 text-xs text-ink-muted">
                  <p>
                    School, degree, major, GPA and dates are answered from the Education section of
                    your resume; add or correct them there.
                  </p>
                  <Link className="mt-2 inline-block text-accent underline" to="/profile/resume">
                    Edit education on the resume
                  </Link>
                </div>
              )}
              {group.title === "Salary" && (
                <p className="mt-3 text-xs text-ink-muted">
                  Salary questions are answered from your maximum: the posting's top pay when it is
                  below your maximum, otherwise your maximum, in the posting's unit (hourly ↔ yearly
                  at 2,080 hours). With no posted pay, intern and co-op roles use your hourly
                  maximum and other roles your yearly maximum. Leave the maximums empty to answer
                  salary questions yourself.
                </p>
              )}
              {group.fields.length > 0 && (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">{group.fields.map(field)}</div>
              )}
              {group.title === "Languages" && draft && (
                <LanguagesEditor
                  languages={draft.languages ?? []}
                  onChange={(languages) => applicant.setDraft({ ...draft, languages })}
                />
              )}
              {group.title === "Voluntary information" && (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {(["gender", "race", "race_detail", "veteran", "disability"] as const).map(
                    (key) => (
                      <label key={key} className="text-sm">
                        {format(key)}
                        <input
                          className="field mt-1"
                          value={draft?.eeo[key] ?? ""}
                          onChange={(e) =>
                            draft &&
                            applicant.setDraft({
                              ...draft,
                              eeo: { ...draft.eeo, [key]: e.target.value },
                            })
                          }
                        />
                      </label>
                    ),
                  )}
                  <label className="text-sm">
                    Hispanic or Latino
                    <select
                      className="field mt-1"
                      value={
                        draft?.eeo.hispanic_latino == null ? "" : String(draft.eeo.hispanic_latino)
                      }
                      onChange={(e) =>
                        draft &&
                        applicant.setDraft({
                          ...draft,
                          eeo: {
                            ...draft.eeo,
                            hispanic_latino:
                              e.target.value === "" ? null : e.target.value === "true",
                          },
                        })
                      }
                    >
                      <option value="">Not set</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  </label>
                </div>
              )}
              {group.title === "Saved answers and other preferences" && (
                <div className="mt-4">
                  <h3 className="text-sm font-semibold">Custom answers</h3>
                  {Object.entries(draft?.custom_answers ?? {}).map(([question, answer]) => (
                    <label key={question} className="mt-2 block text-sm">
                      {question}
                      <textarea
                        className="field mt-1"
                        value={answer}
                        onChange={(e) =>
                          draft &&
                          applicant.setDraft({
                            ...draft,
                            custom_answers: { ...draft.custom_answers, [question]: e.target.value },
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
              )}
            </details>
          ))}
        </div>
      )}
      {section !== "resume" && (
        <div className="sticky bottom-0 flex flex-wrap items-center gap-3 border border-line bg-panel p-3">
          <button
            className="rounded-md bg-accent px-4 text-sm text-on-accent disabled:opacity-50"
            disabled={!applicant.dirty || applicant.saving}
            onClick={() => void applicant.save()}
          >
            {applicant.saving ? "Saving…" : "Save application details"}
          </button>
          {applicant.dirty && (
            <button className="text-sm text-ink-muted underline" onClick={applicant.discard}>
              Discard changes
            </button>
          )}
          {applicant.error && (
            <span role="alert" className="text-sm text-danger">
              {applicant.error}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
