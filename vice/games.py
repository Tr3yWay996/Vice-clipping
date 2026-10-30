"""Persistent local game identities, decisions and matching rules.

All consumers resolve here. Display names and artwork are attributes, never IDs.
No network requests are made by recognition or suggestion creation.
"""
from __future__ import annotations
import copy
import fnmatch
import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from .runtime import actual_home_dir

GAMES_PATH = actual_home_dir() / '.local/share/vice/games.json'
log = logging.getLogger('vice.games')
RULE_FIELDS = ('executables', 'paths', 'classes', 'steam_ids', 'titles')
_GENERIC = {'wine', 'wine64', 'wine-preloader', 'wine64-preloader', 'proton', 'steam', 'steamwebhelper',
            'java', 'javaw.exe', 'python', 'python3', 'sh', 'bash', 'explorer.exe', 'services.exe',
            'winedevice.exe', 'rundll32.exe', 'launcher.exe', 'gamescope', '#32770'}
_NON_GAMES = {'firefox', 'chrome', 'chromium', 'discord', 'code', 'code-oss', 'obs', 'obs-studio',
              'dolphin', 'konsole', 'kitty', 'alacritty', 'gnome-terminal', 'vice', 'vice-app',
              'lutris', 'heroic', 'bottles', 'systemsettings', 'plasmashell', 'kwin_wayland'}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def leaf(value):
    return str(value or '').replace('\\', '/').rsplit('/', 1)[-1].casefold()


def normalized_path(value):
    path = str(value or '').replace('\\', '/')
    return path.casefold() if re.match(r'^[A-Za-z]:/', path) else path


def meaningful(value):
    name = leaf(value)
    return len(name) >= 3 and name not in _GENERIC and name.removesuffix('.exe') not in _NON_GAMES


def display_name(game):
    return game.get('name_override') or game.get('confirmed_name') or game['automatic_name']


@lru_cache(maxsize=4096)
def signature_pattern(value):
    return re.compile(r'(?<![a-z0-9])' + re.escape(value) + r'(?![a-z0-9])')


def best_game_match(entries, haystacks):
    """Prefer specific bundled signatures, with identifier boundaries."""
    best, length = None, 0
    for name, matches in entries:
        for needle in matches or []:
            n = str(needle or '').casefold()
            if len(n) > length and any(signature_pattern(n).search(h) for h in haystacks):
                best, length = name, len(n)
    return best


class GameLibrary:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else GAMES_PATH
        self.lock = threading.RLock()
        self.on_change = None
        self.entries = []
        self.clips = {}
        self.forgotten = set()
        self.revision = 0
        self.bundled = json.loads((files('vice')/'data/games.json').read_text())
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if not isinstance(data, dict) or data.get('version') != 1:
                    raise ValueError('Unsupported game library version')
                entries, clips = data.get('games', []), data.get('clips', {})
                if not isinstance(entries, list) or not isinstance(clips, dict):
                    raise ValueError('Invalid game library')
                for game in entries:
                    if not isinstance(game, dict) or not all(key in game for key in ('id','automatic_name','status','rules')):
                        raise ValueError('Invalid game entry')
                    if any(not isinstance(game['rules'].get(field), list) for field in RULE_FIELDS):
                        raise ValueError('Invalid game rules')
                self.entries, self.clips = entries, clips
                self.forgotten = set(data.get('forgotten', []))
            except (ValueError, TypeError, AttributeError) as exc:
                # Keep the original for recovery instead of letting an edited
                # or damaged metadata file prevent recording from starting.
                backup = self.path.with_name(f'{self.path.name}.invalid-{time.time_ns()}')
                self.path.replace(backup)
                log.error('Game library could not be loaded (%s); preserved at %s', exc, backup)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.json.tmp')
        fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'version':1, 'games':self.entries, 'clips':self.clips, 'forgotten':sorted(self.forgotten)}, stream, ensure_ascii=False)
            stream.flush(); os.fsync(stream.fileno())
        tmp.replace(self.path)
        self.revision += 1
        if self.on_change:
            self.on_change()

    def get(self, gid):
        return next((game for game in self.entries if game['id'] == gid), None)

    def by_name(self, name):
        folded = str(name or '').casefold()
        return next((g for g in self.entries if g['status'] != 'removed' and folded in {display_name(g).casefold(), g['automatic_name'].casefold(),
                                                         *[n.casefold() for n in g.get('aliases', [])]}), None)

    def by_automatic_name(self, name):
        key = str(name or '').casefold()
        return next((game for game in self.entries if game['automatic_name'].casefold() == key and game['status'] != 'removed'), None)

    def snapshot(self):
        with self.lock:
            return [dict(copy.deepcopy(g), name=display_name(g), steam_app_id=next(iter(g['rules']['steam_ids']), None),
                         clip_count=sum(gid == g['id'] for gid in self.clips.values())) for g in self.entries if g['status'] != 'removed']

    def _new(self, name, source, rules=None, status='recognized', seed=None):
        gid = 'game-' + hashlib.sha256(str(seed or (source + ':' + name.casefold())).encode()).hexdigest()[:24]
        game = self.get(gid)
        if game:
            return game
        game = dict(id=gid, automatic_name=name, name_override=None, confirmed_name=None,
                    artwork_override=None, automatic_artwork=None, source=source, status=status,
                    user_rules=source == 'manual', rules={field:list((rules or {}).get(field, [])) for field in RULE_FIELDS},
                    aliases=[], created_at=timestamp(), last_detected=None)
        self.entries.append(game)
        return game

    def import_legacy(self, custom):
        with self.lock:
            changed = False
            for entry in custom:
                if not entry.name.strip():
                    continue
                existing = self.by_automatic_name(entry.name)
                # Config-file aliases remain compatible until this identity
                # is explicitly edited in Detected Games.
                if existing:
                    if existing['source'] == 'custom' and not existing.get('user_rules') and existing.get('legacy_matches') != list(entry.matches):
                        aliases = [value for value in entry.matches if meaningful(value)]
                        existing['rules'] = {field:aliases[:] if field in {'executables','classes'} else [] for field in RULE_FIELDS}
                        existing['legacy_matches'] = list(entry.matches)
                        changed = True
                    continue
                if any(g['automatic_name'].casefold() == entry.name.casefold() for g in self.entries):
                    continue  # A removed/rejected identity is still a decision.
                aliases = [value for value in entry.matches if meaningful(value)]
                game = self._new(entry.name, 'custom', {'executables':aliases, 'classes':aliases})
                game['legacy_matches'] = list(entry.matches)
                changed = True
            if changed:
                self.save()

    def ensure_name(self, name):
        with self.lock:
            game = self.by_name(name)
            if not game:
                known = next((entry for entry in self.bundled if entry['name'].casefold() == name.casefold()), None)
                rules = {'executables':[value for value in known['matches'] if meaningful(value)]} if known else {}
                game = self._new(name, 'builtin' if known else 'legacy', rules)
                self.save()
            return game

    @staticmethod
    def identity(win):
        from .active_window import process_identity, read_steam_app_id
        identity = {**win, **process_identity(win.get('pid'))}
        proc = identity.get('process', '')
        exe = identity.get('executable') or proc
        sid = str(identity.get('steam_app_id') or read_steam_app_id(win.get('pid')) or '')
        if not sid:
            match = re.fullmatch(r'steam_app_(\d+)', str(win.get('class', '')).casefold())
            sid = match.group(1) if match else ''
        return dict(process=proc.casefold(), executable=leaf(exe), path=normalized_path(identity.get('executable_path')),
                    cls=str(win.get('class') or '').casefold(), steam_id=sid,
                    title=str(win.get('title') or '').strip()[:200])

    @staticmethod
    def _rules_match(rules, identity):
        sid = identity['steam_id']
        if sid and rules['steam_ids'] and sid not in rules['steam_ids']:
            return 0  # Shared Source/Wine binaries must not swallow another Steam game.
        values = [('steam_ids', sid, 1000), ('paths', identity['path'], 900),
                  ('executables', identity['executable'], 800), ('classes', identity['cls'], 700)]
        score = max((weight for field, value, weight in values if value and value in
                     [(normalized_path(x) if field == 'paths' else x.casefold()) for x in rules[field]]), default=0)
        if not score and identity['title']:
            if any(fnmatch.fnmatchcase(identity['title'].casefold(), pattern.casefold()) for pattern in rules['titles']):
                score = 500
        return score

    @classmethod
    def _entry_match(cls, game, identity):
        score = cls._rules_match(game['rules'], identity)
        sid = identity['steam_id']
        if sid and game['rules']['steam_ids'] and sid not in game['rules']['steam_ids']:
            return 0
        values = (identity['process'], identity['executable'], identity['cls'])
        for raw in game.get('legacy_matches', []):
            needle = str(raw).casefold()
            if re.fullmatch(r'steam_app_\d+', needle):
                matched = needle == f'steam_app_{sid}'
            else:
                matched = needle and any(needle in value for value in values)
            if matched:
                score = max(score, len(needle))
        return score

    def resolve(self, win, custom=(), *, suggestions=True, bundled=None, steam_name=None):
        from .active_window import steam_game_name
        identity = self.identity(win)
        if not identity['title'] and any(g.get('user_rules') and g['rules']['titles'] for g in self.entries):
            from .active_window import window_title
            identity['title'] = window_title(win)
        with self.lock:
            matches = [(self._entry_match(g, identity), g) for g in self.entries
                       if g.get('user_rules') or g['status'] in {'rejected', 'deferred', 'removed'}]
            matches = [(score, game) for score, game in matches if score]
            if matches:
                live = [(score, game) for score, game in matches if game['status'] != 'removed']
                matches = live or matches
                score, game = max(matches, key=lambda pair: pair[0])
                if sum(s == score for s, _ in matches) > 1:
                    return None  # Ambiguous custom rules never silently choose a game.
                if game['status'] in {'rejected', 'deferred', 'pending', 'removed'}:
                    return None
                self._seen(game)
                return copy.deepcopy(game)
            haystacks = tuple(s for s in (identity['process'], identity['executable'], identity['cls']) if s)
            if identity['steam_id']:
                haystacks += (f"steam_app_{identity['steam_id']}",)
            # Legacy custom entries remain explicit user intent; one resolver
            # imports their identity without maintaining a second matching path.
            allowed = lambda name: not ((existing := self.by_automatic_name(name)) and existing.get('user_rules'))
            candidates = [(len(str(needle)), game.name) for game in custom if allowed(game.name)
                          for needle in game.matches if needle and any(str(needle).casefold() in h for h in haystacks)]
            name = max(candidates, default=(0,None), key=lambda pair:pair[0])[1]
            source = 'custom'
            if not name and identity['steam_id']:
                name = (steam_name or steam_game_name)(identity['steam_id'])
                if name and not allowed(name):
                    name = None
                source = 'steam'
            if not name:
                name = best_game_match([(g['name'], g.get('matches')) for g in (self.bundled if bundled is None else bundled) if allowed(g['name'])], haystacks)
                source = 'builtin'
            if name:
                sid = identity['steam_id']
                game = next((g for g in self.entries if sid and sid in g['rules']['steam_ids'] and g['status'] != 'removed'), None)
                if not game:
                    game = self.by_automatic_name(name)
                    if source == 'steam' and game and game['rules']['steam_ids'] and sid not in game['rules']['steam_ids']:
                        game = None  # Different Steam applications may have identical titles.
                if not game:
                    game = self._new(name, source, self._observed_rules(identity), seed=f'steam:{sid}' if source == 'steam' else None)
                if game['status'] not in {'recognized', 'confirmed'}:
                    return None
                if source == 'steam':
                    game['automatic_name'] = name
                    game['source'] = source
                self._seen(game)
                return copy.deepcopy(game)
            if suggestions:
                self._suggest(identity, win)
            return None

    def _seen(self, game):
        previous = game.get('_seen_clock', 0)
        if not game.get('last_detected') or time.time() - previous >= 60:
            game['last_detected'] = timestamp()
            game['_seen_clock'] = time.time()
            self.save()

    @staticmethod
    def _observed_rules(identity):
        return dict(executables=[identity['executable']] if meaningful(identity['executable']) else [],
                    paths=[identity['path']] if identity['path'] and meaningful(identity['executable']) else [],
                    classes=[identity['cls']] if meaningful(identity['cls']) and not identity['cls'].isdigit() else [],
                    steam_ids=[identity['steam_id']] if identity['steam_id'] else [], titles=[])

    def _suggest(self, identity, window):
        executable = identity['executable']
        if executable.removesuffix('.exe') in _NON_GAMES or identity['cls'] in _NON_GAMES:
            return
        plausible = identity['steam_id'] or executable.endswith('.exe') or any(
            token in identity['path'] + ' ' + identity['cls'] + ' ' + executable for token in ('/games/', '/steamapps/common/', 'game'))
        if not plausible or not meaningful(executable or identity['cls']):
            return
        rules = self._observed_rules(identity)
        fingerprint = json.dumps(rules, sort_keys=True)
        if fingerprint in self.forgotten:
            return
        existing = next((g for g in self.entries if self._rules_match(g['rules'], identity)), None)
        if existing:
            return
        title = re.sub(r'\.(exe|bin|x86_64)$', '', executable, flags=re.I) or identity['cls']
        title = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', title).replace('_', ' ').strip()
        from .active_window import window_title
        caption = identity['title'] or window_title(window)
        if 3 <= len(caption) <= 100 and not any(c in caption for c in ('/', '\\', '\n')) and caption.casefold() not in {'untitled','unknown','wine','launcher'}:
            title = caption
        game = self._new(title or 'Game', 'process', rules, 'pending', fingerprint)
        game['last_detected'] = timestamp()
        self.save()

    def _validate_rules(self, gid, raw, ignore=None):
        if not isinstance(raw, dict):
            raise ValueError('rules')
        result = {}
        for field in RULE_FIELDS:
            values = raw.get(field, [])
            if not isinstance(values, list) or len(values) > 40:
                raise ValueError('rules')
            values = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
            if any(len(value) > 512 for value in values):
                raise ValueError('rules')
            if field == 'steam_ids' and any(not re.fullmatch(r'[1-9]\d{0,11}', v) for v in values):
                raise ValueError('steam')
            if field in {'executables', 'classes'} and any(not meaningful(v) for v in values):
                raise ValueError('generic')
            if field == 'titles' and any(len(re.sub(r'[^\w]', '', v)) < 5 or len(v) > 160 or v.count('*') > 2 or '[' in v or '?' in v for v in values):
                raise ValueError('title')
            result[field] = values
        for game in self.entries:
            if game['id'] in {gid, ignore} or game['status'] == 'removed':
                continue
            if result['steam_ids'] and game['rules']['steam_ids'] and not set(result['steam_ids']) & set(game['rules']['steam_ids']):
                continue
            if any(set(normalized_path(v) if field == 'paths' else v.casefold() for v in result[field]) &
                   set(normalized_path(v) if field == 'paths' else v.casefold() for v in game['rules'][field]) for field in RULE_FIELDS):
                raise ValueError('conflict')
        if gid is None and not any(result.values()):
            raise ValueError('rules')
        return result

    def edit(self, gid, fields):
        with self.lock:
            game = self.get(gid)
            if not game:
                raise KeyError(gid)
            changed = copy.deepcopy(game)
            if fields.get('reset_name'):
                changed['name_override'] = changed['confirmed_name'] = None
            elif 'name' in fields:
                name = str(fields['name']).strip()
                if not name or len(name) > 120 or any(ord(c) < 32 for c in name):
                    raise ValueError('name')
                changed['aliases'] = list(dict.fromkeys([*changed['aliases'], display_name(game)]))
                changed['name_override'] = name
                changed['user_rules'] = True
            if 'rules' in fields:
                changed['rules'] = self._validate_rules(gid, fields['rules'])
                if changed['rules'] != game['rules']:
                    changed.pop('legacy_matches', None)
                changed['user_rules'] = True
            if 'artwork_override' in fields:
                from .game_icons import ArtworkStore
                asset = fields['artwork_override']
                if asset is not None and not ArtworkStore(self.path.parent/'game-artwork').asset_path(asset).is_file():
                    raise ValueError('artwork')
                changed['artwork_override'] = asset
            if fields.get('confirm') and game['status'] in {'pending', 'deferred'}:
                changed.update(status='confirmed', user_rules=True, confirmed_name=display_name(changed))
            game.clear()
            game.update(changed)
            self.save()
            return copy.deepcopy(game)

    def create(self, fields):
        with self.lock:
            name = str(fields.get('name') or '').strip()
            if not name or len(name) > 120 or any(ord(c) < 32 for c in name):
                raise ValueError('name')
            if self.by_name(name):
                raise ValueError('conflict')
            rules = self._validate_rules(None, fields.get('rules', {}))
            artwork = fields.get('artwork_override')
            if artwork is not None:
                from .game_icons import ArtworkStore
                if not ArtworkStore(self.path.parent/'game-artwork').asset_path(artwork).is_file():
                    raise ValueError('artwork')
            game = self._new(name, 'manual', rules, 'confirmed')
            game.update(rules=rules, source='manual', user_rules=True)
            game['artwork_override'] = artwork
            game['name_override'] = name
            game['status'] = 'confirmed'
            game['confirmed_name'] = name
            self.save()
            return copy.deepcopy(game)

    def action(self, gid, action, target=None):
        with self.lock:
            game = self.get(gid)
            if not game:
                raise KeyError(gid)
            if action == 'confirm':
                game.update(status='confirmed', user_rules=True, confirmed_name=display_name(game))
            elif action in {'reject', 'later', 'enable'}:
                game['status'] = {'reject':'rejected', 'later':'deferred', 'enable':'confirmed'}[action]
                game['user_rules'] = True
            elif action == 'reset-name':
                game['name_override'] = game['confirmed_name'] = None
            elif action == 'reset-artwork':
                game['artwork_override'] = None
            elif action == 'remove':
                self.forgotten.add(json.dumps(game['rules'], sort_keys=True))
                game['status'] = 'removed'
                game['user_rules'] = True
                # Existing classifications stay as historical metadata until
                # explicitly reclassified; a removal never deletes a clip.
            elif action == 'merge':
                destination = self.get(target)
                if not destination or destination is game:
                    raise ValueError('target')
                combined = {field:list(dict.fromkeys(destination['rules'][field] + game['rules'][field])) for field in RULE_FIELDS}
                combined = self._validate_rules(target, combined, ignore=gid)
                destination['rules'] = combined
                destination['legacy_matches'] = list(dict.fromkeys(destination.get('legacy_matches', []) + game.get('legacy_matches', [])))
                if not destination.get('artwork_override') and game.get('artwork_override'):
                    destination['artwork_override'] = game['artwork_override']
                destination['aliases'] = list(dict.fromkeys(destination['aliases'] + game['aliases'] + [display_name(game)]))
                destination.update(status='confirmed', user_rules=True)
                self.clips = {slug:target if identity == gid else identity for slug, identity in self.clips.items()}
                self.entries.remove(game)
            else:
                raise ValueError('action')
            self.save()

    def associate(self, slug, gid):
        self.associate_many([slug], gid)

    def associate_many(self, slugs, gid):
        with self.lock:
            changed = {slug:gid for slug in slugs if self.clips.get(slug) != gid}
            if self.get(gid) and changed:
                self.clips.update(changed)
                self.save()

    def game_for(self, slug):
        with self.lock:
            game = self.get(self.clips.get(slug))
            return display_name(game) if game else None

    def rename_clip(self, old, new):
        with self.lock:
            if old in self.clips:
                self.clips[new] = self.clips.pop(old)
                self.save()

    def delete_clip(self, slug):
        with self.lock:
            if self.clips.pop(slug, None):
                self.save()
