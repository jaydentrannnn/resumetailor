import type { SetupStatus } from "../api";

/** Pill text for the header: "Ready", or how many required steps are left. */
export function setupPillLabel(status: SetupStatus): string {
  if (status.ready) return "Ready";
  return `${status.remaining} setup step${status.remaining === 1 ? "" : "s"} left`;
}
