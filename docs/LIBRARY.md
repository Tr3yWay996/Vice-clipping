# Media titles, selection and processing

Clip and screenshot titles use single-click editing in cards, Home collections,
playlists, viewers and Quick Trimmer. F2 uses the same field for a focused or
selected item. Enter confirms, Escape cancels and blur confirms. Clicking the
thumbnail or ordinary card background still opens the viewer outside selection
mode. Titles never start a file drag.

## Exact titles and filenames

Manual titles preserve case, spaces (including leading/trailing spaces), Unicode,
accents and punctuation. Renaming never runs the recorder's legacy slugifier.
The existing container extension is appended unchanged; renaming does not convert
media to another format. For example, a title ending in a period results in that
period followed by the existing extension.

For a legal Linux filename component, the physical file receives the exact title
plus its extension. A collision is reported and never overwrites another file.
For `/`, NUL, the special titles `.` / `..`, or a component exceeding the backing
filesystem's name limit, Vice keeps the exact display title in metadata and leaves
the physical filename unchanged. The rename notice and bulk preview explicitly
show this distinction. Display titles are limited to 4,096 UTF-8 bytes; malformed
Unicode and empty titles are rejected. Internal cache/sidecar names are bounded
independently so a legal long media name still works.

The private, atomic `~/.local/share/vice/library.json` index assigns persistent
media IDs. IDs survive Vice renames, replacement trims and Trash restores. A fresh
recording under a reused filename receives a new ID. Recording dates and bytes
are not rewritten by title changes. Keep this metadata file with a library backup
if display titles cannot be represented by the physical filenames. Invalid JSON
is preserved under an `.invalid-*` backup instead of blocking normal startup.

Content revision is a separate concept. It changes when media bytes change, and
continues to invalidate thumbnail, proxy, audio and keyframe caches even when a
trim preserves the historical filesystem modification time. A title-only change
keeps that revision and the local playback URL, so playback does not reload.
Current valid cache files are carried across physical renames. Original public
tokens, view counts, game IDs, custom/automatic playlist membership, highlights,
keyboard sidecars and editor references follow the shared rename operation.

Existing slug routes remain compatible. UUID-based local media routes keep player
identity independent of filenames. Names beginning with Vice's legacy internal
`img:` or `vid:` prefixes use a separate internal clip alias while preserving the
exact physical filename; they cannot be mistaken for screenshots in playlists.

## Select and organize

- **Select** enters selection mode. Cards then show checkboxes and selected borders.
- **Ctrl-click** (or Meta-click) toggles individual items. **Shift-click** extends a
  range within that gallery's current order, anchored by the previous selection.
- **Ctrl+A** selects the focused gallery's filtered results, including its current
  playlist scope. The explicit Select All control does the same.
- Deselect Filtered removes that gallery's visible results from the selection.
  Clear Selection or Escape leaves selection mode.
- Selection uses persistent IDs and stays available when filtering, changing
  library views, renaming or editing metadata. Trashing an item removes it from
  the current selection. Typing keeps native text-selection shortcuts.

The contextual toolbar offers:

- **Bulk rename:** literal text replacement, prefix, suffix, sequential numbering
  or patterns. Review exact resulting titles and physical filenames before Apply.
  Patterns accept `{title}`, `{index}`, `{index:03d}`, `{date}` and `{game}`; the
  date is the original recording date. Up to 1,000 items can be previewed together.
- **Add/remove playlist membership** or **move between playlists**. A move starts
  from a custom playlist and adds to the destination before removing membership
  from the source. These actions do not physically move recordings between folders.
- **Assign game** or remove a game association, using the existing recognized game
  identities. Automatic game playlists follow; custom playlists remain intact.
- **Move to Trash**, with a count/review confirmation, using the existing managed
  recoverable Trash. Permanent deletion is not a bulk gallery default.
- **Copy file paths**, copy video sharing links, or reveal the selected directories.
  Text copying retains the existing native/browser/manual clipboard fallbacks.

Bulk application reuses existing operations in chunks of 20, reports completed
and failed items separately, and can stop before the next chunk. A chunk already
sent to the daemon completes. Successful changes are retained; failures remain
selected for review. Rename plans are checked again before application so another
window's edit or a newly occupied destination cannot silently change the preview
or overwrite files. Physical file moves across folders/disks and bulk encoding
exports are intentionally outside this patch; use the existing per-export tools.

## Processing on cards

Home, All Clips and playlists read the same daemon job snapshot and WebSocket
updates as the existing processing panel. A job carries `source_media_ids` and a
mode such as replace, copy, export or share preparation. Cards never infer a job
association from its filename. Export jobs may refer to multiple source cards.

The card indicator shows queued/running/paused/failure state, known progress and
operation mode. Click it for the existing queue controls and error details.
Completion/cancellation notices disappear after five seconds; failures remain
available until removed or superseded. Reduced-motion preferences disable the
indeterminate animation. Reopening the interface restores indicators from the
backend snapshot without polling.

A physical rename is blocked while a queued/active job owns that source, or while
legacy untracked preparation needs the resource lock. A display-only title change
is safe during processing. The job's own final deferred rename remains supported.
Closing the GUI does not stop the daemon's queue, copy validation or re-encoding
fallback. Existing jobs are associated with IDs on startup only when their saved
content revision still matches; ambiguous history is not matched by filename.

## Events and compatibility

`clip_saved` / `image_saved` mean actual media creation. `clip_renamed` /
`image_renamed` atomically carry old slug plus updated media. `clip_updated` /
`image_updated` enrich metadata, replace trimmed bytes or restore existing media.
Only creation events add the new-recording badge or save notification. Renames
update cards in place and preserve date order. The viewer, trimmer and editor
follow identity updates without resetting playback, trim handles or unsaved edits.

Older playlist/game/editor stores still use compatible slug references; the shared
operation migrates these references while the media index supplies stable identity.
External filesystem moves are not a substitute for an in-app rename. If a disk is
offline, or a file is moved/overwritten outside Vice, reconnect/rescan and review
missing sources. Unchanged inode/content revisions are required to adopt a file
without an explicit Vice edit. No operation assumes that a reused filename means
the same recording.

## Validation and desktop limits

Regression tests cover exact/forbidden/maximum-length names, collisions, stable
IDs and URLs, cache/sidecar migration, timestamps, public tokens, game/playlist
membership, editor references, Trash restore, queue persistence/source mapping,
semantic events, modifier selection, scoped Select All, bulk previews, cancellation
between chunks and partial failures. Production Chromium also exercises the
French UI against aiohttp/FFmpeg, including a real background copy and GUI reopen.

KDE Plasma Wayland focus integration, native clipboard permissions and opening
Dolphin require checking on a real desktop. The implementation reuses Vice's
existing native clipboard and directory-reveal paths and does not change recorder,
GPU, keyframe interval, audio-track or export-encoding settings.
