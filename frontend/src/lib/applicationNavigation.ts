const scrollPositions = new Map<string, number>();
export function rememberApplicationListScroll(workspaceId: string) {
  scrollPositions.set(workspaceId, window.scrollY);
}
export function consumeApplicationListScroll(workspaceId: string) {
  const value = scrollPositions.get(workspaceId);
  scrollPositions.delete(workspaceId);
  return value;
}

const applyParams = new Map<string, string>();
const applyParamsKey = (workspaceId: string) => `rt.applyParams.${workspaceId}`;

/** Keep the Apply page's tab, sort, page and filters so the nav link can bring them back. */
export function rememberApplyParams(workspaceId: string, search: string) {
  const params = new URLSearchParams(search);
  params.delete("settings");
  const value = params.toString();
  applyParams.set(workspaceId, value);
  try {
    window.sessionStorage.setItem(applyParamsKey(workspaceId), value);
  } catch {
    // Storage can be blocked; the in-memory copy still covers this session.
  }
}

export function recallApplyParams(workspaceId: string): string {
  try {
    const stored = window.sessionStorage.getItem(applyParamsKey(workspaceId));
    if (stored != null) return stored;
  } catch {
    // Fall through to the in-memory copy.
  }
  return applyParams.get(workspaceId) ?? "";
}
