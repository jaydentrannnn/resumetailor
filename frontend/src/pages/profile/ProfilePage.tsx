import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { getOnboarding } from "../../api";
import { Button, CommandBar, Page, StatusMark } from "../../components/ui";
import {
  changedKeys,
  fieldLabel,
  ALL_PROFILE_GROUP_IDS,
  groupForField,
  inSetup,
  initialOpenGroups,
  tabForField,
  withGroupOpen,
} from "../../lib/profileForm";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import { useCommands } from "../../state/commandState";
import { useEditorState } from "../../state/editorState";
import { ApplicationTab } from "./ApplicationTab";
import { PersonalTab } from "./PersonalTab";
import { TailoringTab } from "./TailoringTab";
import { useProfileFields } from "./useProfileFields";

type Tab = "personal" | "application" | "tailoring";

/** Underline tabs below `lg`; from `lg` up, the Resume page's section list look. */
function sectionLinkClass(active: boolean): string {
  return `rt-control -mb-px block shrink-0 border-b px-3 py-2 text-sm lg:mb-0 lg:rounded-sm lg:border-b-0 lg:border-l-2 ${active ? "border-selected-line font-semibold text-ink lg:border-accent lg:bg-sunken lg:font-normal" : "border-transparent text-ink-muted hover:text-ink lg:hover:bg-sunken"}`;
}

const TABS: [Tab, string][] = [
  ["personal", "Personal information"],
  ["application", "Application details"],
  ["tailoring", "Tailoring"],
];

/**
 * Profile: three sections over two stores (the master resume and the applicant profile)
 * with one save bar. Save validates first and jumps to the first problem; otherwise it
 * saves whichever store changed and says which part failed, if one did. Laid out like the
 * Resume page: the sections in a list down the left (tabs across the top below `lg`),
 * the open section's tiles on the right.
 */
export function ProfilePage() {
  const { pathname: path, search } = useLocation();
  const navigate = useNavigate();
  const tab: Tab = path.endsWith("/application")
    ? "application"
    : path.endsWith("/tailoring")
      ? "tailoring"
      : "personal";
  const editor = useEditorState();
  const { applicant, draft, ctx, allErrors, attempted, setAttempted, reset } = useProfileFields();
  const toast = useToast();
  const { confirm } = useConfirm();

  const [open, setOpen] = useState<Set<string>>(() => initialOpenGroups(inSetup(null, search)));
  const [pendingFocus, setPendingFocus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<{ resume: boolean; profile: boolean }>({
    resume: false,
    profile: false,
  });

  const invalidCount = Object.keys(allErrors).length;
  const profileChanges = changedKeys(applicant.saved, draft).length;
  const changeCount = profileChanges + (editor.dirty ? 1 : 0);
  useCommands(() => [
    {
      id: "profile-save",
      title: "Save profile",
      group: "Profile",
      shortcut: ["Ctrl", "S"],
      disabled: changeCount === 0 || editor.busy || saving,
      run: () => void saveAll(),
    },
    {
      id: "profile-discard",
      title: "Discard profile changes",
      group: "Profile",
      disabled: changeCount === 0 || saving,
      run: () => void discardAll(),
    },
  ]);

  const setGroupOpen = useCallback((id: string, isOpen: boolean) => {
    setOpen((current) => withGroupOpen(current, id, isOpen));
  }, []);

  // Groups start collapsed; during first-run setup (or `?setup=1`) they all start open.
  useEffect(() => {
    if (inSetup(null, search)) {
      setOpen(new Set(ALL_PROFILE_GROUP_IDS));
      return;
    }
    let cancelled = false;
    getOnboarding()
      .then((state) => {
        if (!cancelled && inSetup(state)) setOpen(new Set(ALL_PROFILE_GROUP_IDS));
      })
      .catch(() => undefined); // setup progress is a convenience; collapsed is fine
    return () => {
      cancelled = true;
    };
  }, [search]);

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
  }, [pendingFocus, tab, open]);

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
      reset();
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
    reset();
    setFailed({ resume: false, profile: false });
  }

  const educationSection = editor.resume?.sections.find((section) => section.kind === "education");

  const problems = [
    attempted && invalidCount > 0 && (
      <button
        key="invalid"
        type="button"
        role="alert"
        className="text-sm text-danger underline"
        onClick={() => focusField(firstInvalid())}
      >
        {invalidCount} field{invalidCount === 1 ? " needs" : "s need"} attention:{" "}
        {Object.keys(allErrors).slice(0, 3).map(fieldLabel).join(", ")}
        {invalidCount > 3 ? "…" : ""}
      </button>
    ),
    failed.resume && editor.dirty && (
      <span key="resume" role="alert" className="text-sm text-danger">
        Resume not saved{editor.errors[0] ? `: ${editor.errors[0]}` : ""}{" "}
        <Link className="underline" to="/resume">
          Open resume
        </Link>
      </span>
    ),
    failed.profile && applicant.error && (
      <span key="profile" role="alert" className="text-sm text-danger">
        Application details not saved: {applicant.error}
      </span>
    ),
  ].filter(Boolean);

  return (
    <Page className="pb-4">
      <CommandBar
        title="Profile"
        state={
          <span className="flex items-center gap-1.5" aria-live="polite">
            <StatusMark tone={changeCount === 0 ? "done" : "attention"} />
            {changeCount === 0
              ? "All changes saved"
              : `${changeCount} unsaved change${changeCount === 1 ? "" : "s"}`}
          </span>
        }
        actions={
          <>
            {changeCount > 0 && (
              <Button variant="ghost" size="sm" disabled={saving} onClick={() => void discardAll()}>
                Discard
              </Button>
            )}
            <Button
              variant="primary"
              size="sm"
              data-shortcut="save"
              aria-label="Save profile"
              loading={saving || applicant.saving}
              disabled={changeCount === 0 || editor.busy}
              onClick={() => void saveAll()}
            >
              Save
            </Button>
          </>
        }
      />
      <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:items-start lg:gap-5">
        <nav
          aria-label="Profile sections"
          className="mb-5 flex gap-1 overflow-x-auto border-b border-line lg:sticky lg:top-[calc(var(--rt-bar-top)+1rem)] lg:mb-0 lg:block lg:space-y-1 lg:overflow-visible lg:border-b-0"
        >
          <p className="rt-eyebrow mb-3 hidden px-3 lg:block">Sections</p>
          {TABS.map(([id, label]) => (
            <Link
              key={id}
              to={`/profile/${id}`}
              aria-current={tab === id ? "page" : undefined}
              className={sectionLinkClass(tab === id)}
            >
              {label}
            </Link>
          ))}
        </nav>
        <div className="min-w-0 space-y-5">
          {problems.length > 0 && (
            <div role="region" aria-label="Save problems" className="flex flex-wrap gap-3">
              {problems}
            </div>
          )}
          {tab === "tailoring" && <TailoringTab />}
          {!ctx && (tab === "personal" || tab === "application") && (
            <p className="text-sm text-ink-muted">{applicant.error ?? "Loading your profile…"}</p>
          )}
          {ctx && tab === "personal" && (
            <PersonalTab ctx={ctx} resume={editor.resume} setResume={editor.setResume} />
          )}
          {ctx && tab === "application" && (
            <ApplicationTab
              ctx={ctx}
              open={open}
              onToggle={setGroupOpen}
              onOpenGroup={openGroup}
              education={educationSection?.kind === "education" ? educationSection.entries : []}
            />
          )}
        </div>
      </div>
    </Page>
  );
}
