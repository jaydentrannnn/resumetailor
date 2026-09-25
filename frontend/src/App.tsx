import {
  createBrowserRouter,
  Navigate,
  NavLink,
  Route,
  RouterProvider,
  Routes,
  useBlocker,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { lazy, Suspense, useEffect, useRef } from "react";
import { getOnboarding } from "./api";
import { needsWelcome } from "./lib/onboarding";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { SettingsMenu } from "./components/SettingsMenu";
import { KeyboardShortcuts } from "./components/KeyboardShortcuts";
import { AutomationSwitch } from "./components/AutomationSwitch";
import { SetupHealth } from "./components/SetupHealth";
import { ToastProvider } from "./components/ui/Toast";
import { RunPage } from "./pages/run/RunPage";
import { ConfirmProvider } from "./state/confirmState";
import { EditorProvider } from "./state/editorState";
import { LibraryProvider, useLibraryState } from "./state/libraryState";
import { RunProvider, useRunState } from "./state/runState";
import { TemplateProvider } from "./state/templateState";
import { ThemeProvider } from "./state/themeState";
import { WorkspaceProvider, useWorkspaceState } from "./state/workspaceState";
import { ApplicantProfileProvider } from "./state/applicantProfileState";
import { useApplicantProfile } from "./state/applicantProfileState";
import { useEditorState } from "./state/editorState";
import { useConfirm } from "./state/confirmState";

const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-[var(--dur-short)] ease-out ${
    isActive ? "bg-accent text-on-accent" : "text-ink-muted hover:bg-accent-soft hover:text-ink"
  }`;

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
      <div className="flex min-h-screen items-center justify-center text-sm text-ink-muted">
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
 * Brand + profile switcher + nav, then the three pages. Remounts on a profile
 * switch along with the providers above — a brief nav flicker is an acceptable
 * trade for `ProfileSwitcher` being able to read the *outgoing* profile's editor
 * state directly (see its docstring) instead of needing a separate cross-boundary
 * store just to check for unsaved edits.
 */
function Shell() {
  return (
    <div className="min-h-screen">
      <NavigationGuard />
      <OnboardingGate />
      <header className="relative z-30 border-b border-line/80 bg-panel/80 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-6 py-4">
          {/* Brand and nav read left-to-right as one group; profile and theme
              utilities sit on the right. min-w-0 lets each group shrink below its
              max-content width, and flex-wrap keeps a 320px viewport from scrolling
              sideways — the old unwrapped row was the app's one real horizontal-scroll bug. */}
          <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
            <p className="font-display text-2xl font-bold tracking-tight text-ink [overflow-wrap:anywhere]">
              ResumeTailor
            </p>
            <nav className="flex flex-wrap gap-1">
              <NavLink to="/" end className={navLinkClassName}>
                Tailor
              </NavLink>
              <NavLink to="/applications" className={navLinkClassName}>
                Apply
              </NavLink>
              {/* "/profile", not "/profile/personal": a non-`end` NavLink matches every
                  /profile/* sub-tab, so Profile stays highlighted on Resume content and
                  Application details. The route redirects to the personal tab. */}
              <NavLink to="/profile" className={navLinkClassName}>
                Profile
              </NavLink>
              <NavLink to="/template" className={navLinkClassName}>
                Template
              </NavLink>
              <NavLink to="/settings" className={navLinkClassName}>
                Settings
              </NavLink>
            </nav>
          </div>
          <div className="flex min-w-0 flex-wrap items-end gap-4">
            <SetupHealth />
            <AutomationSwitch />
            <SettingsMenu />
          </div>
        </div>
      </header>
      <KeyboardShortcuts />
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Suspense fallback={<PageLoading />}>
          <Routes>
            <Route path="/" element={<RunPage />} />
            <Route path="/applications" element={<ApplyPage />} />
            <Route path="/applications/:applicationId" element={<ApplicationDetailPage />} />
            <Route path="/profile" element={<Navigate to="/profile/personal" replace />} />
            <Route path="/profile/personal" element={<ProfilePage />} />
            <Route path="/profile/resume" element={<ProfilePage />} />
            <Route path="/profile/application" element={<ProfilePage />} />
            <Route path="/editor" element={<Navigate to="/profile/resume" replace />} />
            <Route path="/template" element={<TemplatePage />} />
            <Route path="/vocabulary" element={<VocabularyPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/welcome" element={<OnboardingPage />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}

// The Tailor page loads with the app; every other page is fetched on first visit, so
// the first paint does not wait for the editor, Apply dashboard and template wizard.
const ApplyPage = lazy(() =>
  import("./pages/apply/ApplyPage").then((m) => ({ default: m.ApplyPage })),
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
 * Sends a profile that has not finished (or skipped) first-run setup to `/welcome`,
 * once per load: after that the student may leave the wizard (to the editor, say)
 * and come back through the header's setup checklist.
 */
function OnboardingGate() {
  const navigate = useNavigate();
  const location = useLocation();
  const checked = useRef(false);
  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    getOnboarding()
      .then((state) => {
        if (needsWelcome(state, location.pathname)) navigate("/welcome", { replace: true });
      })
      .catch(() => undefined); // setup progress is a convenience; never block the app
  }, [navigate, location.pathname]);
  return null;
}

function NavigationGuard() {
  const { dirty: resumeDirty, discard: discardResume } = useEditorState();
  const applicant = useApplicantProfile();
  const { settingsSaveState } = useRunState();
  const { overridesSaveState } = useLibraryState();
  const { confirm } = useConfirm();
  const location = useLocation();
  const prompted = useRef(false);
  const blocker = useBlocker(
    ({ nextLocation }) =>
      location.pathname.startsWith("/profile/") &&
      !nextLocation.pathname.startsWith("/profile/") &&
      (resumeDirty || applicant.dirty),
  );
  useEffect(() => {
    if (
      !resumeDirty &&
      !applicant.dirty &&
      !applicant.saving &&
      settingsSaveState === "saved" &&
      overridesSaveState === "saved"
    )
      return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [resumeDirty, applicant.dirty, applicant.saving, settingsSaveState, overridesSaveState]);
  useEffect(() => {
    if (blocker.state !== "blocked") {
      prompted.current = false;
      return;
    }
    if (prompted.current) return;
    prompted.current = true;
    void confirm({
      title: "Unsaved profile edits",
      message: "Leaving Profile will discard unsaved resume and application changes.",
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
