# Playback and trimming shortcuts

The viewer, Quick Trimmer and timeline editor share transport controls, monitoring
volume, mute preferences and keyboard interpretation. Their media engines remain
separate: the editor still uses its multitrack video/audio pool and composition
clock.

| Key | Playback action |
| --- | --- |
| Space (tap) | Play or pause on release |
| Space (hold) | Temporary playback boost; wheel adjusts by 0.25× |
| F2 | Rename the opened/focused clip, or selected editor source |
| Left / Right | Seek backward / forward 1 second |
| Shift + Left / Right | Fine seek backward / forward 0.1 seconds |
| Up / Down | Raise / lower monitoring volume by 5 percentage points |
| M | Mute / unmute monitoring |
| Home / End | Seek to the beginning / end |
| I / O | Set IN / OUT in the Quick Trimmer, or trim a selected editor video |

Seeking clamps to the recording/composition duration and preserves whether it is
playing or paused. Fine steps use actual media timestamps; they are not rounded
to an assumed 60 FPS frame or fixed keyframe interval. This is timestamp seeking,
not a promise of single-frame stepping on every decoder/VFR source.

Settings → Appearance → **Arrow key behavior** selects the viewer's arrows:

- **Playback navigation**, the default for this fork, uses the table above.
- **Clip navigation (legacy)** keeps Left/Right switching between clips and leaves
  Up/Down alone. The other playback surfaces always use playback navigation.

The preference is saved as `ui.arrow_key_behavior = "playback"` or `"clips"` in
Vice's existing configuration. Old configs default to playback navigation.
Changing it needs no daemon restart and does not affect recording hotkeys.

Viewer and Quick Trimmer titles now open their existing rename field with one
click. Enter confirms and Escape cancels; see [Trash and renaming](TRASH.md) for
playback preservation and delayed Quick Trimmer saves.

Hold Space for 250 ms to start the temporary speed (2× by default). Release
restores the previous playback rate; a preview that was paused returns to paused.
The **Hold speed** selector in each player configures/resets the multiplier
without a mouse wheel, from 0.25× to 4×. It is saved as `ui.playback_boost` through
the existing configuration API, shared across clips and application restarts.
Wheel adjustments persist once on release. Blur, hidden windows, typing,
new dialogs, clip changes and unmounting cancel the hold safely. The editor
applies speed to its preview clock, video pool and audio monitoring only; export
and project timing stay unchanged.

F2 uses the same inline rename field as the existing gestures. The Quick Trimmer
still delays the filesystem rename until it closes. In the library, focus a card
or one of its controls first. In the editor, focus a library source or select a
video/audio item; F2 renames that source, never the project or text.

## Shortcut ownership and accessibility

A single shared document dispatcher handles the active playback context. An open
player dialog takes priority over the page underneath. Other dialogs, including
editor export/reset, block underlying players even when nested inside the same
DOM container. Opening or closing surfaces registers/unregisters their handlers;
React re-renders update callbacks without adding more global listeners.

Ordinary clicks on the stage, readouts or modal background do not require
refocusing a transport control. Text entry, IME composition, editable fields,
renaming, dropdowns and accessibility widgets retain their own keys. Native
buttons, links and disclosure summaries keep Space activation; range inputs keep
their own arrow behavior. Ctrl/Alt/Meta playback combinations are untouched.
The editor's existing Ctrl/Meta undo/redo, copy/paste, duplication, split, delete,
zoom and deselection remain available in an appropriate editing context.

## Quick Trimmer: playback and boundaries are independent

- Click the timeline to seek. Drag its background to scrub.
- Shift + click changes the nearest boundary. Drag a handle to change only it.
- I sets IN and O sets OUT at the current playback position.
- All boundary edits, focused-handle arrows, automatic keyframe snapping and the
  manual snap-selection action leave playback position and playing/paused state
  unchanged. Editing exits selection-loop mode without pausing or seeking.
- Preview explicitly starts at IN and loops the selection. Stop ends that preview.

I/O refuses a crossed, out-of-range or too-short selection and shows compact
feedback. The opposite boundary never moves to accommodate an invalid command.
The minimum remains 0.5 seconds, or the entire recording if shorter. Pointer
handles retain their existing constrained dragging. With keyframes shown,
boundary operations use actual extracted timestamps; playback navigation never
snaps to keyframes. Focused handle arrows move by 1 second, or 0.1 with Shift;
with keyframes shown they step between actual valid keyframes instead.

The trimmer has a collapsed, translated shortcut reference beside its timeline.
Its controls reuse the viewer's play/pause, time, volume, loading and error logic.
No native progress bar is introduced.

## Full editor: non-ripple I/O and monitoring

Select a video item and place the timeline playhead inside it. I moves its start
to the playhead, reduces duration and increases the source offset by the same
amount. O changes its duration to end at the playhead. Neither operation moves
the composition playhead, neighboring items or other timeline tracks.

Coextensive detached audio streams with the same source/time mapping follow the
edit, preserving gain and mute. Older projects have no explicit audio-link
metadata: if related detached audio has been independently trimmed, the operation
is rejected atomically rather than guessing or partially desynchronizing it.
Select and edit those independently timed items deliberately instead.

A broken transition junction is cleared and remaining transition lengths stay
within clip bounds. All affected video, audio and transition changes form one
existing undo transaction. Undo/redo restores the complete edit. Invalid sources,
missing selections and invalid cut positions leave the project untouched.

The editor's shared volume/mute controls affect preview monitoring only. Audio
item gains, recorded audio, project data and export settings are unchanged.
Paused fine seeks use an exact target; a seek already in progress retains the
latest requested position until the decoder can accept it. All three surfaces
coalesce pointer scrubbing through the same animation-frame scheduler.
Decoder warm-up is time-bounded and parks back at the paused position, so muted
warm-up cannot keep moving the picture underneath a stopped composition clock.

## Validation

Regression coverage includes modal ownership (including nested export dialogs),
input/IME protection, cleanup, viewer preference modes and persistence, trimmer
keyboard and pointer operations, source-offset/audio synchronization, transition
cleanup, undo/redo and delayed decoder seeks.

A real headless Chromium check used H.264/AAC media with the actual viewer,
trimmer and editor. It exercised Space after ordinary interaction, pointer edits
without seeking, snapping without seeking, fine seek, both viewer arrow modes,
editor I/O and undo, export-dialog isolation, and a narrow trimmer viewport.
French UI was also checked at the reference recording's window size.

Remaining manual checks on KDE Plasma Wayland:

1. Repeat shortcuts in the native QtWebEngine window, including French/AZERTY
   key entry, changing focus, opening/closing dialogs and renaming.
2. Try hardware-decoded recordings and HEVC proxies; verify rapid fine seeks,
   loading/error feedback, audio/video synchronization and resource cleanup.
3. Check multitrack preview monitoring and I/O with detached audio, transitions,
   undo/redo and a concurrent recording/background processing job.

Run the normal Python suite, `npm test`, `npm run typecheck`,
`npm run i18n:check` and `npm run build`. KDE/native GPU behavior is not claimed
as verified by the browser checks.

Implementation results: 911 Python tests run (905 passed, 6 skipped), 79 frontend
tests passed, and TypeScript, localization, Python compilation and production
build passed. The final generated assets also passed the Python UI-static checks.
The real Chromium check included the bounded decoder warm-up regression and the
French trimmer at 894×799. Existing runtime font-path/single-bundle warnings and
older translation gaps outside this change remain.
