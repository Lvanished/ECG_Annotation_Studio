/**
 * Shared viewport math. The view is the half-open integer sample range
 * [start, end). Every pixel position is derived from integer sample indices on
 * demand (never accumulated), so repeated zoom/pan cannot drift.
 */
export interface View {
  start: number;
  end: number;
}

export const MIN_SPAN = 20;

export function clampView(start: number, end: number, n: number): View {
  let span = Math.round(end - start);
  span = Math.max(Math.min(MIN_SPAN, n), Math.min(span, n));
  let s = Math.round(start);
  s = Math.max(0, Math.min(s, n - span));
  return { start: s, end: s + span };
}

export function sampleToX(sample: number, view: View, width: number): number {
  return ((sample - view.start) / (view.end - view.start)) * width;
}

/** Nearest sample *boundary* (0..n) at pixel x. */
export function xToSample(x: number, view: View, width: number): number {
  return view.start + Math.round((x / width) * (view.end - view.start));
}

/** Zoom by `factor` (<1 zooms in) keeping `anchor` at the same pixel. */
export function zoomAt(view: View, anchor: number, factor: number, n: number): View {
  const span = view.end - view.start;
  const newSpan = Math.max(MIN_SPAN, Math.round(span * factor));
  const frac = span > 0 ? (anchor - view.start) / span : 0.5;
  const start = Math.round(anchor - frac * newSpan);
  return clampView(start, start + newSpan, n);
}

export function pan(view: View, delta: number, n: number): View {
  return clampView(view.start + Math.round(delta), view.end + Math.round(delta), n);
}

export function centerOn(view: View, sample: number, n: number): View {
  const span = view.end - view.start;
  const start = Math.round(sample - span / 2);
  return clampView(start, start + span, n);
}

/** Time-grid spacing (seconds) that keeps minor lines at least `minPx` apart. */
export function gridSpacing(pxPerSecond: number, minPx = 5): { minor: number; major: number } {
  const options: [number, number][] = [
    [0.04, 0.2],
    [0.2, 1],
    [1, 5],
    [5, 30],
    [30, 300],
    [300, 1800],
  ];
  for (const [minor, major] of options) {
    if (minor * pxPerSecond >= minPx) return { minor, major };
  }
  return { minor: 600, major: 3600 };
}

export function formatTime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(3)} s`;
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s.toFixed(3).padStart(6, '0')}`;
}
