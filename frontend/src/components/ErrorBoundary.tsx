import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/**
 * Last-resort catch for a render throw — without this, an uncaught error anywhere in
 * the tree white-screens the whole app with nothing but a blank page and a console
 * trace the user cannot see. React error boundaries must be class components; there
 * is no hook equivalent.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled error in ResumeTailor UI:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center px-6">
          <div className="max-w-md rounded-xl border border-line bg-panel p-6 text-center shadow-sm">
            <h1 className="font-display text-xl font-semibold text-ink">Something went wrong</h1>
            <p className="mt-2 text-sm text-ink-muted">
              {this.state.error.message || "The page hit an unexpected error."}
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:brightness-110"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
