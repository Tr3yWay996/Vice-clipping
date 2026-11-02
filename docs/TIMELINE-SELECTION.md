# Timeline selection and actual media previews

Click an item to select it. Ctrl-click (or Command-click) toggles individual
items; Shift-click selects an inclusive chronological range. Ties are ordered by
track position and item ID. Ctrl+A selects all timeline items after interacting
with the timeline. Text inputs keep native select-all/copy/paste. Library focus
is separate from timeline focus.

Drag an already-selected item to move the entire group. Relative times remain
fixed. Compatible same-type groups can move between lanes; a group spanning
media types can move horizontally but cannot move vertically as a unit. Unsafe
placements, missing/incompatible destination lanes, and collisions are rejected
atomically with an explanation. Unrelated items are never rippled or overwritten.
Alt-drag bypasses snapping; group snap points exclude every selected item.
Pointer cancellation leaves the original project unchanged.

Plain dragging empty timeline space scrubs playback and clears item selection.
Shift-drag empty space draws a selection rectangle across lanes; Ctrl-drag adds
a rectangle to the existing selection. Escape clears selection or closes a menu.
Right-clicking a selected item preserves its group for context actions.

Ctrl-click or Shift-click track headers to select several tracks. Their context
menu can select the combined contents. Mute and Solo apply to selected audio
headers together; persistent mute is one undo transaction and Solo remains
monitor-only. Renaming and removing multiple headers are explicitly refused:
choose one header for those operations. Detach and I/O boundary trimming likewise
require one item; they never silently edit one member of a group.

Ctrl+C/V copies/pastes the entire group at the playhead with relative offsets and
source references intact. Colliding pastes are rejected. Ctrl+D places a complete
copy after the selection, advancing the whole group to a common free interval
when necessary. Delete removes the entire selection. S splits every selected
item that crosses the playhead; nonintersecting items are untouched. Each group
operation undoes/redoes in one step. Selection is temporary; edits are autosaved
in the existing version-1 project format.

## Real preview artwork

The seeded decorative waveform and stretched cover thumbnail are removed.
Audio items request a real 1,024-bin peak envelope for their chosen audio stream,
source offset, and duration. It uses stereo peak magnitudes from an 8 kHz decoded
preview, displayed with a square-root amplitude scale. This is an overview rather
than a sample-accurate mastering display. Silent regions remain flat.

Video items show up to sixteen small frames sampled progressively through the
item's source interval. Source trims update both previews. Images are lazy-loaded;
waveforms are requested when visible. React/pointer handlers do not decode media.

The local-only API runs at most two FFmpeg analysis processes, deduplicates jobs,
bounds the queued jobs, streams PCM in bounded chunks, and caches results using
filesystem device/inode/size/mtime/ctime plus the requested interval and stream.
It retains at most 512 analysis files and limits waveform ranges to one hour.
Replaced content with a preserved historical mtime gets a different cache key.
Failures leave artwork empty rather than showing made-up peaks. Closing the
server cancels owned analysis processes. No source media is rewritten, and the
recording buffer, encoding settings, and export pipeline are unchanged.

Regression coverage exercises real keyboard/pointer events for the selection
workflows, collision rejection, cancellation, group undo, cross-lane movement,
project reload, native input shortcuts, waveform rendering, and filmstrip URLs.
FFmpeg tests verify real silence/tone envelopes, separate streams, offsets,
changing video frames, cache reuse, content replacement, and failure behavior.
