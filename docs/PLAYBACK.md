# Reliable playback and editor timeline synchronization

Vice keeps its current appearance, player chrome, timeline, inspector and editing
workflows. This change repairs transport behavior shared by the Viewer, its
window-filling mode, Quick Trimmer and the full Editor.

## Playback shortcuts and focus

Space toggles playback after ordinary pointer interactions, including clicking
volume, mute and other controls. Hold-Space and wheel speed adjustment keep their
existing playback-only behavior. Arrow seeking/volume, M, Home/End, F2 and the
context's existing I/O actions use the shared `playbackShortcuts.ts` dispatcher.
The Viewer's configured legacy clip-navigation arrow mode remains available.

A mouse-focused control does not trap the next transport key. Tab resets that
pointer focus: keyboard-focused buttons retain Space activation, and native
volume sliders retain arrow/Home/End stepping. Text fields, IME input, inspector
fields, menus and other editing/accessibility widgets keep their keys. Enter
still activates buttons. The current modal owns playback, including when another
player is mounted underneath; export dialogs block the underlying player.

The Viewer's bottom transport bar is a sibling of its modal. Its explicit control
scope belongs to that player without broadening modal ownership to unrelated
application controls. Only one document keyboard dispatcher is installed and it
is removed when its last playback context unmounts.

Viewer inline and window-filling timelines share pointer capture/cleanup, seek
immediately on press, coalesce move events through the existing animation-frame
scheduler and commit the final pointer position exactly. Editor ruler and empty
lanes do the same. Timeline focus moves away from the previously clicked volume
control. Clicking a clip item still selects/edits it without repositioning the
playhead. Trimmer boundary edits and snapping keep their existing independent
preview behavior. Clicking the editor video toggles playback; text manipulation
and loading/error overlays retain their own interactions.

## Editor decoder and clock behavior

Previously, `seek()` moved the logical playhead, but an already playing master
video only sought on a fresh clip or track promotion. A seek inside the same clip
could therefore leave the decoder at its old source time. The clock's wall-time
fallback then made the timeline appear to keep progressing over the wrong frame.

Explicit seeks now reach the master and secondary videos, detached audio and
outgoing transition media. Each element retains the latest pending target while
metadata loads or another seek decodes. `loadedmetadata`/`seeked` commit that
request; normal playback corrections cannot overwrite it. A deliberate paused
seek cancels the current element's decoder warm-up, so an older timer cannot
move the preview back. Preloaded upcoming elements retain their bounded warm-up.

During playback, the active master video supplies timeline time, or detached
audio supplies it in an audio-only region. Wall time advances only a genuine gap
with no active media. An unchanged media timestamp leaves the playhead unchanged;
large timestamp differences never trigger a wall-time substitute. Seeking,
loading and waiting hold the clock and pause active companion media together.
Readiness events resume synchronization without accumulating elapsed wall time.
Ordinary master playback does not seek on each animation frame. Secondary drift
correction retains its existing tolerance and the three-element video pool.

The existing loading overlay now covers ordinary loading, seeking and buffering,
as well as proxy preparation. It uses a general localized loading message.
Actual media errors retain the existing failure behavior. Play from the last
frame explicitly resets decoder and audio positions when wrapping to the start.

Playback does not rewrite source files, editor timing, track gains, export data,
recording settings or queue state. Split, trim handles, independent selection,
multitrack editing, zoom/scroll, contextual inspector controls and undo/redo keep
their existing implementations.

## Interaction research

The official Medal references were reviewed for interaction principles, not visual
design or source code:

- [New editor overview](https://medal.tv/blog/posts/the-new-and-improved-medal-video-editor):
  multitrack editing, detached audio, contextual clip adjustments and shortcuts.
  Vice retains its existing tracks, inspector and playback-only speed tools;
  this patch does not add destructive clip-speed or export transformations.
- [Advanced Editor guide](https://support.medal.tv/support/solutions/articles/48001275437/):
  trimming preserves timeline gaps and large sources need careful resource use.
  Vice keeps non-ripple edits and its bounded pool/preloading strategy.
- [Trim, split and duplicate](https://support.medal.tv/support/solutions/articles/48001211535-how-to-trim-split-and-duplicate-clips):
  select a timeline item, position the playhead independently, then edit/split.
  Vice retains its existing split-at-playhead, item selection and undo workflows.
- [VFX guide](https://support.medal.tv/support/solutions/articles/48001201806-how-to-add-vfx-to-your-clips):
  timeline-wide and clip-specific effects have different scopes. Vice preserves
  its current effect/transition and contextual inspector model.

## Validation and desktop checks

Automated regressions cover same-clip seeks while playing/paused, rapid requests,
metadata/decoder readiness, stalled video/audio, authoritative clocks, overlaps,
transitions, gaps, boundary playback, final-frame restart, pointer cleanup,
shared shortcuts, detached transport ownership, input/modal isolation and existing
editing/undo/rename/speed behavior.

Production Chromium verification uses actual aiohttp/FFmpeg media: a 65-second
H.264 recording with two AAC streams, a second recording, detached audio,
overlapping video, a transition, a caption and a gap. The 10-to-30-second seek is
checked against the source decoder's 32-second frame (including its source offset)
using native video-frame callbacks, with the preview paused and playing. Keyboard
and scrub interactions run in the French Viewer, window-filling mode, Trimmer
and Editor. Buffering events are additionally controlled in automated tests.

KDE Plasma Wayland focus and native QtWebEngine/GPU/HEVC playback still require a
real desktop check. The browser run does not establish native hardware-decoder
performance. Existing native shortcuts and proxy paths are reused.

Validation for this patch: 998 Python tests ran (992 passed, 6 environment-dependent
skips), 164 frontend tests passed across 19 files, and TypeScript, localization,
production build and whitespace checks passed. The old Python check for the exact
clock expression's variable name was replaced by executable frontend regressions.
The repository has no configured standalone lint command. Existing font-path,
single-bundle-size warnings and unrelated translation gaps remain.
