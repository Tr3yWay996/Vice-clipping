/** Timeline calculations are independent of media elements and pointer events. */
export const MIN_SELECTION = 0.5;
export type Selection = {start: number; end: number};
export type Boundary = keyof Selection;

/** I/O rejects an invalid request instead of clamping it or moving its partner. */
export function boundaryAtPlayhead(selection: Selection, boundary: Boundary, at: number, total: number,
  keys?: number[]): Selection | null {
  const minimum = Math.min(MIN_SELECTION, total);
  const min = boundary === 'start' ? 0 : selection.start + minimum;
  const max = boundary === 'start' ? selection.end - minimum : total;
  if (!Number.isFinite(at) || at < min || at > max || total <= 0) return null;
  const next = keys ? nearestKeyframe(keys, at, min, max) : at;
  return next === null ? null : {...selection, [boundary]: next};
}
export interface KeyframeInfo {
  timestamps: number[];
  total_keyframes: number;
  total_frames: number | null;
  frames_estimated: boolean;
  average_fps: number | null;
  nominal_fps: number | null;
  average_interval: number | null;
  min_interval: number | null;
  max_interval: number | null;
}

export function lowerBound(times: number[], at: number): number {
  let lo = 0,
    hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (times[mid] < at) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function nearestKeyframe(
  times: number[],
  at: number,
  min = 0,
  max = Infinity,
): number | null {
  const lo = lowerBound(times, min);
  const hi = lowerBound(times, max);
  const last = times[hi] === max ? hi : hi - 1;
  if (lo > last) return null;
  const next = Math.max(lo, Math.min(last, lowerBound(times, at)));
  const prev = Math.max(lo, next - 1);
  return Math.abs(times[prev] - at) <= Math.abs(times[next] - at) ? times[prev] : times[next];
}

export function nearestBoundary(selection: Selection, at: number): Boundary {
  return Math.abs(selection.start - at) <= Math.abs(selection.end - at) ? 'start' : 'end';
}

export function moveBoundary(
  selection: Selection,
  boundary: Boundary,
  at: number,
  total: number,
  keys?: number[],
): Selection {
  const minimum = Math.min(MIN_SELECTION, total);
  const min = boundary === 'start' ? 0 : selection.start + minimum;
  const max = boundary === 'start' ? selection.end - minimum : total;
  const target = keys ? nearestKeyframe(keys, at, min, max) : Math.max(min, Math.min(max, at));
  return target === null ? selection : {...selection, [boundary]: target};
}

/** Globally closest valid pair by total endpoint displacement; never invent keys. */
export function snapSelection(
  selection: Selection,
  times: number[],
  total: number,
): Selection | null {
  let best: Selection | null = null,
    cost = Infinity;
  const minimum = Math.min(MIN_SELECTION, total);
  // For each start, only the end nearest the original end can minimize cost.
  for (const start of times) {
    if (start < 0 || start + minimum > total) continue;
    const end = nearestKeyframe(times, selection.end, start + minimum, total);
    if (end === null) continue;
    const nextCost = Math.abs(start - selection.start) + Math.abs(end - selection.end);
    if (nextCost < cost) {
      cost = nextCost;
      best = {start, end};
    }
  }
  return best;
}

/** At most one DOM marker per three CSS pixels; snapping keeps the full index. */
export function visibleKeyframes(times: number[], total: number, width: number): number[] {
  if (!total || !width) return [];
  let previous = -Infinity;
  return times.filter((at) => {
    if (at < 0 || at > total) return false;
    const pixel = Math.floor(((at / total) * width) / 3);
    if (pixel === previous) return false;
    previous = pixel;
    return true;
  });
}
