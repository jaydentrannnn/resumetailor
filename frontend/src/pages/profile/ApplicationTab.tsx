import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ApplicantProfile } from "../../api";
import { LanguagesEditor } from "../../components/LanguagesEditor";
import { ProfileGapBanner } from "../../components/ProfileGapBanner";
import {
  PROFILE_GROUPS,
  classYearFor,
  fieldLabel,
  sponsorshipFromVisa,
} from "../../lib/profileForm";
import type { Education } from "../../lib/resumeEdit";
import { useApplicantProfile } from "../../state/applicantProfileState";
import type { FieldContext } from "./fieldContext";
import { ProfileField } from "./ProfileField";
import { TranscriptUpload } from "./TranscriptUpload";
import { SavedAnswersList } from "./SavedAnswersList";

const yesNo = (value: boolean) => (value ? "Yes" : "No");

/** Plain-language note under a field, mostly "what a blank value means". */
function hintFor(key: keyof ApplicantProfile, draft: ApplicantProfile): ReactNode {
  const fromVisa = sponsorshipFromVisa(draft.visa_status);
  switch (key) {
    case "visa_status":
      return "Sets the sponsorship answers below unless you choose them yourself.";
    case "requires_sponsorship_now":
      return draft[key] == null && fromVisa ? `Auto from visa: ${yesNo(fromVisa[0])}` : null;
    case "requires_sponsorship_future":
      return draft[key] == null && fromVisa ? `Auto from visa: ${yesNo(fromVisa[1])}` : null;
    case "f1_opt_eligible":
      return draft[key] == null && draft.visa_status?.startsWith("f1")
        ? "Auto from visa: Yes"
        : null;
    case "graduation_date":
      return "Blank uses the dates on your resume's Education entry.";
    case "class_year": {
      if (draft.class_year) return null;
      const auto = classYearFor(draft.graduation_date);
      return auto
        ? `Auto: ${auto} (from your graduation month)`
        : "Worked out from your graduation month.";
    }
    case "gpa_display":
      return "Blank uses the GPA on your resume.";
    case "school_email":
      return "Blank uses your email when it ends in .edu.";
    case "hours_per_week_available":
      return "For part-time and co-op forms.";
    default:
      return null;
  }
}

/** Blank, but answered from another field (sponsorship from the visa). */
function autoAnswered(key: keyof ApplicantProfile, draft: ApplicantProfile): boolean {
  if (draft[key] != null) return false;
  if (key === "requires_sponsorship_now" || key === "requires_sponsorship_future")
    return sponsorshipFromVisa(draft.visa_status) !== null;
  return key === "f1_opt_eligible" && !!draft.visa_status?.startsWith("f1");
}

/**
 * Application details: collapsible groups of the facts forms ask for. Every group starts
 * open; the ones the student collapses stay collapsed on the next visit.
 */
export function ApplicationTab({
  ctx,
  closed,
  onToggle,
  onOpenGroup,
  education,
}: {
  ctx: FieldContext;
  closed: Set<string>;
  onToggle: (id: string, open: boolean) => void;
  onOpenGroup: (id: string) => void;
  education: Education[];
}) {
  const applicant = useApplicantProfile();
  const { draft } = ctx;
  const setDraft = (next: Partial<ApplicantProfile>) => applicant.setDraft({ ...draft, ...next });
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-muted">
        Autofill answers application forms from these details. Changes apply from the next fill.
      </p>
      <ProfileGapBanner
        gaps={applicant.gaps.filter((gap) => gap.path === "/profile/application")}
        onOpen={onOpenGroup}
      />
      {PROFILE_GROUPS.map((group) => (
        <details
          key={group.id}
          id={`profile-group-${group.id}`}
          open={!closed.has(group.id)}
          onToggle={(e) => onToggle(group.id, e.currentTarget.open)}
          className="rounded-lg border border-line bg-panel p-4"
        >
          <summary className="cursor-pointer font-semibold">{group.title}</summary>
          {group.id === "Education" && <EducationSummary education={education} />}
          {group.id === "Salary" && (
            <p className="mt-3 text-xs text-ink-muted">
              Salary questions are answered from your maximum: the posting's top pay when it is
              below your maximum, otherwise your maximum, in the posting's unit (hourly ↔ yearly at
              2,080 hours). With no posted pay, intern and co-op roles use your hourly maximum and
              other roles your yearly maximum. Leave the maximums empty to answer salary questions
              yourself.
            </p>
          )}
          {group.id === "Voluntary information" && (
            <p className="mt-3 rounded-md bg-accent-soft px-3 py-2 text-xs text-accent">
              Only used to answer voluntary EEO questions; "Decline to answer" is always allowed.
              These answers never affect how your resume is tailored.
            </p>
          )}
          {group.id === "Application accounts" && (
            <p className="mt-3 text-xs text-ink-muted">
              The Workday password is kept in your system's password store (or an encrypted file),
              never in your profile file.
            </p>
          )}
          {group.fields.length > 0 && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {group.fields.map((key) => (
                <ProfileField
                  key={key}
                  name={key}
                  ctx={ctx}
                  hint={hintFor(key, draft)}
                  auto={autoAnswered(key, draft)}
                />
              ))}
              {group.id === "Education" && <TranscriptUpload />}
            </div>
          )}
          {group.id === "Voluntary information" && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {(["gender", "race", "race_detail", "veteran", "disability"] as const).map((key) => (
                <label key={key} className="text-sm">
                  {fieldLabel(key)}
                  <input
                    className="field mt-1"
                    value={draft.eeo[key] ?? ""}
                    placeholder="Blank skips the question"
                    onChange={(e) => setDraft({ eeo: { ...draft.eeo, [key]: e.target.value } })}
                  />
                </label>
              ))}
              <label className="text-sm">
                Hispanic or Latino
                <select
                  className="field mt-1"
                  value={draft.eeo.hispanic_latino == null ? "" : String(draft.eeo.hispanic_latino)}
                  onChange={(e) =>
                    setDraft({
                      eeo: {
                        ...draft.eeo,
                        hispanic_latino: e.target.value === "" ? null : e.target.value === "true",
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
          {group.id === "Languages" && (
            <LanguagesEditor
              languages={draft.languages ?? []}
              onChange={(languages) => setDraft({ languages })}
            />
          )}
          {group.id === "Saved answers and other preferences" && <SavedAnswersList />}
          {group.id === "Saved answers and other preferences" && (
            <div className="mt-4">
              <h3 className="text-sm font-semibold">Custom answers</h3>
              {Object.keys(draft.custom_answers ?? {}).length === 0 && (
                <p className="mt-1 text-xs text-ink-muted">
                  None yet. Remembered answers above are used first.
                </p>
              )}
              {Object.entries(draft.custom_answers ?? {}).map(([question, answer]) => (
                <label key={question} className="mt-2 block text-sm">
                  {question}
                  <textarea
                    className="field mt-1"
                    value={answer}
                    onChange={(e) =>
                      setDraft({
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
  );
}

/** What forms read from the resume's Education section (edited there, not here). */
function EducationSummary({ education }: { education: Education[] }) {
  return (
    <div className="mt-3 rounded-md border border-line px-3 py-2 text-xs">
      <p className="text-ink-muted">
        School, degree, major and dates come from the Education section of your resume.
      </p>
      {education.length > 0 ? (
        <ul className="mt-1 space-y-0.5">
          {education.map((entry, index) => (
            <li key={index}>
              <span className="font-medium">{entry.school || "School not set"}</span>
              {entry.degree && ` · ${entry.degree}`}
              {entry.major && ` · ${entry.major}`}
              {entry.dates && ` · ${entry.dates}`}
              {entry.end && ` · graduates ${entry.end}`}
              {entry.gpa && ` · GPA ${entry.gpa}`}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-warn">Your resume has no Education entry yet.</p>
      )}
      <Link className="mt-1 inline-block text-accent underline" to="/profile/resume">
        Edit on resume
      </Link>
    </div>
  );
}
