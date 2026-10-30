import {boundaryAtPlayhead, type Boundary} from '../lib/trimming';
import type {EdItem} from './editorTypes';

const same = (a: number, b: number) => Math.abs(a - b) < .001;

/** Compute a complete, non-ripple edit before creating an undo transaction. */
export function trimAtPlayhead(items: EdItem[], selected: EdItem | null, boundary: Boundary,
  playhead: number, sourceDuration: number): EdItem[] | null {
  if (!selected || selected.kind !== 'clip' || !Number.isFinite(sourceDuration)) return null;
  const end = selected.start + selected.dur;
  if (playhead < selected.start || playhead > end) return null;
  const next = boundaryAtPlayhead({start:selected.start, end}, boundary, playhead, end);
  if (!next) return null;
  const delta = next.start - selected.start;
  const offset = (selected.offset ?? 0) + delta;
  const duration = next.end - next.start;
  if (offset < 0 || offset + duration > sourceDuration + .001) return null;
  const companions = selected.muted ? items.filter(item => item.kind === 'audio' && item.clipId === selected.clipId &&
    same((item.offset ?? 0) - item.start, (selected.offset ?? 0) - selected.start) &&
    item.start < end && item.start + item.dur > selected.start) : [];
  // Old projects have no explicit audio links. Coextensive detached streams
  // are unambiguous; independently edited streams require deliberate editing.
  if (companions.some(item => !same(item.start, selected.start) || !same(item.dur, selected.dur))) return null;
  const ids = new Set([selected.id, ...companions.map(item => item.id)]);
  return items.map(item => {
    if (ids.has(item.id)) {
      const changed = {...item, start:next.start, dur:duration, offset};
      if (boundary === 'start' && delta > 0) delete changed.trans;
      return changed;
    }
    // Cutting OUT creates a gap; an incoming transition on the following
    // clip must no longer blend across the removed junction.
    if (boundary === 'end' && next.end < end && item.trackId === selected.trackId && same(item.start, end) && item.trans) {
      const changed = {...item}; delete changed.trans; return changed;
    }
    return item;
  });
}
