import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { ApplicantProfile } from "../../api";
import { ProfileGapBanner } from "../../components/ProfileGapBanner";
import { Button, Page, PageHeader, StatusMark } from "../../components/ui";
import {
  GAP_FIELD_ALIASES,
  changedKeys,
  fieldLabel,
  groupForField,
  loadClosedGroups,
  saveClosedGroups,
  tabForField,
  validateProfile,
} from "../../lib/profileForm";
import { useToast } from "../../lib/toast";
import { useApplicantProfile } from "../../state/applicantProfileState";
import { useConfirm } from "../../state/confirmState";
import { useEditorState } from "../../state/editorState";
import { useWorkspaceState } from "../../state/workspaceState";
import { EditorPage } from "../editor/EditorPage";
import { ApplicationTab } from "./ApplicationTab";
import type { FieldContext, FieldValue } from "./fieldContext";
import { PersonalTab } from "./PersonalTab";

type Tab = "personal" | "resume" | "application";

const TABS: [Tab, string][] = [
  ["personal", "Personal information"],
  ["resume", "Resume content"],
  ["application", "Application details"],
];

/**
 * Profile: three sub-tabs over two stores (the master resume and the applicant profile)
 * with one save bar. Save validates first and jumps to the first problem; otherwise it
 * saves whichever store changed and says which part failed, if one did.
 */
export function ProfilePage() {
  const path = useLocation().pathname;
  const navigate = useNavigate();
  const tab: Tab = path.endsWith("/resume")
    ? "resume"
    : path.endsWith("/application")
      ? "application"
      : "personal";
  const editor = useEditorState();
  const { activeLabel } = useWorkspaceState();
  const applicant = useApplicantProfile();
  const toast = useToast();
  const { confirm } = useConfirm();
  const draft = applicant.draft;

  const [closed, setClosed] = useState<Set<string>>(loadClosedGroups);
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [attempted, setAttempted] = useState(false);
  const [pendingFocus, setPendingFocus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<{ resume: boolean; profile: boolean }>({
    resume: false,
    profile: false,
  });

  const allErrors = useMemo(() => (draft ? validateProfile(draft) : {}), [draft]);
  const shownErrors = useMemo(
    () =>
      attempted
        ? allErrors
        : Object.fromEntries(Object.entries(allErrors).filter(([key]) => touched.has(key))),
    [allErrors, attempted, touched],
  );
  const invalidCount = Object.keys(allErrors).length;
  const profileChanges = changedKeys(applicant.saved, draft).length;
  const changeCount = profileChanges + (editor.dirty ? 1 : 0);

  const setGroupOpen = useCallback((id: string, open: boolean) => {
    setClosed((current) => {
      if (open === !current.has(id)) return current;
      const next = new Set(current);
      if (open) next.delete(id);
      else next.add(id);
      saveClosedGroups(next);
      return next;
    });
  }, []);

  function openGroup(id: string) {
    setGroupOpen(id, true);
    requestAnimationFrame(() =>
      document.getElementById(`profile-group-${id}`)?.scrollIntoView({ block: "start" }),
    );
  }

  /** Show the tab and group that hold `key`, then scroll to and focus it. */
  function focusField(key: string) {
    const target = tabForField(key);
    const group = groupForField(key);
    if (group) setGroupOpen(group, true);
    if (target !== tab) navigate(`/profile/${target}`);
    setPendingFocus(key);
  }

  useEffect(() => {
    if (!pendingFocus) return;
    const el = document.getElementById(`profile-field-${pendingFocus}`);
    if (!el) return;
    el.scrollIntoView({ block: "center" });
    el.querySelector<HTMLElement>("input, select, textarea")?.focus({ preventScroll: true });
    setPendingFocus(null);
  }, [pendingFocus, tab, closed]);

  /** The first problem on the tab being viewed, else the first anywhere. */
  function firstInvalid(): string {
    const keys = Object.keys(allErrors);
    return keys.find((key) => tabForField(key) === tab) ?? keys[0];
  }

  async function saveAll() {
    if (!draft) return;
    const invalid = Object.keys(allErrors);
    if (invalid.length) {
      setAttempted(true);
      focusField(firstInvalid());
      return;
    }
    setSaving(true);
    const result = { resume: false, profile: false };
    try {
      if (editor.dirty) result.resume = !(await editor.save());
      if (applicant.dirty) result.profile = !(await applicant.save());
    } finally {
      setSaving(false);
    }
    setFailed(result);
    if (!result.resume && !result.profile) {
      setAttempted(false);
      setTouched(new Set());
      toast.success("Profile saved");
    }
  }

  async function discardAll() {
    const ok = await confirm({
      title: "Discard unsaved changes?",
      message: "Your resume contact and application details go back to what was last saved.",
      confirmLabel: "Discard",
      tone: "danger",
    });
    if (!ok) return;
    editor.discard();
    applicant.discard();
    setAttempted(false);
    setTouched(new Set());
    setFailed({ resume: false, profile: false });
  }

  const ctx: FieldContext | null = draft
    ? {
        draft,
        set: (key: keyof ApplicantProfile, value: FieldValue) =>
          applicant.setDraft({ ...draft, [key]: value }),
        setMany: (patch) => applicant.setDraft({ ...draft, ...patch }),
        errors: shownErrors,
        gapFields: new Set(applicant.gaps.map((gap) => GAP_FIELD_ALIASES[gap.key] ?? gap.key)),
        defaults: applicant.defaults,
        fallbacks: applicant.fallbacks,
        passwordSet: applicant.passwordSet,
        touch: (key) =>
          setTouched((current) => (current.has(key) ? current : new Set(current).add(key))),
      }
    : null;
  const educationSection = editor.resume?.sections.find((section) => section.kind === "education");

  return (
    <Page className="pb-4">
      <PageHeader
        title="Profile"
        eyebrow={`PROFILE · ${activeLabel ?? "Default"}`}
        description="Your resume content and the details application forms ask for, saved together."
      />
      <nav aria-label="Profile sections" className="flex flex-wrap gap-4 border-b border-line">
        {TABS.map(([id, label]) => (
          <Link
            key={id}
            to={`/profile/${id}`}
            aria-current={tab === id ? "page" : undefined}
            className={`rt-control -mb-px border-b px-3 py-2 text-sm ${tab === id ? "border-selected-line font-semibold text-ink" : "border-transparent text-ink-muted hover:text-ink"}`}
          >
            {label}
          </Link>
        ))}
      </nav>
      {tab === "resume" && (
        <div className="space-y-4">
          <ProfileGapBanner
            gaps={applicant.gaps.filter((gap) => gap.path === "/profile/resume")}
            onOpen={() =>
              educationSection &&
              document
                .getElementById(`resume-section-${educationSection.id}`)
                ?.scrollIntoView({ block: "start" })
            }
          />
          <EditorPage showContact={false} embedded />
        </div>
      )}
      {!ctx && tab !== "resume" && (
        <p className="text-sm text-ink-muted">{applicant.error ?? "Loading your profile…"}</p>
      )}
      {ctx && tab === "personal" && (
        <PersonalTab ctx={ctx} resume={editor.resume} setResume={editor.setResume} />
      )}
      {ctx && tab === "application" && (
        <ApplicationTab
          ctx={ctx}
          closed={closed}
          onToggle={setGroupOpen}
          onOpenGroup={openGroup}
          education={educationSection?.kind === "education" ? educationSection.entries : []}
        />
      )}

      <div
        role="region"
        aria-label="Save profile"
        className="sticky bottom-0 z-10 flex flex-wrap items-center gap-3 border-t border-line bg-chrome py-3"
      >
        <Button
          variant="primary"
          className="order-3"
          loading={saving || applicant.saving}
          disabled={changeCount === 0 || editor.busy}
          onClick={() => void saveAll()}
        >
          Save changes
        </Button>
        <span className="mr-auto flex items-center gap-2 text-sm text-ink-muted" aria-live="polite">
          <StatusMark tone={changeCount === 0 ? "done" : "attention"} />
          {changeCount === 0
            ? "All changes saved"
            : `${changeCount} unsaved change${changeCount === 1 ? "" : "s"}`}
        </span>
        {changeCount > 0 && (
          <Button variant="ghost" size="sm" disabled={saving} onClick={() => void discardAll()}>
            Discard
          </Button>
        )}
        {attempted && invalidCount > 0 && (
          <button
            type="button"
            role="alert"
            className="text-sm text-danger underline"
            onClick={() => focusField(firstInvalid())}
          >
            {invalidCount} field{invalidCount === 1 ? " needs" : "s need"} attention:{" "}
            {Object.keys(allErrors).slice(0, 3).map(fieldLabel).join(", ")}
            {invalidCount > 3 ? "…" : ""}
          </button>
        )}
        {failed.resume && editor.dirty && (
          <span role="alert" className="text-sm text-danger">
            Resume not saved{editor.errors[0] ? `: ${editor.errors[0]}` : ""}
            {tab !== "resume" && (
              <>
                {" "}
                <Link className="underline" to="/profile/resume">
                  Open resume
                </Link>
              </>
            )}
          </span>
        )}
        {failed.profile && applicant.error && (
          <span role="alert" className="text-sm text-danger">
            Application details not saved: {applicant.error}
          </span>
        )}
      </div>
    </Page>
  );
}
