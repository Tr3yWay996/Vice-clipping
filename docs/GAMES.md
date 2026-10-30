# Detected Games

Open **Settings → Detected Games** (**Réglages → Jeux détectés** in French).
The list contains games actually recognized on this machine, imported automatic
playlists and custom rules, and plausible applications awaiting a decision. It
does not list every entry in the bundled catalog.

Unknown applications are suggestions, never automatic filename tags or Discord
activities. Confirm a suggestion, correct its name, choose an existing identity
and merge into it, mark it as not a game, or ask later. Decisions survive daemon
restarts and Vice updates. The homepage shows a passive pending count; Vice never
opens a confirmation over gameplay. Turning suggestions off stops new candidates
without disabling existing recognition.

Each game has a stable ID independent of its display name. Open its editor to
change the name, preview/import artwork, edit rules, restore automatic metadata,
or re-enable a rejected application. Save game applies immediately; the general
Settings save button is not needed for game edits. Remove, merge and historical
reclassification require confirmation. Removing an identity hides it and stops
recognition while retaining historical clip labels. It can be added again with
explicit rules. Ask later keeps the candidate in the pending filter without
repeated homepage prompts.

## Recognition and rules

All clip tags, screenshots, session associations and Discord presence use
`GameLibrary` in `vice/games.py`. Resolution is offline, in this order:

1. Explicit/confirmed rules, including saved rejection and deferral decisions.
2. Legacy custom rules imported from `discord.custom_games`.
3. Steam App IDs and local Steam manifests, including Flatpak Steam libraries.
4. Specific, bounded signatures from the existing bundled catalog.
5. Full executable/process paths and window/application classes as evidence for
   an unconfirmed candidate. A safe local window title can suggest its name.

Linux's truncated `/proc/PID/comm` is supplemented by `/proc/PID/exe`. Wine/Proton
command lines recover the Windows executable. Existing X11, Hyprland, sway, Niri
and KDE adapters remain in use; KDE Wayland needs `kdotool`. If the compositor or
process permissions hide an identity, users can add an appropriate explicit rule.
Suggestions deliberately favor false negatives over labeling ordinary desktop
applications as games. There is no universal offline classifier for every native
executable.

Rules are alternatives, one identifier per line. Executable basenames and classes
match exactly, ignoring case. Linux paths are exact and case sensitive; Windows
paths normalize separators and case. Steam IDs match exactly and distinguish games
that share a binary. Conflicting identifiers produce an error; merge duplicate
identities or correct the conflicting rule. Generic launchers such as `wine` or
`steam` cannot be used alone as game aliases. Explicit title patterns must be
specific, allow at most two `*` wildcards, and never replace process evidence by
default. Clearing all rules on an existing identity preserves its historical
metadata but disables those recognition matches.

User names and artwork always take priority. Resetting a name or image opts back
into automatic metadata; ordinary catalog updates never clear an override.

## Artwork and privacy

Steam library-cache images work offline. Local imports accept PNG, JPEG and WebP,
up to 5 MiB and 4096 × 4096 pixels. FFprobe validates the actual image, then FFmpeg
creates a metadata-free PNG no larger than 512 × 512. Previewing an upload does
not apply it until Save game. Images are content addressed and retained locally.

Online lookup is off by default. Enabling it permits background exact-name
matching and explicit alternative-artwork searches against Discord's public
detectable-game catalog. The catalog is downloaded and searched locally: queries,
window titles and executable paths are never sent. Only public application IDs
and fixed Discord API/CDN URLs are fetched. Ambiguous search results require an
explicit selection. Failed requests leave recognition and cached images usable.
Online metadata never determines a game's stable identity.

Discord Rich Presence can use the public URL attached to selected cached Discord
artwork. Custom local images and Steam cache images stay local; presence uses the
Vice logo when no compatible public asset exists. Nothing uploads custom artwork
to Discord. Browser artwork is served only by the local control server, never by
the public clip-sharing server.

## Storage, compatibility and synchronization

`~/.local/share/vice/games.json` stores versioned identities, decisions, rules,
overrides and clip associations with owner-only permissions, fsync and atomic
replacement. `game-artwork/` alongside it contains validated PNGs and public-source
metadata. Back up both to retain learned identities and custom images. A malformed
registry is preserved as `games.json.invalid-<timestamp>` for recovery; it does
not prevent recording from starting.

Existing `playlists.json` remains authoritative for playlist membership. Legacy
automatic playlists acquire a game ID without changing playlist IDs, custom
playlists or filenames. Existing config-file custom rules remain compatible;
Detected Games replaces the old Discord-only textarea and explicit library edits
take priority over later config/catalog changes. Rename updates logical game
labels. Reclassify explicitly binds already-associated historical clips to the
identity; merge combines identity rules and automatic memberships. These
operations never rewrite media, recording timestamps, sidecars, thumbnails,
keyframe caches or share tokens.

Background discovery checks the active application every five seconds even when
Discord presence is disabled. Signature regexes are cached, detection timestamps
write at most once a minute per game, historical reclassification saves in a
batch, and image probing/downloading runs off the HTTP event loop. Settings lists
render 30 entries at a time. The existing WebSocket carries complete
`games_changed` snapshots; REST reconciles startup, reconnection, focus, online and
visibility recovery. Older HTTP responses cannot overwrite newer events. There
is no frontend polling.

Regression tests live in `tests/test_games.py`, the existing Steam/Discord tests,
`ui-src/components/settings/DetectedGames.test.tsx` and the store tests. Run
`python -m unittest discover -s tests`, `npm test`, `npm run typecheck`,
`npm run i18n:check` and `npm run build`. FFmpeg/FFprobe enable real artwork and
media checks; hardware/compositor behavior and actual Discord rendering still
need a Linux desktop with the corresponding services running.


## Assign older recordings explicitly

Open **Settings → Detected Games**, open the recognized game, then choose
**Assign recordings to this game**. Select individual clips/screenshots (the
list initially shows only untagged recordings), review their names and the
chosen game, and confirm. Clear the filter to correct an existing assignment.
Up to 1,000 selected recordings can be applied in a batch. Nothing is guessed
from an image or from all untagged recordings.

This changes persistent game IDs and automatic playlist membership only. Custom
playlists, media bytes, historical timestamps, filenames, public tokens,
thumbnails, highlights, sidecars and editor source references stay intact.
Auto playlists are created only when the existing auto-playlist option is on.

Executable rules also check the process comm when Wine exposes a generic loader.
An exact 15-byte Linux comm truncation can match a longer rule when the full
executable is unavailable; an ambiguous match remains unclassified. Full
executable paths, Steam IDs and user overrides retain their existing priority.
KDE's XWayland visible-window fallback preserves dotted Wine classes instead of
reducing `RocketLeague.exe` to `exe`. Detection remains independent of Discord.
Recording diagnostics include the compositor adapter, process/class, match,
visible-window candidate count and (at debug level) stable game ID. Empty window
metadata still cannot reliably identify a game; no match is safer than attaching
a browser or launcher to Rocket League.
