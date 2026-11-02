/** Stable temporal tiles: zoom changes density, scrolling reuses overlapping samples. */
export function filmstripTiles(
  offset: number,
  duration: number,
  pps: number,
  visibleStart: number,
  visibleEnd: number,
  viewportWidth: number,
) {
  const target = Math.max(96, viewportWidth / 20);
  const step = 2 ** Math.ceil(Math.log2(target / pps));
  const first = Math.max(
    Math.floor(offset / step),
    Math.floor((offset + Math.max(0, visibleStart)) / step) - 1,
  );
  const last = Math.min(
    Math.ceil((offset + duration) / step) - 1,
    Math.floor((offset + Math.min(duration, visibleEnd)) / step) + 1,
  );
  const result = [];
  for (let index = first; index <= last && result.length < 24; index++) {
    const start = Math.max(offset, index * step),
      end = Math.min(offset + duration, (index + 1) * step);
    if (end > start)
      result.push({
        left: (start - offset) * pps,
        width: (end - start) * pps,
        time: (start + end) / 2,
      });
  }
  return result;
}
export function waveformRetryDelay(failures: number) {
  return Math.min(60000, 1000 * 2 ** Math.min(6, Math.max(0, failures - 1)));
}
