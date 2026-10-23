import {
  createBrowserRouter,
  Navigate,
  Route,
  RouterProvider,
  Routes,
  useBlocker,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { getOnboarding } from "./api";
import { needsWelcome, setupActive } from "./lib/onboarding";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { CommandPalette } from "./components/CommandPalette";
import { KeyboardShortcuts } from "./components/KeyboardShortcuts";
import { AppCommands } from "./components/shell/useAppCommands";
import { TextContextMenu } from "./components/TextContextMenu";
import { AppRail } from "./components/shell/AppRail";
import { StatusBar } from "./components/shell/StatusBar";
import { ToastProvider } from "./components/ui/Toast";
import { RunPage } from "./pages/run/RunPage";
import { ConfirmProvider } from "./state/confirmState";
import { EditorProvider } from "./state/editorState";
import { LibraryProvider } from "./state/libraryState";
import { RunProvider, useRunState } from "./state/runState";
import { TemplateProvider } from "./state/templateState";
import { ThemeProvider } from "./state/themeState";
import { WorkspaceProvider, useWorkspaceState } from "./state/workspaceState";
import { ApplicantProfileProvider } from "./state/applicantProfileState";
import { useApplicantProfile } from "./state/applicantProfileState";
import { useEditorState } from "./state/editorState";
import { useConfirm } from "./state/confirmState";
import { LogoMark } from "./components/LogoMark";
import { CommandProvider } from "./state/commandState";
import { ShellContext, type ShellSlots } from "./lib/shell";
import { useWindowTitle } from "./lib/useWindowTitle";
import { useStartPage } from "./lib/useStartPage";
import { EvidencePage } from "./pages/resume/EvidencePage";
import { ResumePage } from "./pages/resume/ResumePage";

/** Profile, Resume and its Evidence page share unsaved-edit protection: leaving them asks first. */
const guarded = (path: string) =>
  path.startsWith("/profile/") || path === "/resume" || path.startsWith("/resume/");

/**
 * Root: `ThemeProvider` owns light/dark/system preference (localStorage).
 * `WorkspaceProvider` sits above the router and never remounts — it owns the
 * profile registry itself, independent of which profile is active.
 * `ConfirmProvider` wraps `WorkspaceScope` (not the keyed Run/Editor providers) so a
 * profile switch cannot unmount a dialog the user is mid-decision on.
 */
export default function App() {
  return <RouterProvider router={router} />;
}

const router = createBrowserRouter([{ path: "/*", element: <AppFrame /> }]);

function AppFrame() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <ToastProvider>
          <WorkspaceProvider>
            <ConfirmProvider>
              <WorkspaceScope />
            </ConfirmProvider>
          </WorkspaceProvider>
        </ToastProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

/**
 * Keys Run/Editor/Template state on the active profile id.
 *
 * Changing `key` unmounts and remounts all three providers, which discards every
 * profile-scoped cache — config, the master-resume draft, the template library, the
 * last job's report — with no reset logic in any of them: each already refetches on
 * mount. This is deliberately simpler than threading a "generation" counter through
 * three providers' effects, which is more code with more ways to miss a field.
 */
function WorkspaceScope() {
  const { activeId, loading, error } = useWorkspaceState();

  if (loading) {
    return (
      <div
        className="flex min-h-screen items-center justify-center gap-3 bg-paper text-sm text-ink-muted"
        role="status"
      >
        <LogoMark />
        Loading…
      </div>
    );
  }

  if (!activeId) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6 text-center text-sm text-danger">
        {error ?? "No profile is active. Reload the page, or check the server log."}
      </div>
    );
  }

  return (
    <RunProvider key={activeId}>
      <EditorProvider key={activeId}>
        <TemplateProvider key={activeId}>
          <LibraryProvider key={activeId}>
            <ApplicantProfileProvider key={activeId}>
              <Shell />
            </ApplicantProfileProvider>
          </LibraryProvider>
        </TemplateProvider>
      </EditorProvider>
    </RunProvider>
  );
}

/**
 * The window: the rail on the left; the work area's command bar (filled by each page's
 * `CommandBar`), page and status bar on the right. Remounts on a profile switch along
 * with the providers above, so `ProfileMenu` can read the outgoing profile's editor
 * state directly. The document still scrolls (pages use `window.scrollTo`); the rail,
 * command bar and status bar are sticky.
 */
function Shell() {
  const settingUp = useOnboardingGate();
  useStartPage(settingUp);
  const [commandBar, setCommandBar] = useState<HTMLElement | null>(null);
  const [pageTitle, setPageTitle] = useState<string | null>(null);
  const slots = useMemo<ShellSlots>(() => ({ commandBar, setPageTitle }), [commandBar]);
  const { dirty: resumeDirty } = useEditorState();
  const applicant = useApplicantProfile();
  useWindowTitle(pageTitle, resumeDirty || applicant.dirty);
  return (
    <ShellContext.Provider value={slots}>
      <CommandProvider>
        <div className="flex min-h-screen">
          <NavigationGuard />
          {/* During first-run setup the wizard is the only page: no rail to wander off by. */}
          {!settingUp && <AppRail />}
          <div className="flex min-w-0 flex-1 flex-col">
            <div ref={setCommandBar} className="sticky top-0 z-30" />
            <KeyboardShortcuts />
            {/* Like the rail, Ctrl+K stays out of first-run setup. */}
            {!settingUp && (
              <>
                <AppCommands />
                <CommandPalette />
              </>
            )}
            <TextContextMenu />
            <main className="w-full flex-1 px-4 pb-12 pt-5 sm:px-6">
              <Suspense fallback={<PageLoading />}>
                <Routes>
                  <Route path="/" element={<RunPage />} />
                  <Route path="/applications" element={<ApplyPage />} />
                  <Route path="/applications/sources" element={<SourcesPage />} />
                  <Route path="/applications/:applicationId" element={<ApplicationDetailPage />} />
                  <Route path="/resume" element={<ResumePage />} />
                  <Route path="/resume/evidence" element={<EvidencePage />} />
                  <Route path="/profile" element={<Navigate to="/profile/personal" replace />} />
                  <Route path="/profile/personal" element={<ProfilePage />} />
                  <Route path="/profile/application" element={<ProfilePage />} />
                  <Route path="/profile/tailoring" element={<ProfilePage />} />
                  <Route path="/profile/resume" element={<Navigate to="/resume" replace />} />
                  <Route path="/editor" element={<Navigate to="/resume" replace />} />
                  <Route path="/template" element={<TemplatePage />} />
                  <Route path="/vocabulary" element={<VocabularyPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/welcome" element={<OnboardingPage />} />
                </Routes>
              </Suspense>
            </main>
            <StatusBar />
          </div>
        </div>
      </CommandProvider>
    </ShellContext.Provider>
  );
}

// The Tailor page loads with the app; every other page is fetched on first visit, so
// the first paint does not wait for the editor, Apply dashboard and template wizard.
const ApplyPage = lazy(() =>
  import("./pages/apply/ApplyPage").then((m) => ({ default: m.ApplyPage })),
);
const SourcesPage = lazy(() =>
  import("./pages/apply/SourcesPage").then((m) => ({ default: m.SourcesPage })),
);
const ApplicationDetailPage = lazy(() =>
  import("./pages/ApplicationDetailPage").then((m) => ({ default: m.ApplicationDetailPage })),
);
const ProfilePage = lazy(() =>
  import("./pages/profile/ProfilePage").then((m) => ({ default: m.ProfilePage })),
);
const TemplatePage = lazy(() =>
  import("./pages/TemplatePage").then((m) => ({ default: m.TemplatePage })),
);
const VocabularyPage = lazy(() =>
  import("./pages/VocabularyPage").then((m) => ({ default: m.VocabularyPage })),
);

const OnboardingPage = lazy(() =>
  import("./pages/onboarding/OnboardingPage").then((m) => ({ default: m.OnboardingPage })),
);
const SettingsPage = lazy(() =>
  import("./pages/settings/SettingsPage").then((m) => ({ default: m.SettingsPage })),
);

function PageLoading() {
  return (
    <p role="status" className="py-12 text-center text-sm text-ink-muted">
      Loading…
    </p>
  );
}

/**
 * Keeps a profile that has not finished (or skipped) first-run setup on `/welcome`: the
 * progress is re-read on every navigation, so no link, shortcut or typed URL leaves the
 * wizard. Returns whether setup is running (the shell hides its nav meanwhile).
 */
function useOnboardingGate(): boolean {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [active, setActive] = useState(false);
  useEffect(() => {
    let live = true;
    getOnboarding()
      .then((state) => {
        if (!live) return;
        setActive(setupActive(state));
        if (needsWelcome(state, pathname)) navigate("/welcome", { replace: true });
      })
      .catch(() => undefined); // setup progress is a convenience; never block the app
    return () => {
      live = false;
    };
  }, [navigate, pathname]);
  return active;
}

function NavigationGuard() {
  const { dirty: resumeDirty, discard: discardResume } = useEditorState();
  const applicant = useApplicantProfile();
  const { settingsSaveState } = useRunState();
  const { confirm } = useConfirm();
  const location = useLocation();
  const prompted = useRef(false);
  const blocker = useBlocker(
    ({ nextLocation }) =>
      guarded(location.pathname) &&
      !guarded(nextLocation.pathname) &&
      (resumeDirty || applicant.dirty),
  );
  useEffect(() => {
    if (!resumeDirty && !applicant.dirty && !applicant.saving && settingsSaveState === "saved")
      return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [resumeDirty, applicant.dirty, applicant.saving, settingsSaveState]);
  useEffect(() => {
    if (blocker.state !== "blocked") {
      prompted.current = false;
      return;
    }
    if (prompted.current) return;
    prompted.current = true;
    void confirm({
      title: "Unsaved edits",
      message: "Leaving will discard unsaved resume and application changes.",
      confirmLabel: "Discard changes",
      cancelLabel: "Stay",
      tone: "danger",
    }).then((discard) => {
      if (discard) {
        discardResume();
        applicant.discard();
        blocker.proceed();
      } else blocker.reset();
    });
  }, [blocker, confirm, discardResume, applicant]);
  return null;
}
