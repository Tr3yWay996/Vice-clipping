# Playback and background processing

The viewer and trim modal share playback controls, audio preferences, loading and
failure handling, exact seeking and animation-frame-coalesced scrubbing. A normal
click on the trim timeline seeks. Shift + click changes the nearest boundary;
handles still drag without Shift. Boundary edits and snapping leave playback
position and state unchanged. Showing keyframes enables boundary snapping.
Playback seeking remains free in either mode. See [the keyboard guide](KEYBOARD.md)
for shared shortcuts, viewer preferences and full editor I/O semantics.

## Daemon-owned jobs

Trims, editor exports and explicit sharing preparations submit work to the daemon.
The homepage displays the queue by default. Settings → Appearance → Homepage side
panel restores Images; the Images page and screenshot shortcut remain available.
Closing or minimizing the interface leaves jobs and recording running. Explicitly
quitting Vice or stopping `vice.service` interrupts active jobs.

`vice/jobs.py` stores versioned history atomically in
`~/.local/share/vice/jobs.json`, with owner-only permissions. Existing users need no
manual migration. Configuration without `ui.home_side_panel` defaults to `queue`.
The existing configuration writer persists `queue` or `images` without a recorder
restart.

The queue reuses `ExportManager` and the server's media resource lock. Legacy
export, proxy, audio preparation and synchronous trim APIs share that lock, so
only one resource-heavy preparation runs at a time. Metadata and thumbnails are
not prominent queue jobs. Recording has its own process and never waits for this
lock. Background FFmpeg runs with two CPU threads and a lower CPU priority;
recording settings and GPU Screen Recorder arguments are unchanged. GPU rendering
still shares hardware with a game and recorder, so users can pause processing
while playing.

`vice/processing.py` owns a separate process group for each invocation. Pause and
resume send SIGSTOP and SIGCONT to that group. Cancel resumes a stopped group,
kills it and reaps the child before advancing the queue. A Linux parent-death
signal prevents an encoder surviving an abruptly killed daemon. Controls are
disabled during stages without an active process and final file publication.

Progress comes from FFmpeg's `-progress` output. Multi-stage work can reset its
percentage when moving from copying to fallback encoding or validation; Vice does
not combine stages into an invented overall percentage. Validation and file
publication are indeterminate. Elapsed time excludes suspension; estimates use
observed progress in the current stage. Liquid waves are CSS transforms and obey
reduced-motion preferences.

The UI subscribes to existing WebSocket events and obtains an authoritative REST
snapshot at initialization, reconnection, focus, online and visibility recovery.
An older HTTP response cannot replace a newer queue event. No polling is needed.
History renders in batches of 20, with active work ahead of completed history.

On daemon restart, queued jobs resume when their indexed source revisions still
match. Work that was processing or actively paused becomes Interrupted and its
recorded temporary outputs are removed. Retry starts a fresh invocation, not a
mid-encode resume. Completed files are never inferred from partial outputs.
An output committed immediately before an abrupt daemon crash may exist while
the job is marked interrupted; export retries refuse to overwrite it. Remove or
rename that output before retrying. Source changes or deletion cause a clear
failure rather than processing a different recording. Queue history persists
until its entries are removed.

Trims retain stream-copy-first validation, source-codec fallback, separate audio
tracks, historical nanosecond timestamps and explicit cache invalidation. Fast
copy trims remain copies; joining the scheduler does not force transcoding.

## Original-file drag

Clip cards reuse the compact drag preview and internal playlist MIME identifier.
The local-only `/api/clips/{slug}/file` endpoint resolves indexed recordings, never
an arbitrary client-supplied path. Public sharing routes expose neither this
endpoint nor the job API. Ordinary card drags do not prepare, encode or substitute
a sharing URL. The share sheet explicitly queues its existing Discord preparation
and reuses that result.

On QtWebEngine, the existing pywebview bridge launches a Qt native QDrag on the
GUI thread, with QUrl file URLs and copy semantics. It retains the playlist MIME
identifier and a themed thumbnail/name preview. Escape cancels quietly. Internal
drops are routed to the same playlist hook because Chromium strips custom MIME
types from native file drops. Rejected
or unavailable drops offer the existing copy-file/share workflow. GTK and browser
sessions retain the HTML file-URI fallback, whose external capabilities depend on
the web engine and receiving application. Sandboxed targets can reject local
files; Vice cannot override their permissions. Original recordings are not moved
or deleted.

## Validation and desktop checklist

Automated regressions cover seek gestures, shared audio controls, keyframe tools,
French statistics, durable queue ordering/recovery, real process suspension and
cancellation, parent-death cleanup, timestamp-preserving background trims,
background editor exports without a connected interface, reconnect snapshots,
Appearance persistence, file-index security, URI encoding, playlist drops and
translation enforcement. Run:

```sh
python -m unittest discover -s tests
npm test
npm run typecheck
npm run i18n:check
npm run build
```

A real X11 test used the actual React ClipCard in pywebview/QtWebEngine, its native
bridge and a separate Qt receiving application. The receiver copied the video;
its hash matched, the original hash and nanosecond timestamp were unchanged,
the internal playlist identifier survived and Qt reported CopyAction. The tested
filename included spaces, accented characters and `#`.
An additional real native drop back into QtWebEngine reached the existing
playlist drop hook with the correct identifier.
Repeat this opt-in integration check on an isolated X11 display with
`xvfb-run -a python tools/native-drag-smoke.py` after `npm ci`; it also requires
xdotool, FFmpeg and the QtWebEngine/pywebview Python packages. It controls that
display's pointer, so do not run it on a display in use.

**Not verified in this environment:** KDE Plasma Wayland, Discord, Dolphin,
sandboxed browser uploads, and GPU/game recording under simultaneous load. On the
target desktop, check:

1. Drag an ordinary card to Dolphin. Compare hashes and confirm the original
   remains. Drag it onto a playlist as well.
2. Drop into Discord and a browser upload target, including Flatpak versions when
   applicable. Confirm they receive a video attachment, not a link. If a sandbox
   rejects the file, verify the fallback notification and copy/share workflow.
3. Drag the explicitly prepared share-sheet version; confirm it uses the prepared
   file. Test Escape and rejected targets without losing the original.
4. Submit two jobs while recording, close the window, reopen it, and inspect the
   queue. Pause/resume during encoding and confirm the game remains usable.
5. Restart the service during an encode; confirm Interrupted, temporary cleanup,
   retained pending/history entries and a fresh retry.
6. Test narrow windows, French, reduced motion, and switching Queue/Images while
   work continues.

## Install this fork on Arch

Merging a PR changes your fork; it does not update a package installed from an
Arch repository. Rebuild a package from this fork **after merging into main**.
The checked-in PKGBUILD normally downloads upstream's release, so use a separate
copy pointed at this fork:

```sh
sudo pacman -S --needed base-devel git
git clone https://github.com/Tr3yWay996/Vice-clipping.git
cd Vice-clipping
cp PKGBUILD PKGBUILD.fork
sed -i \
  -e 's|splitshotz/Vice/archive/refs/tags/v$pkgver|Tr3yWay996/Vice-clipping/archive/refs/heads/main|' \
  -e 's|Vice-$pkgver|Vice-clipping-main|g' PKGBUILD.fork
makepkg -p PKGBUILD.fork -Csi
```

Review the package sources before building and run makepkg as your normal user.
It installs the package through pacman, replacing the existing `vice-clipper`
package; do not install a second unmanaged copy with sudo pip. Dependencies that
are already installed remain managed by pacman. For a later fork update, use
`git pull --ff-only` and repeat the PKGBUILD copy, substitution and build steps.
Repository updates to the official package do not include these fork changes.

Finish or pause/stop recording deliberately before updating the running daemon.
Close the interface, then load the new Python code and UI:

```sh
systemctl --user restart vice.service
vice-app
```

The service restart interrupts active jobs; closing the interface alone does not.
Existing settings, recordings and sidecars are retained. Queue state is created
on first use. No global keyframe recording interval changes are needed.

## Results for this change

Validated in the implementation environment:

- Python: 909 tests run, 903 passed and 6 skipped for unavailable/opt-in platform
  facilities. Includes real FFmpeg trims, exports, process controls and recovery.
- React/Vitest: 62 tests passed.
- TypeScript, localization validation, Python compilation and production build:
  passed. The generated bundle was rebuilt through Vite.
- `tools/native-drag-smoke.py`: passed under Xvfb/X11 with QtWebEngine, including
  both a separate external receiver and an internal playlist drop.

The localization checker still reports pre-existing untranslated upstream copy:
59 missing keys each in French and German, and 113 in Brazilian Portuguese.
The frozen baseline allows those existing gaps only. The keyframe controls and
all copy added by this change are provided in all four shipped locales.
Vite retains its existing runtime font-path and single-bundle size warnings.
KDE Wayland and real gameplay/GPU contention require the desktop checks above.
