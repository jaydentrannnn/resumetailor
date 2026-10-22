import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useRunState } from "../state/runState";
import { visibleRailItems } from "../components/shell/railItems";

const SESSION_KEY = "rt-start-page-done";

/**
 * Once per window session, if the URL is Tailor (`/`) and a different opening page
 * is saved, navigate there. Skips when the setup wizard is about to redirect.
 */
export function useStartPage(welcomePending: boolean): void {
  const { settings } = useRunState();
  const navigate = useNavigate();
  const location = useLocation();
  const done = useRef(false);

  useEffect(() => {
    if (done.current || welcomePending) return;
    try {
      if (sessionStorage.getItem(SESSION_KEY)) {
        done.current = true;
        return;
      }
    } catch {
      /* private mode */
    }
    if (location.pathname !== "/") return;
    const start = settings.start_page || "/";
    const allowed = new Set(visibleRailItems(settings.rail_layout).map((i) => i.to));
    done.current = true;
    try {
      sessionStorage.setItem(SESSION_KEY, "1");
    } catch {
      /* ignore */
    }
    if (start !== "/" && allowed.has(start)) {
      navigate(start, { replace: true });
    }
  }, [settings.start_page, settings.rail_layout, welcomePending, location.pathname, navigate]);
}
