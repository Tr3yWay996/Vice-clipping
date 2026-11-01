# Audio warnings and quick audio editing

Audio diagnostics remain visible in Settings → Audio, including live levels,
missing sources, unsupported capture, routing errors, muted sources, and silence.
Ordinary inactivity and intentional mute do not create intrusive warnings.

Open **Audio warnings** in Settings → Audio to configure:

- Critical capture failures: on by default.
- Disconnected sources: on by default.
- Prolonged silence: off by default, with a configurable duration (180 seconds
  initially; 30 seconds to 24 hours allowed).
- Restore warnings previously silenced for a particular condition or source.

A failure has one episode ID until capture recovers. Repeated status/level
updates, source name changes, or updates to the same unresolved failure do not
create another alert. Dismissal lasts for that episode, including an interface
reload. A recovery clears the episode; a later genuine failure may warn again.
“Silence this warning” and “Silence this source” persist in recording settings.
Changing warning preferences never restarts the replay buffer.

## Names and audibility

Detach Audio inherits MP4/MKV stream titles, including custom recording-source
names and MP4 `handler_name` tags. Existing recordings without useful metadata
get numbered fallback labels. Vice will not reuse an unrelated named lane. Track
IDs, editable labels, mute, gain, and source association are separate project
fields. Duplicate labels keep the exact text you chose; small A1/A2 badges and
different track IDs distinguish their lanes.

Named separate streams start audible, with the embedded video's audio muted.
A known combined mix starts track-muted to avoid doubling the separate streams.
For older unnamed multi-stream recordings, only the first track starts audible;
Vice explains this and exposes the other tracks' M controls. It cannot infer
whether unnamed streams contain a combined mix without additional analysis.
No audio is discarded. Use M or the item inspector to choose the sources.

Double-click a header, use its context menu, or select it and press F2 to rename.
M is persistent track mute. S is temporary monitoring Solo; Shift-click supports
multiple Solo tracks. The compact header gain slider is independent of both.
The audio item's inspector still controls its own stream, gain, and mute.

Right-click audio items for mute, split, duplicate, copy/paste, delete, volume,
and revealing the original clip in the gallery. Right-click a track for naming,
mute, Solo, resetting its gain, adding/removing tracks, or selecting its contents.
Menus support keyboard navigation and Escape. See [keyboard controls](KEYBOARD.md).

## Media and exports

Recorded stream titles are written with stream copy, using `title` and
`handler_name`, including legacy desktop/microphone/application configurations
and single mixed recordings. All streams, codecs, order, and historical mtime
are retained. Copy/trim operations retain supported container metadata. External
editors decide which metadata they display: ffprobe can verify the stored names,
but Vice cannot force every editor to show them.

Full-editor export still mixes audio by default. **Export separate named audio
tracks** explicitly produces one stream per audio lane (plus audible embedded
video lanes), with the lane's chosen name and an aligned silent anchor. Muted
lanes export silence so their names/order remain available. There is no extra
rendering pipeline or recording change: this uses the existing FFmpeg graph.
Discord-optimized export retains one compatibility mix. Temporary Solo never
changes either export mode; persistent item/track mutes and gains do.

Validation includes real MP4/MKV naming, copy/trim/video-reencode preservation,
actual separate-stream export and silent muted stems, project round trips,
warning episode/dismissal tests, and editor preview/keyboard/menu tests.
