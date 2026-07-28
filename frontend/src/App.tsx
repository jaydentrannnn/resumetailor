import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { EditorPage } from "./pages/EditorPage";
import { RunPage } from "./pages/RunPage";
import { EditorProvider } from "./state/editorState";
import { RunProvider } from "./state/runState";

/**
 * Shell: brand + nav, then the two pages (run and master-resume editor).
 *
 * Providers sit above Routes so Tailor / Master-resume state survives tab switches.
 */
export default function App() {
  return (
    <BrowserRouter>
      <RunProvider>
        <EditorProvider>
          <div className="min-h-screen">
            <header className="border-b border-line/80 bg-panel/80 backdrop-blur-sm">
              <div className="mx-auto flex max-w-6xl items-end justify-between gap-6 px-6 py-5">
                <div>
                  <p className="font-display text-3xl font-bold tracking-tight text-ink">
                    ResumeTailor
                  </p>
                  <p className="mt-1 text-sm text-ink-muted">
                    Tailor your resume to a posting without changing its look.
                  </p>
                </div>
                <nav className="flex gap-1 pb-1">
                  <NavLink
                    to="/"
                    end
                    className={({ isActive }) =>
                      `rounded-md px-3 py-1.5 text-sm font-medium transition ${
                        isActive
                          ? "bg-accent text-white"
                          : "text-ink-muted hover:bg-accent-soft hover:text-ink"
                      }`
                    }
                  >
                    Tailor
                  </NavLink>
                  <NavLink
                    to="/editor"
                    className={({ isActive }) =>
                      `rounded-md px-3 py-1.5 text-sm font-medium transition ${
                        isActive
                          ? "bg-accent text-white"
                          : "text-ink-muted hover:bg-accent-soft hover:text-ink"
                      }`
                    }
                  >
                    Master resume
                  </NavLink>
                </nav>
              </div>
            </header>
            <main className="mx-auto max-w-6xl px-6 py-8">
              <Routes>
                <Route path="/" element={<RunPage />} />
                <Route path="/editor" element={<EditorPage />} />
              </Routes>
            </main>
          </div>
        </EditorProvider>
      </RunProvider>
    </BrowserRouter>
  );
}
