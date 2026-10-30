# Recoverable Trash and title renaming

Delete now moves clips and screenshots into Vice's **Trash** (**Corbeille** in
French). Open Trash from the sidebar to restore individual items, restore all,
select multiple items, permanently delete a selection, or empty the bin.
Permanent deletion and Empty Trash require confirmation. These controls use
Vice's own bin, separate from the desktop file manager's trash.

Cards show the original filename, game, recording date, deletion date, size and
remaining retention time. Normal galleries and playlist listings exclude the
trashed media. The originals are moved, never re-encoded or recompressed.
Highlights, keyboard sidecars, view counts, game identity, thumbnails and playlist
membership are retained. Restore merges membership without undoing later edits
to the playlist's name or appearance; missing remembered playlists are recreated.

## Retention and storage

**Settings → Storage → Trash** offers 7, 14, 30 or 90 days, and **Never** for manual
deletion only. Existing configurations default to 30 days. The setting is stored
as `output.trash_retention_days`, with `0` meaning Never. Age starts when the item
enters Trash, independent of its original recording timestamp.

Cleanup runs at daemon startup, hourly while running, and after a policy change.
Closing or minimizing the interface does not stop it. Retention also runs when
the local sharing server is disabled. A shorter policy can make older entries
immediately eligible; the setting explains this before Save. Items are never
expired before the configured age, though cleanup can occur after that age.

The private journal is `~/.local/share/vice/trash.json`. Media and recoverable
sidecars live in `<original media folder>/.vice-trash/<entry ID>/`, so moving a
large recording into Trash uses a rename on its original filesystem. No central
cross-disk video copy is needed. Trash displays its total occupied size; sizes
for unavailable media use the last known value. Back up the journal and these
payload directories together if backing up deleted media is important.

The journal is atomically replaced with owner-only permissions and fsync. Its
operation states allow recovery after interruption before/after moving media or
publishing a restore. An incomplete move that never left the source rolls back
without detaching its metadata. An interrupted restore can finish metadata
publication after restart. Interrupted purges are retried. An unreadable journal
is preserved and disables Trash mutations while ordinary recording remains
available; it is never silently replaced or used for unrestricted deletion.

Only indexed entries, identified by opaque IDs, can be purged. Permanent deletion
unlinks known files inside their managed directory and removes that directory
only when empty. Symbolic links and unexpected contents produce an error;
there is no recursive deletion of client-supplied paths.

## Restoration and processing conflicts

Restore normally returns media to its original folder with its original filename
and nanosecond modification timestamp. Collisions use `name (restored 1).mp4`,
and subsequent numbers, without overwriting existing recordings or sidecars.
Publication also protects against a file appearing between the collision check
and the move. Restored items outside the currently configured library folder
remain indexed across restarts, including subsequent renames.

If the original destination cannot be used, each card offers **Other restore
location → Restore to current library folder**. This uses the configured clip or
screenshot folder. If it is on another disk, Vice copies the bytes once to a
staging file, preserves timestamps, and publishes it before removing the trash
copy. The original remains recoverable if copying fails or is interrupted.

Disconnected drives, inaccessible directories and externally moved/deleted
payloads cannot be reconstructed from metadata alone. Reconnect the storage and
refresh. Failed batch entries remain visible with per-item errors; successful
entries complete independently. Cleanup never follows an external move to delete
an unrelated file outside the managed entry.

Deletion is rejected while an encoder/export is using the media, or a queued or
paused job references it. Wait for that job or cancel it before deleting. File
publication and restoration share the existing processing resource lock.
Trash thumbnails are generated asynchronously on demand and are local-only.

## Public links and editor references

Moving a clip into Trash revokes its existing public token. Restore issues a
fresh token; old public links stay invalid after restoration. Tokens are not
reused just because the original filename becomes available again. The public
server exposes no Trash list, thumbnails, files or restore operations.

Editor items stay in their existing tracks with their timings intact. Their
source becomes a missing-media reference bearing the original name, so a new
recording with the old filename cannot substitute itself into the project.
Restore reconnects those references to the restored file, including after a
collision. Permanent deletion or retention expiry removes the retained source
references. When a project has unsaved timeline edits, source changes merge into
those edits and undo history rather than replacing the project. Stale autosaves
and exports are checked against active Trash references too.

## Single-click titles

Click the displayed name once in the Viewer or Quick Trimmer, or focus it and
press Enter/Space. The existing inline field selects the name. Enter confirms,
Escape cancels without closing the player, and blur retains the existing commit
behavior. The heading style is unchanged until editing; hover adds a subtle
underline.

Viewer renames retain playback position and playing/paused state when the new
media URL loads, without counting another view. Quick Trimmer renames stay
pending until the modal closes or saves, preserving its source, playback and
trim boundaries. Card-title and highlight double-click gestures are unchanged.

## Validation

Regression coverage is in `tests/test_trash.py`, the share-server/editor tests,
the Trash screen and store tests, and Viewer/TrimModal/editor-engine tests. Run
`python -m unittest discover -s tests`, `npm test`, `npm run typecheck`,
`npm run i18n:check`, and `npm run build`. The four supported locales include all
new controls and error messages. Existing recording, stream-copy/fallback trim,
keyframe, background-queue and sharing tests remain part of the full suite.
