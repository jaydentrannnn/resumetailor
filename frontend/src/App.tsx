import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { ProfileSwitcher } from "./components/workspace/ProfileSwitcher";
import { EditorPage } from "./pages/EditorPage";
import { RunPage } from "./pages/RunPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TemplatePage } from "./pages/TemplatePage";
import { EditorProvider } from "./state/editorState";
import { LibraryProvider } from "./state/libraryState";
import { RunProvider } from "./state/runState";
import { TemplateProvider } from "./state/templateState";
import { WorkspaceProvider, useWorkspaceState } from "./state/workspaceState";

const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition ${
    isActive ? "bg-accent text-white" : "text-ink-muted hover:bg-accent-soft hover:text-ink"
  }`;

/**
 * Root: `WorkspaceProvider` sits above the router and never remounts — it owns the
 * profile registry itself, independent of which profile is active.
 */
export default function App() {
  return (
    <BrowserRouter>
      <WorkspaceProvider>
        <WorkspaceScope />
      </WorkspaceProvider>
    </BrowserRouter>
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
            <Shell />
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
      <header className="border-b border-line/80 bg-panel/80 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-4 px-6 py-5">
          <div>
            <p className="font-display text-3xl font-bold tracking-tight text-ink">
              ResumeTailor
            </p>
            <p className="mt-1 text-sm text-ink-muted">
              Tailor your resume to a posting without changing its look.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <ProfileSwitcher />
            <nav className="flex gap-1 pb-1">
              <NavLink to="/" end className={navLinkClassName}>
                Tailor
              </NavLink>
              <NavLink to="/editor" className={navLinkClassName}>
                Master resume
              </NavLink>
              <NavLink to="/template" className={navLinkClassName}>
                Template
              </NavLink>
              <NavLink to="/settings" className={navLinkClassName}>
                Settings
              </NavLink>
            </nav>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<RunPage />} />
          <Route path="/editor" element={<EditorPage />} />
          <Route path="/template" element={<TemplatePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
