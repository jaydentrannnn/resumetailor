/** "20260925T120000Z" (from `submit-<stamp>`) → a local date and time. */
export function evidenceTime(stamp: string): string {
  const m = /^submit-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(stamp);
  if (!m) return stamp;
  const [, y, mo, d, h, mi, s] = m;
  return new Date(Date.UTC(+y, +mo - 1, +d, +h, +mi, +s)).toLocaleString();
}
