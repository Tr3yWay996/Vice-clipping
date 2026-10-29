# Trimming and keyframes

The trimming window has a single playback and selection timeline. Click to move
whichever endpoint is closer in time; drag the background to scrub without
changing the selection. Drag either handle to change just that endpoint.
Selections keep a minimum duration of 0.5 seconds (or the entire recording when
it is shorter). The play button plays the recording; Preview loops the selection.

Tab to the playback slider or either handle. Left/Right adjusts time by 0.1
seconds, Shift by 1 second for handles or 5 seconds for playback. Home/End seeks
to the available limits. With keyframes shown, handle arrows step between actual
keyframes. Space or Enter on the playback slider toggles playback. Existing
volume, mute, selection preview, rename, confirmation and keyboard-overlay
behavior remains available.

**Show keyframes & snap** displays the source video's actual keyframes and snaps
boundary edits to the nearest valid keyframe. Hiding it restores arbitrary
frame-accurate cuts. Scrubbing playback stays free in both modes. The separate
**Snap selection to keyframes** button adjusts both endpoints without saving,
including while markers are hidden. It minimizes total endpoint movement over
valid pairs; ties prefer the earlier pair. If there is no pair at least 0.5
seconds apart, the selection stays unchanged and an explanation appears.

Keyframe alignment increases the chance of stream copying. It does not guarantee
a self-contained GOP. Vice still validates stream-copy output and falls back to
its existing precise re-encoding path, preserving recorded audio tracks and
using the existing codec/accelerator preferences.

## Analysis and statistics

The local-only `GET /api/clips/{slug}/keyframes` endpoint asynchronously probes
only the first video stream with FFprobe's `-skip_frame nokey`. Markers use
presentation timestamps relative to the container's timeline origin, never
nominal GOP intervals or decode timestamps. Invalid and out-of-range timestamps
are discarded; duplicate timestamps are collapsed. H.264, HEVC, reordered frames,
irregular keyframes and variable frame rate are covered by regression fixtures.

The collapsed Keyframe information section reports detected keyframes, the
container's exact frame count when available, otherwise an explicitly labeled
average-rate estimate, the frame/keyframe ratio, timestamp-based interval
statistics, and separate average and nominal frame rates. With fewer than two
usable keyframes, interval statistics are unavailable. Missing FFprobe, malformed
files and timeouts leave ordinary trimming usable.

Analyses share in-flight work, run at most two probes concurrently, time out after
120 seconds, and retain at most 32 recordings / 500,000 timestamps in memory.
Reopening unchanged recordings reuses this cache until eviction or server
restart. Only visible markers are aggregated (one per three CSS pixels); binary
search and manual selection snapping always use the complete index. Resizing
recalculates marker aggregation.

## Recording dates and cache identity

Both replacement and save-as-copy apply the source's original `st_mtime_ns` and
captured access timestamp to the finished temporary file **before** atomic
publication. Failed encoding, validation or timestamp restoration leaves the
source recording intact. Save-as-copy keeps the source file and its caches.
Gallery ordering still uses the recording's modification date.

Media revisions include size, nanosecond modification/change times, device and
inode. Replacing media explicitly clears metadata, thumbnail, video/audio proxy,
Discord-copy and keyframe caches. Media URLs carry the revision, so even a
same-sized replacement with its historical modification time cannot reuse the
previous browser video. In-flight metadata/keyframe analyses check the revision
before publishing their results. Renaming carries valid thumbnail/proxy files
forward under the new identity.

Timestamp resolution remains limited by the destination filesystem. Unusable
keyframe timestamps cannot be snapped to; no synthetic endpoint at video duration
is added. New UI copy falls back to English for untranslated locales. No
recording GOP settings or GPU Screen Recorder arguments change.

## Validation

Run `python -m unittest discover -s tests`, `npm test`, `npm run typecheck` and
`npm run build`. The frontend tests exercise the actual modal with media/pointer
stubs; backend integration tests encode real H.264/HEVC VFR media and multi-track
recordings. CI runs the frontend checks alongside the existing Python matrix.

Validated on 2026-10-29 with Python 3.12.14, Node 24.19.0 and local FFmpeg:

- Python: 889 tests run, OK with 6 skips (three pycairo checks, two Flatpak
  checks requiring the kernel's `/proc` task-children interface, one opt-in
  native Qt lifecycle check).
- Frontend: 15 tests passed; TypeScript and the production build passed.
- Real headless Chromium: playback, pointer selection, scrub dragging, both snap
  modes, marker positioning, expandable information and a narrower viewport
  passed. No browser runtime errors were observed.
- Locale validation and `git diff --check` passed. The production build retains
  the existing warning about the single JavaScript bundle exceeding 500 kB.

The test fixtures now isolate dummy-file broadcasts and watchdog output paths;
Flatpak process tests explicitly skip kernels missing their required interface.
These fixes address failures reproduced on the unchanged base revision.
