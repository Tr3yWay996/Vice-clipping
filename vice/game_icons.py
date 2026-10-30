"""Discord game icons for detected games.

Matches a game name against Discord's public detectable-games list, reads the
application's icon hash, and returns a CDN URL. Results are cached on disk.
Lookups run in a background thread, so callers get None until one finishes.
"""
import json
import logging
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

from . import __version__
from .runtime import actual_home_dir

log = logging.getLogger("vice")

_API = "https://discord.com/api/v10"
_LIST_TTL = 7 * 86400
_lock = threading.Lock()
_inflight: set[str] = set()


def cache_dir() -> Path:
    return actual_home_dir() / ".cache" / "vice"


def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": f"Vice/{__version__}"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.load(resp)


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        log.debug("Game icon cache %s unreadable: %s", path.name, exc)
        return default


def _save(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)
    except OSError as exc:
        log.debug("Could not write game icon cache %s: %s", path.name, exc)


def build_name_map(apps: list) -> dict:
    """Lowercased game name -> Discord application id. First entry wins."""
    names: dict = {}
    for app in apps or []:
        name = str(app.get("name", "")).strip().lower()
        if name and app.get("id") and name not in names:
            names[name] = app["id"]
    return names


def _name_map() -> dict:
    path = cache_dir() / "detectable.json"
    cached = _load(path, {})
    if cached.get("names") and cached.get("ts", 0) + _LIST_TTL > time.time():
        return cached["names"]
    try:
        apps = _fetch_json(f"{_API}/applications/detectable")
    except Exception as exc:
        log.debug("Could not fetch Discord's detectable games list: %s", exc)
        return cached.get("names", {})
    names = build_name_map(apps)
    _save(path, {"ts": time.time(), "names": names})
    return names


def _resolve(key: str) -> None:
    try:
        names = _name_map()
        if not names:
            log.debug("No detectable games list available, not caching %r", key)
            return
        app_id = names.get(key)
        url = ""
        if app_id:
            icon = _fetch_json(f"{_API}/applications/{app_id}/rpc").get("icon")
            if icon:
                url = f"https://cdn.discordapp.com/app-icons/{app_id}/{icon}.png"
    except Exception as exc:
        log.debug("Game icon lookup for %r failed, not caching: %s", key, exc)
        return
    with _lock:
        path = cache_dir() / "icons.json"
        icons = _load(path, {})
        icons[key] = url
        _save(path, icons)


def discord_icon_url(game: str) -> Optional[str]:
    """Cached icon URL for a game name, or None. Starts a lookup on a miss."""
    key = (game or "").strip().lower()
    if not key:
        return None
    icons = _load(cache_dir() / "icons.json", {})
    if key in icons:
        return icons[key] or None
    with _lock:
        if key in _inflight:
            return None
        _inflight.add(key)

    def run() -> None:
        try:
            _resolve(key)
        finally:
            with _lock:
                _inflight.discard(key)

    threading.Thread(target=run, daemon=True, name="vice-game-icon").start()
    return None


class ArtworkStore:
    """Validated local artwork, reused by Settings, playlists and Discord.

    Imports are canonical PNGs; API clients choose cached IDs, never paths/URLs.
    Online search downloads Discord's public catalog and filters it locally.
    """
    MAX_BYTES = 5 * 1024 * 1024

    def __init__(self, directory):
        self.directory = Path(directory)

    def asset_path(self, asset):
        import re
        if not re.fullmatch(r'[0-9a-f]{64}\.png', str(asset or '')):
            raise ValueError('artwork')
        return self.directory / asset

    def import_image(self, data: bytes, remote_url=None):
        import hashlib
        import subprocess
        import tempfile
        if not data or len(data) > self.MAX_BYTES or not (
            data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or
            (data.startswith(b'RIFF') and data[8:12] == b'WEBP')):
            raise ValueError('artwork')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.directory) as directory:
            source, output = Path(directory)/'input', Path(directory)/'output.png'
            source.write_bytes(data)
            try:
                probe = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                    '-select_streams', 'v:0', '-show_entries', 'stream=codec_name,width,height', '-of', 'json', str(source)],
                    capture_output=True, timeout=5, check=True)
                stream = json.loads(probe.stdout)['streams'][0]
                if stream['codec_name'] not in {'png','mjpeg','webp'} or not all(0 < stream[k] <= 4096 for k in ('width','height')):
                    raise ValueError('artwork')
                subprocess.run(['ffmpeg','-v','error','-threads','1','-filter_threads','1','-protocol_whitelist','file,pipe',
                    '-i',str(source),'-frames:v','1','-vf','scale=512:512:force_original_aspect_ratio=decrease',
                    '-map_metadata','-1','-threads','1','-y',str(output)],capture_output=True,check=True,timeout=8)
            except (subprocess.SubprocessError, OSError, KeyError, IndexError, json.JSONDecodeError) as exc:
                raise ValueError('artwork') from exc
            asset = hashlib.sha256(output.read_bytes()).hexdigest() + '.png'
            destination = self.asset_path(asset)
            if not destination.exists():
                output.replace(destination)
            if remote_url:
                _save(destination.with_suffix('.json'), {'remote_url':remote_url})
            return asset

    def remote_url(self, asset):
        if not asset:
            return None
        return _load(self.asset_path(asset).with_suffix('.json'), {}).get('remote_url')

    def search(self, query, online=False):
        if not online:
            return []
        query = str(query or '').strip().casefold()
        if len(query) < 3 or len(query) > 120:
            return []
        # No title, query or executable path is included in a remote request.
        names = _name_map()
        return [{'name':name, 'application_id':str(app_id)} for name, app_id in names.items()
                if query == name or all(word in name.split() for word in query.split())][:12]

    def prepare_discord(self, application_id, online=False):
        import re
        if not online or not re.fullmatch(r'\d{1,24}', str(application_id)):
            raise ValueError('online')
        # IDs must come from the public catalog, not arbitrary remote URLs.
        if str(application_id) not in {str(value) for value in _name_map().values()}:
            raise ValueError('artwork')
        info = _fetch_json(f'{_API}/applications/{application_id}/rpc')
        icon = info.get('icon', '')
        if not re.fullmatch(r'[a-zA-Z0-9_]{1,128}', str(icon)):
            raise ValueError('artwork')
        url = f'https://cdn.discordapp.com/app-icons/{application_id}/{icon}.png'
        request = urllib.request.Request(url, headers={'User-Agent':f'Vice/{__version__}'})
        with urllib.request.urlopen(request, timeout=8) as response:
            data = response.read(self.MAX_BYTES + 1)
        return self.import_image(data, url)

    def local_steam(self, app_id):
        from .active_window import _steam_roots
        if not str(app_id or '').isdigit():
            return None
        for root in _steam_roots():
            cache = root/'appcache/librarycache'
            candidates = [cache/f'{app_id}_icon.jpg', cache/f'{app_id}_header.jpg',
                          cache/f'{app_id}_library_600x900.jpg']
            folder = cache/str(app_id)
            if folder.is_dir():
                candidates += list(folder.glob('*icon*.jpg'))[:4] + list(folder.glob('*header*.jpg'))[:4]
            for path in candidates:
                try:
                    if path.is_file() and path.stat().st_size <= self.MAX_BYTES:
                        return self.import_image(path.read_bytes())
                except (OSError, ValueError):
                    continue
        return None
