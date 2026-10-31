"""Persistent media identity and exact display titles, independent of filenames.

Content revisions continue to drive byte caches. A library ID survives an
explicit rename, replacement trim, location change and Trash restore.
"""
from __future__ import annotations
import copy
import json
import logging
import time
import os
import string
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from .media import media_revision
from .runtime import actual_home_dir

LIBRARY_PATH = actual_home_dir()/'.local/share/vice/library.json'


class MediaLibrary:
    def __init__(self, path=None):
        self.path = Path(path) if path else LIBRARY_PATH
        self.entries = {}
        self._batch=0;self._dirty=False
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if not isinstance(data,dict) or data.get('version') != 1 or not isinstance(data.get('media'), dict):
                    raise ValueError('Unsupported media library')
                for mid,entry in data['media'].items():
                    if not isinstance(entry,dict) or entry.get('id')!=mid or entry.get('kind') not in {'clip','image'} or not isinstance(entry.get('path'),str) or not isinstance(entry.get('revision'),str) or not isinstance(entry.get('observed'),str) or not isinstance(entry.get('inode'),list) or len(entry['inode'])!=2 or not (entry.get('title') is None or isinstance(entry['title'],str)):
                        raise ValueError('Invalid media identity')
                self.entries = data['media']
            except (ValueError,TypeError) as exc:
                backup=self.path.with_name(f'{self.path.name}.invalid-{time.time_ns()}')
                self.path.replace(backup)
                logging.getLogger(__name__).error('Invalid media library preserved at %s: %s',backup,exc)
        self._paths={(entry['kind'],entry['path']):mid for mid,entry in self.entries.items() if not entry.get('trashed') and not entry.get('replaced')}

    @contextmanager
    def batch(self):
        self._batch+=1
        try:yield
        finally:
            self._batch-=1
            if not self._batch and self._dirty:self.save()

    def save(self):
        if self._batch:
            self._dirty=True
            return
        self._dirty=False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.json.tmp')
        fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'version':1, 'media':self.entries}, stream, ensure_ascii=False)
            stream.flush(); os.fsync(stream.fileno())
        tmp.replace(self.path)
        directory=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)

    def ensure(self, path, kind, *, fresh=False):
        path = Path(path).absolute()
        revision = media_revision(path)
        st = path.stat()
        key=(kind,str(path))
        current=self.entries.get(self._paths.get(key))
        # A new inode at a known path is a different recording unless the edit
        # explicitly adopts it. Externally edited bytes on the same inode keep ID.
        if current and current.get('inode') != [st.st_dev, st.st_ino]:
            current = None
        if fresh or current is None:
            old=self.entries.get(self._paths.get(key))
            if old:old['replaced']=True
            current = dict(id=uuid.uuid4().hex, kind=kind, path=str(path), title=None,
                           inode=[st.st_dev,st.st_ino], observed=revision, revision=uuid.uuid4().hex)
            self.entries[current['id']] = current
            self._paths[key]=current['id']
            self.save()
        elif current['observed'] != revision:
            current.update(observed=revision, revision=uuid.uuid4().hex)
            self.save()
        return copy.deepcopy(current)

    def adopt(self, mid, path, *, title=None, content_changed=False, trashed=False):
        entry = self.entries[mid]
        self._paths.pop((entry['kind'],entry['path']),None)
        path = Path(path).absolute();st = path.stat()
        entry.update(path=str(path), inode=[st.st_dev,st.st_ino], observed=media_revision(path), trashed=trashed)
        if not trashed:self._paths[(entry['kind'],str(path))]=mid
        if title is not None:
            entry['title'] = title
        if content_changed:
            entry['revision'] = uuid.uuid4().hex
        self.save()
        return copy.deepcopy(entry)

    def mark_trashed(self, mid):
        entry=self.entries[mid]
        self._paths.pop((entry['kind'],entry['path']),None)
        entry['trashed'] = True
        self.save()

    def get(self, mid):
        return copy.deepcopy(self.entries.get(mid))

    def title(self, entry):
        return entry['title'] if entry.get('title') is not None else Path(entry['path']).stem


def physical_target(path, title):
    """Exact Linux component when possible; metadata-only for impossible names."""
    if not isinstance(title,str) or not title:raise ValueError('title')
    try:title_bytes=title.encode('utf-8')
    except UnicodeError:raise ValueError('title')
    if len(title_bytes)>4096:raise ValueError('title')
    filename = title + path.suffix
    try:
        limit = os.pathconf(path.parent, 'PC_NAME_MAX')
    except (OSError, ValueError):
        limit = 255
    if title in {'.','..'} or '/' in title or '\0' in title or len(filename.encode('utf-8')) > limit:
        return path
    return path.with_name(filename)


def rename_title(mode, options, title, index, path, game):
    """One implementation for preview and application; no eval or slugification."""
    if mode == 'replace':
        find = options.get('find', '')
        if not find: raise ValueError('find')
        return title.replace(find, options.get('replace',''))
    if mode == 'prefix': return options.get('text','') + title
    if mode == 'suffix': return title + options.get('text','')
    if mode == 'number':
        width = int(options.get('width',3))
        if not 1 <= width <= 8: raise ValueError('pattern')
        return options.get('prefix','') + str(index).zfill(width) + options.get('suffix','')
    if mode == 'pattern':
        pattern = options.get('pattern','{title}')
        values = dict(title=title, index=index, date=datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d'), game=game or '')
        out = []
        for literal, field, spec, conversion in string.Formatter().parse(pattern):
            out.append(literal)
            if field is None: continue
            if field not in values or conversion or (spec and (field != 'index' or not spec.endswith('d') or not spec[:-1].isdigit() or int(spec[:-1]) > 8)):
                raise ValueError('pattern')
            out.append(format(values[field], spec))
        return ''.join(out)
    raise ValueError('mode')
