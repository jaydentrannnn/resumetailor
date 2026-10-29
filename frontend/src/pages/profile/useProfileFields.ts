import { useMemo, useState } from "react";
import type { ApplicantProfile } from "../../api";
import { GAP_FIELD_ALIASES, validateProfile, sponsorshipFromVisa } from "../../lib/profileForm";
import { realContact } from "../../lib/onboardingContact";
import { useApplicantProfile } from "../../state/applicantProfileState";
import { openGaps } from "../../lib/onboarding";
import { useEditorState } from "../../state/editorState";
import type { FieldContext, FieldValue } from "./fieldContext";

/**
 * The applicant-profile draft as the profile fields consume it: validation (shown per
 * touched field, or everywhere after a save attempt) and the `FieldContext` every field
 * takes. Shared by the Profile page and the setup wizard's profile steps.
 */
export function useProfileFields() {
  const applicant = useApplicantProfile();
  const draft = applicant.draft;
  const { resume } = useEditorState();
  const fromVisa = sponsorshipFromVisa(draft?.visa_status);
  const live = draft
    ? {
        ...applicant.fallbacks,
        ...Object.fromEntries(
          Object.entries(draft).filter(([, value]) => value !== "" && value != null),
        ),
        email: draft.email || resume?.contact.email,
        phone: draft.phone || resume?.contact.phone,
        requires_sponsorship_now: draft.requires_sponsorship_now ?? fromVisa?.[0],
        requires_sponsorship_future: draft.requires_sponsorship_future ?? fromVisa?.[1],
      }
    : null;
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [attempted, setAttempted] = useState(false);

  const allErrors = useMemo(() => (draft ? validateProfile(draft) : {}), [draft]);
  const shownErrors = useMemo(
    () =>
      attempted
        ? allErrors
        : Object.fromEntries(Object.entries(allErrors).filter(([key]) => touched.has(key))),
    [allErrors, attempted, touched],
  );

  const ctx: FieldContext | null = draft
    ? {
        draft,
        set: (key: keyof ApplicantProfile, value: FieldValue) =>
          applicant.setDraft({ ...draft, [key]: value }),
        setMany: (patch) => applicant.setDraft({ ...draft, ...patch }),
        errors: shownErrors,
        gapFields: new Set(
          openGaps(
            applicant.gaps.map((gap) => GAP_FIELD_ALIASES[gap.key] ?? gap.key),
            live,
          ),
        ),
        defaults: applicant.defaults,
        fallbacks: Object.fromEntries(
          Object.entries(applicant.fallbacks).map(([key, value]) => [key, realContact(value)]),
        ),
        passwordSet: applicant.passwordSet,
        touch: (key) =>
          setTouched((current) => (current.has(key) ? current : new Set(current).add(key))),
      }
    : null;

  /** Forget touched fields and a failed save attempt (after a successful save). */
  function reset() {
    setAttempted(false);
    setTouched(new Set());
  }

  return { applicant, draft, ctx, allErrors, shownErrors, attempted, setAttempted, reset };
}
