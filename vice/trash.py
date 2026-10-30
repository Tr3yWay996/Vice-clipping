"""Recoverable same-filesystem media moves with a durable operation journal.

The index is private daemon state. Clients only ever choose an opaque entry ID.
Every destructive filesystem operation is restricted to an indexed .vice-trash
entry; original paths are used only as restore destinations, never purge targets.
"""
from __future__ import annotations

import copy
import ctypes
import errno
import json
import logging
import math
import os
import re
import shutil
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .runtime import actual_home_dir

TRASH_PATH = actual_home_dir() / '.local/share/vice/trash.json'
RETENTION_DAYS = {0, 7, 14, 30, 90}
log = logging.getLogger(__name__)
FILES = {'keys.json', 'highlights.json', 'thumbnail.jpg'}


class TrashError(ValueError):
    pass


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)
    sync_directory(path.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def identity(path):
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def move_exclusive(source, target):
    """Atomic publication without overwriting a racing external recording."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is not None:
        result = rename(-100, os.fsencode(source), -100, os.fsencode(target), 1)
        if result == 0:
            return
        error = ctypes.get_errno()
        if error not in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
            raise OSError(error, os.strerror(error), str(target))
    # Fallback preserves no-overwrite semantics and is restart recoverable if
    # interrupted between creating the hard link and removing the old one.
    os.link(source, target)
    source.unlink()


class TrashStore:
    def __init__(self, path=None, clock=time.time_ns):
        self.path = Path(path) if path is not None else TRASH_PATH
        self.clock = clock
        self.entries = {}
        self.restored_paths = {}
        self.error = None
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                if data.get('version') != 1 or not isinstance(data.get('entries'), dict):
                    raise ValueError('Unsupported trash index')
                self.entries = data['entries']
                self.restored_paths = data.get('restored_paths', {})
                if not isinstance(self.restored_paths, dict) or any(not Path(path).is_absolute() or kind not in {'clip','image'} for path, kind in self.restored_paths.items()):
                    raise ValueError('Invalid restored locations')
                for tid, entry in self.entries.items():
                    if tid != entry['id'] or entry['kind'] not in {'clip','image'} or not isinstance(entry['metadata'], dict):
                        raise ValueError('Invalid trash entry')
                    if any(type(entry[field]) is not int for field in ('deleted_at_ns','mtime_ns','size')):
                        raise ValueError('Invalid trash timestamps')
                    self.directory(entry)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            # Never replace a damaged index or delete unindexed files. Recording
            # still works; trash operations report the recoverable storage error.
            self.error = 'index'
            self.entries = {}
            self.restored_paths = {}
            log.error('Trash index %s needs recovery: %s', self.path, exc)

    def save(self):
        if self.error:
            raise TrashError(self.error)
        atomic_json(self.path, {'version': 1, 'entries': self.entries, 'restored_paths': self.restored_paths})

    def get(self, tid):
        entry = self.entries.get(tid)
        if not entry:
            raise TrashError('missing')
        return entry

    def directory(self, entry):
        tid, name = entry['id'], entry['name']
        if not re.fullmatch(r'[0-9a-f]{32}', tid) or name != Path(name).name or name in {'', '.', '..'}:
            raise TrashError('unsafe')
        root = Path(entry['original_dir']) / '.vice-trash'
        folder = root / tid
        if not root.is_absolute() or root.resolve() != root or root.is_symlink() or folder.is_symlink():
            raise TrashError('unsafe')
        return folder

    def media(self, entry):
        path = self.directory(entry) / entry['name']
        if path.is_symlink():
            raise TrashError('unsafe')
        return path

    def attachment(self, entry, name):
        if name not in FILES:
            raise TrashError('unsafe')
        path = self.directory(entry) / name
        if path.is_symlink():
            raise TrashError('unsafe')
        return path

    def move(self, source, kind, metadata, attachments=None):
        if self.error:
            raise TrashError(self.error)
        if source.is_symlink() or not stat.S_ISREG(source.stat().st_mode):
            raise TrashError('unsafe')
        source = source.parent.resolve() / source.name
        info = source.stat()
        entry = dict(id=uuid.uuid4().hex, name=source.name, kind=kind,
                     original_dir=str(source.parent), slug=source.stem,
                     deleted_at_ns=self.clock(), mtime_ns=info.st_mtime_ns,
                     size=info.st_size, identity=identity(source),
                     state='moving', metadata=copy.deepcopy(metadata))
        folder = self.directory(entry)
        folder.parent.mkdir(mode=0o700, exist_ok=True)
        folder.mkdir(mode=0o700)
        try:
            for name, path in (attachments or {}).items():
                if path.is_file() and not path.is_symlink():
                    destination = self.attachment(entry, name)
                    shutil.copy2(path, destination)
                    with destination.open('rb') as stream:
                        os.fsync(stream.fileno())
            sync_directory(folder)
            sync_directory(folder.parent)
            sync_directory(source.parent)
            self.entries[entry['id']] = entry
            self.save()  # Journal before moving the only copy of the media.
            source.rename(self.media(entry))
            sync_directory(source.parent)
            sync_directory(folder)
        except Exception:
            if source.exists() and not self.media(entry).exists():
                self.entries.pop(entry['id'], None)
                self.save()
                self._remove_files(entry)
            raise
        return entry

    def commit(self, entry):
        entry['state'] = 'trashed'
        self.save()

    def snapshot(self, days=30):
        days = days if type(days) is int and days in RETENTION_DAYS else 30
        now = self.clock()
        result = []
        for entry in self.entries.values():
            available = False
            size = entry['size']
            try:
                media = self.media(entry)
                available = media.is_file()
                if available:
                    size = sum(p.stat().st_size for p in [media, *[self.attachment(entry, name) for name in FILES]] if p.is_file())
            except (OSError, TrashError):
                pass
            expiry = entry['deleted_at_ns'] + days * 86400 * 10**9 if days else None
            result.append(dict(id=entry['id'], name=entry['name'], kind=entry['kind'], size=size,
                               original_dir=entry['original_dir'], source_slug=entry['slug'], media_id=entry['metadata'].get('media_id'),
                               game=entry['metadata'].get('game'), game_id=entry['metadata'].get('game_id'),
                               created_at=datetime.fromtimestamp(entry['mtime_ns']/1e9, timezone.utc).isoformat(),
                               deleted_at=datetime.fromtimestamp(entry['deleted_at_ns']/1e9, timezone.utc).isoformat(),
                               remaining_seconds=max(0, math.ceil((expiry-now)/1e9)) if expiry else None,
                               available=available, state=entry['state'],
                               thumbnail_url=f"/api/trash/{entry['id']}/thumbnail" if available else None))
        return sorted(result, key=lambda entry: entry['deleted_at'], reverse=True)

    def expired(self, days):
        if type(days) is not int or days not in RETENTION_DAYS or days == 0:
            return []
        return [entry['id'] for entry in self.entries.values() if entry['state'] == 'trashed'
                and self.clock()-entry['deleted_at_ns'] >= days*86400*10**9]

    def cleanup_candidates(self, days):
        return list(dict.fromkeys([*self.expired(days), *[entry['id'] for entry in self.entries.values() if entry['state'] in {'deleting','restored'}]]))

    def cleanup_staging(self, entry):
        if entry.get('restore_target'):
            temporary = Path(entry['restore_target']).parent / f".vice-restore-{entry['id']}.tmp"
            if temporary.is_symlink() or temporary.parent.resolve() != temporary.parent:
                raise TrashError('unsafe')
            temporary.unlink(missing_ok=True)

    def restore_file(self, entry, destination=None, reserved=(), stop=None):
        """Return a safely published path; metadata is restored by the caller."""
        media = self.media(entry)
        if entry['state'] == 'restoring':
            target = Path(entry['restore_target'])
            if target.is_file() and not target.is_symlink() and identity(target) == entry['restore_identity']:
                return target  # Publication succeeded before a crash.
        if not media.is_file():
            raise TrashError('unavailable')
        dest = (Path(destination) if destination is not None else Path(entry['original_dir'])).resolve()
        if not dest.is_dir():
            raise TrashError('destination')
        original = Path(entry['name'])
        for number in range(10000):
            name = original.name if number == 0 else f'{original.stem} (restored {number}){original.suffix}'
            target = dest / name
            if target.stem in reserved or target.exists() or target.is_symlink():
                continue
            entry.update(state='restoring', restore_target=str(target), restore_identity=entry['identity'])
            self.save()
            try:
                move_exclusive(media, target)
            except FileExistsError:
                continue
            except OSError as exc:
                if exc.errno != errno.EXDEV or destination is None:
                    raise
                # Cross-disk restore is explicit. Copy once to a private staging
                # file, fsync it, then publish without overwriting any target.
                temporary = dest / f".vice-restore-{entry['id']}.tmp"
                if temporary.is_symlink():
                    raise TrashError('unsafe')
                temporary.unlink(missing_ok=True)
                try:
                    with media.open('rb') as source, temporary.open('xb') as output:
                        while chunk := source.read(1024*1024):
                            if stop is not None and stop.is_set():
                                raise TrashError('storage')
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    shutil.copystat(media, temporary)
                    if stop is not None and stop.is_set():
                        raise TrashError('storage')
                    entry['restore_identity'] = identity(temporary)
                    self.save()
                    move_exclusive(temporary, target)
                    sync_directory(dest)
                    media.unlink()
                finally:
                    temporary.unlink(missing_ok=True)
            sync_directory(dest)
            sync_directory(media.parent)
            return target
        raise TrashError('collision')

    def _remove_files(self, entry):
        folder = self.directory(entry)
        if not folder.exists():
            # An unplugged disk must retain its journal entry for a later retry.
            if not folder.parent.is_dir():
                raise TrashError('unavailable')
            return
        for path in [self.media(entry), *[self.attachment(entry, name) for name in FILES]]:
            path.unlink(missing_ok=True)
        folder.rmdir()  # Unexpected files are never recursively removed.
        sync_directory(folder.parent)

    def discard(self, entry, restored=False):
        """Only known files inside this journal entry may be permanently removed."""
        entry['state'] = 'restored' if restored else 'deleting'
        self.save()
        self.cleanup_staging(entry)
        self._remove_files(entry)
        del self.entries[entry['id']]
        self.save()
