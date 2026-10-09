import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ApplicantProfile } from "../../api";
import { LanguagesEditor } from "../../components/LanguagesEditor";
import { ProfileGapBanner } from "../../components/ProfileGapBanner";
import { DataList, Tile, TileSection } from "../../components/ui";
import {
  PROFILE_GROUPS,
  REMEMBERED_ANSWERS_GROUP,
  classYearFor,
  sponsorshipFromVisa,
} from "../../lib/profileForm";
import type { Education } from "../../lib/resumeEdit";
import { useApplicantProfile } from "../../state/applicantProfileState";
import type { FieldContext } from "./fieldContext";
import { ProfileField } from "./ProfileField";
import { AIChoicesList } from "./AIChoicesList";
import { CustomAnswers } from "./CustomAnswers";
import { DocumentUpload } from "./DocumentUpload";
import { EeoFields } from "./EeoFields";
import { SavedAnswersList } from "./SavedAnswersList";

const yesNo = (value: boolean) => (value ? "Yes" : "No");

/**
 * What an empty select stands for, shown as its first option: "Auto from visa: Yes",
 * "Auto: Senior". Undefined when nothing answers a blank value.
 */
function blankLabelFor(key: keyof ApplicantProfile, draft: ApplicantProfile): string | undefined {
  const fromVisa = sponsorshipFromVisa(draft.visa_status);
  switch (key) {
    case "requires_sponsorship_now":
      return fromVisa ? `Auto from visa: ${yesNo(fromVisa[0])}` : undefined;
    case "requires_sponsorship_future":
      return fromVisa ? `Auto from visa: ${yesNo(fromVisa[1])}` : undefined;
    case "f1_opt_eligible":
      return draft.visa_status?.startsWith("f1") ? "Auto from visa: Yes" : undefined;
    case "class_year": {
      const auto = classYearFor(draft.graduation_date);
      return auto ? `Auto: ${auto}` : "Auto from expected graduation";
    }
    default:
      return undefined;
  }
}

/** Explanations that are not "what a blank value means" (those live inside the control). */
function hintFor(key: keyof ApplicantProfile): ReactNode {
  switch (key) {
    case "auto_accept_routine_acknowledgements":
      return "Accepts routine privacy and read-notice acknowledgements. Certifications and signatures stay for your review.";
    case "visa_status":
      return "Sets the sponsorship answers below unless you choose them yourself.";
    case "hours_per_week_available":
      return "For part-time and co-op forms.";
    case "location_preference":
      return "Cities you would work in (“New York; Remote”). Office checklists tick the ones named here, else the posting’s city.";
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
 * Application details: collapsible groups of the facts forms ask for. `open` holds the
 * expanded ones (all during first-run setup, none after it).
 */
export function ApplicationTab({
  ctx,
  open,
  onToggle,
  onOpenGroup,
  education,
  onEditResume,
}: {
  ctx: FieldContext;
  open: Set<string>;
  onToggle: (id: string, open: boolean) => void;
  onOpenGroup: (id: string) => void;
  education: Education[];
  /** Replaces the "Edit on resume" link (the setup wizard edits the resume in a step). */
  onEditResume?: () => void;
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
        <Tile key={group.id} id={`profile-group-${group.id}`}>
          <details
            open={open.has(group.id)}
            onToggle={(e) => onToggle(group.id, e.currentTarget.open)}
          >
            <summary className="rt-tile-title cursor-pointer">{group.title}</summary>
            {group.id === "Education" && (
              <EducationSummary education={education} onEditResume={onEditResume} />
            )}
            {group.id === "Salary" && (
              <p className="mt-3 text-xs text-ink-muted">
                Salary questions are answered from your maximum: the posting's top pay when it is
                below your maximum, otherwise your maximum, in the posting's unit (hourly ↔ yearly
                at 2,080 hours). With no posted pay, intern and co-op roles use your hourly maximum
                and other roles your yearly maximum. Leave the maximums empty to answer salary
                questions yourself.
              </p>
            )}
            {group.id === "Voluntary information" && (
              <p className="mt-3 text-xs text-ink-muted">
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
                    hint={hintFor(key)}
                    blankLabel={blankLabelFor(key, draft)}
                    auto={autoAnswered(key, draft)}
                  />
                ))}
                {group.id === "Education" && <DocumentUpload kind="transcript" />}
                {group.id === "Saved answers and other preferences" && (
                  <DocumentUpload kind="portfolio" />
                )}
              </div>
            )}
            {group.id === "Voluntary information" && (
              <EeoFields eeo={draft.eeo} onChange={(eeo) => setDraft({ eeo })} />
            )}
            {group.id === "Languages" && (
              <LanguagesEditor
                languages={draft.languages ?? []}
                onChange={(languages) => setDraft({ languages })}
              />
            )}
            {group.id === "Saved answers and other preferences" && <CustomAnswers />}
          </details>
        </Tile>
      ))}
      <Tile id="profile-group-remembered-answers">
        <details
          open={open.has(REMEMBERED_ANSWERS_GROUP)}
          onToggle={(e) => onToggle(REMEMBERED_ANSWERS_GROUP, e.currentTarget.open)}
        >
          <summary className="rt-tile-title cursor-pointer">Remembered answers</summary>
          <TileSection className="mt-4" title="Saved answers">
            <SavedAnswersList />
          </TileSection>
          <TileSection className="mt-4">
            <AIChoicesList />
          </TileSection>
        </details>
      </Tile>
    </div>
  );
}

/** What forms read from the resume's Education section (edited there, not here). */
function EducationSummary({
  education,
  onEditResume,
}: {
  education: Education[];
  onEditResume?: () => void;
}) {
  return (
    <div className="mt-3 space-y-3 text-xs">
      <p className="text-ink-muted">
        School, degree, major and dates come from the Education section of your resume.
      </p>
      {education.length > 0 ? (
        education.map((entry, index) => (
          <DataList
            key={index}
            items={[
              { label: "School", value: entry.school || "School not set" },
              {
                label: "Degree",
                value: [entry.degree, entry.major].filter(Boolean).join(" · ") || "—",
              },
              {
                label: "Dates",
                value:
                  [entry.dates, entry.end && `graduates ${entry.end}`]
                    .filter(Boolean)
                    .join(" · ") || "—",
              },
              ...(entry.gpa ? [{ label: "GPA", value: entry.gpa }] : []),
            ]}
          />
        ))
      ) : (
        <p className="mt-1 text-attn">Your resume has no Education entry yet.</p>
      )}
      {onEditResume ? (
        <button type="button" className="rt-link mt-1 inline-block" onClick={onEditResume}>
          Edit on resume
        </button>
      ) : (
        <Link className="rt-link mt-1 inline-block" to="/profile/resume">
          Edit on resume
        </Link>
      )}
    </div>
  );
}
