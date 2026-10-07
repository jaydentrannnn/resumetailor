import { ProfileGapBanner } from "../../components/ProfileGapBanner";
import { fieldLabel } from "../../lib/profileForm";
import type { MasterResume } from "../../lib/resumeEdit";
import { useApplicantProfile } from "../../state/applicantProfileState";
import type { FieldContext } from "./fieldContext";
import { ProfileField } from "./ProfileField";

const RESUME_CONTACT = ["name", "email", "phone", "location", "linkedin", "github"] as const;

const CONTACT_PAIRS = [
  { resume: "email", applicant: "email" },
  { resume: "phone", applicant: "phone" },
  { resume: "linkedin", applicant: "linkedin_url" },
  { resume: "github", applicant: "github_url" },
] as const;

/** Resume contact (printed on the resume) and the names and overrides forms use. */
export function PersonalTab({
  ctx,
  resume,
  setResume,
}: {
  ctx: FieldContext;
  resume: MasterResume | null;
  setResume: (resume: MasterResume) => void;
}) {
  const applicant = useApplicantProfile();
  const { draft } = ctx;
  const gaps = applicant.gaps.filter((gap) => gap.path === "/profile/personal");
  /** Scroll to the first blank field the banner lists (the Basics card if none renders). */
  function openFirstGap() {
    const target =
      gaps
        .map((gap) => document.getElementById(`profile-field-${gap.key}`))
        .find((el) => el !== null) ?? document.getElementById("profile-basics");
    target?.scrollIntoView({ block: "center" });
  }
  return (
    <div className="space-y-4">
      <ProfileGapBanner gaps={gaps} onOpen={openFirstGap} />
      <section id="profile-basics" className="rounded-lg border border-line bg-panel p-5">
        <h2 className="text-lg font-semibold">Basics</h2>
        <p className="text-xs text-ink-muted">The names forms ask for.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {(["first_name", "middle_name", "last_name", "preferred_name"] as const).map((key) => (
            <ProfileField key={key} name={key} ctx={ctx} />
          ))}
        </div>
      </section>
      <section className="rounded-lg border border-line bg-panel p-5">
        <h2 className="text-lg font-semibold">Resume contact</h2>
        <p className="text-xs text-ink-muted">Printed at the top of every tailored resume.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {RESUME_CONTACT.map((key) => (
            <label key={key} className="text-sm">
              {key === "name"
                ? "Name on resume"
                : key === "location"
                  ? "Location"
                  : fieldLabel(key)}
              <input
                className="field mt-1"
                value={resume?.contact[key] ?? ""}
                onChange={(e) =>
                  resume &&
                  setResume({ ...resume, contact: { ...resume.contact, [key]: e.target.value } })
                }
              />
            </label>
          ))}
        </div>
      </section>
      <section id="application-contact" className="rounded-lg border border-line bg-panel p-5">
        <h2 className="text-lg font-semibold">Application contact</h2>
        <p className="text-xs text-ink-muted">
          Leave a field blank to use your resume contact. Fill it in to give forms something
          different (say, a personal email instead of a school one).
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {CONTACT_PAIRS.map((pair) => {
            const fallback = resume?.contact[pair.resume] ?? "";
            const overridden = !!draft[pair.applicant];
            return (
              <div key={pair.applicant}>
                <ProfileField
                  name={pair.applicant}
                  ctx={{
                    ...ctx,
                    fallbacks: { ...ctx.fallbacks, [pair.applicant]: fallback },
                  }}
                  label={`${fieldLabel(pair.applicant)} · ${overridden ? "different from resume" : "from resume"}`}
                />
                {overridden && (
                  <button
                    type="button"
                    className="mt-1 text-xs text-accent underline"
                    onClick={() => ctx.set(pair.applicant, "")}
                  >
                    Use resume value
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
