import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getApplicantProfile, putApplicantProfile, type ApplicantProfile } from "../api";

type State = { draft: ApplicantProfile | null; setDraft: (value: ApplicantProfile) => void; dirty: boolean; saving: boolean; error: string | null; passwordSet: boolean; save: () => Promise<void>; discard: () => void };
const Context = createContext<State | null>(null);
export function ApplicantProfileProvider({ children }: { children: ReactNode }) {
  const [saved, setSaved] = useState<ApplicantProfile | null>(null);
  const [draft, setDraft] = useState<ApplicantProfile | null>(null);
  const [passwordSet, setPasswordSet] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { let live = true; getApplicantProfile().then(result => { if (!live) return; setSaved(result.profile); setDraft(result.profile); setPasswordSet(result.workday_password_set); }).catch(reason => { if (live) setError(String(reason)); }); return () => { live = false; }; }, []);
  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);
  async function save() { if (!draft) return; setSaving(true); setError(null); try { const result = await putApplicantProfile(draft); setDraft(result.profile); setSaved(result.profile); setPasswordSet(result.workday_password_set); } catch (reason) { setError(String(reason)); } finally { setSaving(false); } }
  function discard() { setDraft(saved); setError(null); }
  useEffect(() => { if (!dirty) return; const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); }; window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, [dirty]);
  return <Context.Provider value={{ draft, setDraft, dirty, saving, error, passwordSet, save, discard }}>{children}</Context.Provider>;
}
export function useApplicantProfile() { const value = useContext(Context); if (!value) throw new Error("ApplicantProfileProvider missing"); return value; }
