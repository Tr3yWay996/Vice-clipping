import {expect, it} from 'vitest';
import {filmstripTiles, waveformRetryDelay} from './timelineArtwork';
it('samples the visible part of a ten-minute clip at zoom-dependent density', () => {
  for (const pps of [2, 12, 48, 100])
    for (const width of [600, 1200, 3840]) {
      const tiles = filmstripTiles(10, 600, pps, 300, 300 + width / pps, width);
      expect(tiles.length).toBeGreaterThan(0);
      expect(tiles.length).toBeLessThanOrEqual(24);
      expect(tiles.every((tile) => tile.time >= 10 && tile.time <= 610)).toBe(
        true,
      );
      expect(
        tiles.every((tile) => tile.width <= Math.max(96, width / 20) * 2),
      ).toBe(true);
    }
  const distant = filmstripTiles(0, 600, 100, 400, 410, 1000);
  expect(distant.every((tile) => tile.time > 390 && tile.time < 420)).toBe(
    true,
  );
});
it('reuses temporal samples across a small scroll and caps backoff at one request per minute', () => {
  const a = filmstripTiles(0, 600, 12, 300, 370, 1000),
    b = filmstripTiles(0, 600, 12, 301, 371, 1000);
  expect(b.some((tile) => a.some((old) => old.time === tile.time))).toBe(true);
  expect([1, 2, 3, 4, 5, 6, 7, 100].map(waveformRetryDelay)).toEqual([
    1000, 2000, 4000, 8000, 16000, 32000, 60000, 60000,
  ]);
});
