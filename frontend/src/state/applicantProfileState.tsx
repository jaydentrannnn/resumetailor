import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import {
  getApplicantProfile,
  putApplicantProfile,
  type ApplicantProfile,
  type ApplicantProfileResponse,
  type ProfileGap,
} from "../api";

type State = {
  draft: ApplicantProfile | null;
  setDraft: (value: ApplicantProfile) => void;
  dirty: boolean;
  saving: boolean;
  error: string | null;
  passwordSet: boolean;
  gaps: ProfileGap[];
  defaults: Record<string, string>;
  /** Resolves true when the profile was saved; a failure is reported in `error`. */
  save: () => Promise<boolean>;
  discard: () => void;
};
const Context = createContext<State | null>(null);
export function ApplicantProfileProvider({ children }: { children: ReactNode }) {
  const [saved, setSaved] = useState<ApplicantProfile | null>(null);
  const [draft, setDraft] = useState<ApplicantProfile | null>(null);
  const [passwordSet, setPasswordSet] = useState(false);
  // Gaps and defaults reflect the saved profile; they refresh on load and after Save.
  const [gaps, setGaps] = useState<ProfileGap[]>([]);
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  function accept(result: ApplicantProfileResponse) {
    setSaved(result.profile);
    setDraft(result.profile);
    setPasswordSet(result.workday_password_set);
    setGaps(result.gaps ?? []);
    setDefaults(result.defaults ?? {});
  }
  useEffect(() => {
    let live = true;
    getApplicantProfile()
      .then((result) => {
        if (live) accept(result);
      })
      .catch((reason) => {
        if (live) setError(String(reason));
      });
    return () => {
      live = false;
    };
  }, []);
  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);
  async function save(): Promise<boolean> {
    if (!draft) return false;
    setSaving(true);
    setError(null);
    try {
      accept(await putApplicantProfile(draft));
      return true;
    } catch (reason) {
      setError(String(reason));
      return false;
    } finally {
      setSaving(false);
    }
  }
  function discard() {
    setDraft(saved);
    setError(null);
  }
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  return (
    <Context.Provider
      value={{ draft, setDraft, dirty, saving, error, passwordSet, gaps, defaults, save, discard }}
    >
      {children}
    </Context.Provider>
  );
}
/** Blank profile fields forms ask for; empty outside the provider. */
export function useProfileGaps(): ProfileGap[] {
  return useContext(Context)?.gaps ?? [];
}
export function useApplicantProfile() {
  const value = useContext(Context);
  if (!value) throw new Error("ApplicantProfileProvider missing");
  return value;
}
