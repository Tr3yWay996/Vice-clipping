import {describe, expect, it} from 'vitest';
import {
  moveBoundary,
  nearestBoundary,
  nearestKeyframe,
  snapSelection,
  visibleKeyframes,
} from './trimming';

describe('timeline selection', () => {
  it('moves the endpoint nearest in time and enforces the minimum', () => {
    const selection = {start: 10, end: 50};
    expect(nearestBoundary(selection, 15)).toBe('start');
    expect(nearestBoundary(selection, 45)).toBe('end');
    expect(moveBoundary(selection, 'start', 100, 60)).toEqual({start: 49.5, end: 50});
    expect(moveBoundary(selection, 'end', -10, 60)).toEqual({start: 10, end: 10.5});
    expect(moveBoundary(selection, 'end', 100, 60).end).toBe(60);
  });
  it('snaps only to real keys in the valid range', () => {
    expect(nearestKeyframe([0, 1.23, 3.98], 1.3)).toBe(1.23);
    expect(nearestKeyframe([], 1)).toBeNull();
    expect(moveBoundary({start: 0, end: 2}, 'start', 1.9, 5, [0, 1, 1.8, 4])).toEqual({
      start: 1,
      end: 2,
    });
    expect(moveBoundary({start: 1, end: 2}, 'end', 1.8, 5, [0, 1])).toEqual({start: 1, end: 2});
    expect(moveBoundary({start: 0, end: 2}, 'start', 1.3, 5).start).toBe(1.3);
  });
  it('finds a closest valid pair when independent nearest keys collapse', () => {
    expect(snapSelection({start: 1.7, end: 2.3}, [0, 2, 4], 5)).toEqual({start: 0, end: 2});
    expect(snapSelection({start: 0, end: 5}, [2], 5)).toBeNull();
    expect(snapSelection({start: 0, end: 5}, [2, 2.1], 5)).toBeNull();
    expect(snapSelection({start: 1, end: 5}, [], 5)).toBeNull();
  });
  it('matches exhaustive optimal pair selection over irregular distributions', () => {
    const keys = [0, 0.1, 0.48, 0.8, 1.04, 2.78, 3.2, 7.1];
    for (let start = 0; start < 7; start += 0.23) {
      for (let end = start + 0.5; end <= 8; end += 0.37) {
        const result = snapSelection({start, end}, keys, 8)!;
        const all = keys.flatMap((a) =>
          keys.filter((b) => b - a >= 0.5).map((b) => Math.abs(start - a) + Math.abs(end - b)),
        );
        expect(Math.abs(start - result.start) + Math.abs(end - result.end)).toBeCloseTo(
          Math.min(...all),
        );
      }
    }
  });
  it('aggregates dense markers without changing the snapping index', () => {
    const keys = Array.from({length: 10000}, (_, i) => i / 1000);
    expect(visibleKeyframes(keys, 10, 600).length).toBeLessThanOrEqual(201);
    expect(nearestKeyframe(keys, 1.234)).toBe(1.234);
    expect(visibleKeyframes([0, 1, 2, 3], 4, 600)).toEqual([0, 1, 2, 3]);
  });
});
