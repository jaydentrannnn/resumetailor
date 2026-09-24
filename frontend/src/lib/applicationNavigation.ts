const scrollPositions = new Map<string, number>();
export function rememberApplicationListScroll(workspaceId: string) {
  scrollPositions.set(workspaceId, window.scrollY);
}
export function consumeApplicationListScroll(workspaceId: string) {
  const value = scrollPositions.get(workspaceId);
  scrollPositions.delete(workspaceId);
  return value;
}
