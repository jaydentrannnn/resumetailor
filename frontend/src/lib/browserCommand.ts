// Edge, not Chrome: Chrome refuses to open its remote-debugging port whenever any
// other Chrome window (any profile) is already running under this account, which
// would mean closing the user's normal browsing session every time. Edge is a
// separate binary/process, so it can run this debug profile in the background
// without touching Chrome at all.
export const EDGE_DEBUG_COMMAND =
  String.raw`& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="$env:LOCALAPPDATA\ResumeTailorEdge"`;
