# Smart game audio and the audio mixer

Settings → Audio now offers **Recorded Game Audio · Automatic**, live application
entries with separate left/right meters, and persistent application rules. Add
sources in the order you want them recorded, then save settings. Renaming,
enabling/disabling, rules, and capture-level changes apply without restarting the
replay recorder. Adding, removing, or reordering tracks remains a recording-layout
change: save it before the gameplay you want to keep.

For example, choose the automatic game source first, your microphone second,
then Discord and a music player. The automatic source remains on the same track
when the game changes. Mix-first remains optional; it is never enabled for you.
The existing track reorder, remove, and volume controls remain available.

## Requirements and isolation

Smart routing requires GPU Screen Recorder, PipeWire with pipewire-pulse,
WirePlumber **0.5 or newer**, `pw-dump`, `pw-cli`, `pw-link`, `pactl`, and libpulse.
FFmpeg with Pulse input support is needed for the short capture test. The user's
reported GSR version is 6.1.6; Vice uses its existing `-a device:…` capture path.
The documented GSR interface does not provide a command to retarget an audio
track in a running replay buffer, so Vice does not depend on hot-swapping GSR.

Each logical source has one stable private stereo capture device. PipeWire
fans out selected playback ports into it; normal audible application links and
system volumes remain untouched. Gain is applied to that private monitor in
linear amplitude, including for session recordings. GSR keeps the same capture
device while the routing changes, preserving its replay buffer.

These nodes are excluded from WirePlumber session-item/default-device selection
and have no Pulse selection priority. They remain excluded when normal output
devices disappear. Explicitly targeted capture clients use `node.dont-fallback`
and `node.linger`; Vice configures and links their private ports directly. No
unresolved game/rule is replaced by the desktop or default microphone. Unsupported
setups report the limitation. Legacy desktop/input capture remains available by
explicit choice, including on other recording backends.

Restarting the audio server itself can disconnect GSR; Vice cannot preserve data
from a recorder terminated by an external service restart. Routing resumes when
the graph becomes available again. Private capture devices are stereo: native
FL/FR channels are captured and mono sources are duplicated into both channels;
this is not a multichannel surround downmixer.

No global WirePlumber configuration, recording keyframe interval, encoder,
GPU Screen Recorder recording arguments unrelated to audio, or desktop service
is changed. Closing the interface ends its meter lease; recording diagnostics
continue in the daemon. Shutting down Vice removes its capture modules and links.

## Identifying games and applications

Automatic identification uses the recorded window when window capture is pinned,
otherwise Steam process identity, native game desktop entries, and Vice's existing
game recognizer. It remembers the last game during a temporary browser/Discord
alt-tab. Process families and executable paths distinguish game streams from
shared engine labels such as **FMOD Audio**. A newly started game reconnects by
executable/path rather than obsolete PipeWire node IDs.

Games with no Steam identity, matching native game desktop entry, recognized rule,
or pinned captured window cannot be identified safely from focus alone. They
show **Game not detected**; add an executable/path rule in the automatic source's
editor when necessary. Vice does not guess that arbitrary foreground audio is a
game. Known browser/Discord executables are excluded from automatic game routing.

Application rules support case-insensitive exact/contains matching and optional
regex against application name, ID, executable, path, or node name. Multiple
rules form a union and match every relevant stream/instance. Match previews show
live results. Broad rules can include unrelated applications: ambiguity and
multi-track overlap warnings help refine them. Regex runs in a separate process
with a 100 ms evaluation deadline and bounded rules, so a bad pattern cannot
stall recording or the UI.

Existing `audio_tracks` IDs, order, levels, and behavior are preserved. Use
**Manage this source** to explicitly convert a legacy source into a logical
source with persistent rules and live enable/gain controls. This one-time ID
change is a layout change when saved. No automatic migration discards old tracks.
Capture tests for legacy raw GSR application IDs ask you to manage that source
first, rather than claiming the raw name has a verified isolated capture path.

## Meters and diagnostics

Application meters measure a private fan-out of each application's real playback;
track meters read the post-gain private capture monitor. They are native stereo
libpulse peak streams at 25 Hz; React receives scalar levels at up to 10 Hz over
the existing WebSocket. An absent measurement is **Meter unavailable**, not a
fabricated silent/active level. The UI separately identifies a GSR connection to
the source, so application discovery alone does not prove recording.

Warnings distinguish missing game, missing stream, disconnected routing,
unsupported capture, muted sources, and sustained silence. Silence remains a
Settings status and creates no intrusive warning by default.
Optional silence notifications use a configurable duration (180 seconds by
default). Actual failures have dismissible, deduplicated episodes that clear on
recovery; see [warning preferences and editor audio](EDITOR-AUDIO.md).
Naturally idle streams remain connected. These
checks cannot prove a game's intended sound exists if the game itself is silent.

**Test Audio Capture** records three seconds from each applied individual source,
analyzes its real stereo PCM, and offers WAV playback. It does not stop GSR,
flush the buffer, export a library clip, or change your audible routing. Save
pending settings before testing. The optional combined compatibility track is
not duplicated in this source test. Samples are local-only, deleted on clear,
replacement test, component unmount, or daemon shutdown, and expire after ten
minutes. Up to eight sample sets and sixteen sampled tracks are retained;
application picker metering is limited to 32 streams while visible. Meter leases
expire after 45 seconds if the interface vanishes.

## Validation

Unit/component tests cover identity, bounded regex, matching, routing, isolation,
track layout, persistence, gains, connection diagnostics, samples, translations,
and settings controls. For a real PCM check without a GPU or desktop, install the
requirements above plus `paplay`, `parec`, and `dbus-daemon`, then run:

```sh
python tools/test-smart-audio.py
```

The script starts its own private PipeWire, pipewire-pulse, WirePlumber, and D-Bus
processes in a temporary runtime. It never restarts the desktop's services. It
checks launch-before-game, FMOD/executable identity, actual stereo levels,
separate game/music WAV spectra, alt-tab retention, new game process/node IDs,
game switching, default-output moves, live gain, disabled sources, sample cleanup,
and default-device exclusion after normal sinks disappear. One continuous
recorder client remains alive during all changes.

This verifies the native audio graph and recorded PCM, rather than GPU video
encoding. A real NVIDIA/KDE Wayland/GSR session and Flatpak sandbox device access
still require desktop hardware validation; no cloud test can establish those.

References: [pw-link](https://docs.pipewire.org/page_man_pw-link_1.html),
[libpulse recording streams](https://freedesktop.org/software/pulseaudio/doxygen/stream_8h.html),
[GSR command interface](https://man.archlinux.org/man/gpu-screen-recorder.1.en).
