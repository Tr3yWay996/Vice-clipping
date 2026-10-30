"""Local-only Trash endpoints, metadata transactions and daemon retention."""
import asyncio
import json
import logging
import shutil
import threading
from pathlib import Path

from aiohttp import web

from . import keys as keystore
from .jobs import TERMINAL
from .playlists import image_slug
from .recorder import resolve_path
from .trash import TrashError, TrashStore, identity

log = logging.getLogger(__name__)


class TrashAPI:
    def _init_trash(self):
        self.trash = TrashStore()
        self._trash_lock = asyncio.Lock()
        self._trash_wakeup = asyncio.Event()
        self._trash_task = None

    def _trash_snapshot(self):
        entries = self.trash.snapshot(self.cfg.output.trash_retention_days)
        from .games import display_name
        for entry in entries:
            game = self.games.get(entry.get('game_id'))
            if game:
                entry['game'] = display_name(game)
        return dict(items=entries, total_bytes=sum(entry['size'] for entry in entries),
                    retention_days=self.cfg.output.trash_retention_days, error=self.trash.error)

    async def _broadcast_trash(self):
        await self.broadcast({'type':'trash_changed', **self._trash_snapshot()})

    def _trash_conflict(self, slug, check_lock=True):
        if (check_lock and self._proxy_lock.locked()) or getattr(getattr(self, '_exports', None), 'busy', False):
            return True
        for job in getattr(getattr(self, '_jobs', None), 'jobs', []):
            if job['status'] in TERMINAL:
                continue
            payload = job.get('payload', {})
            if payload.get('slug') == slug or slug in payload.get('source_revisions', {}):
                return True
        return False

    def _trash_detach(self, entry):
        """Idempotent metadata commit after media is safely in Trash."""
        from .share import (HIGHLIGHTS_DIR, _save_views, _purge_slug_thumbs,
                            _purge_slug_proxies, _purge_clip_discord)
        slug, kind = entry['slug'], entry['kind']
        key = image_slug(slug) if kind == 'image' else slug
        source = Path(entry['original_dir'])/entry['name']
        index = self._images if kind == 'image' else self._clips
        if index.get(slug) == source:
            index.pop(slug, None)
        self.playlists.on_clip_deleted(key)
        if hasattr(self, 'games'):
            self.games.delete_clip(key)
        if kind == 'clip':
            self._forget_share_token(slug)
            self._meta.pop(slug, None)
            self._meta_revisions.pop(slug, None)
            self._views.pop(slug, None)
            _save_views(self._views)
            (HIGHLIGHTS_DIR/f'{slug}.json').unlink(missing_ok=True)
            keystore.delete_sidecar(slug)
            self.editor_project.on_clip_trashed(slug, entry['id'], entry['metadata'].get('editor_items', []), entry['name'])
            self._keyframes.invalidate(source)
            _purge_slug_proxies(slug)
            _purge_clip_discord(source)
        _purge_slug_thumbs(slug)
        self.trash.restored_paths.pop(str(source), None)

    def _trash_restore_metadata(self, entry, target):
        from .share import HIGHLIGHTS_DIR, _save_views, _thumb_path, media_revision
        slug, kind, metadata = target.stem, entry['kind'], entry['metadata']
        key = image_slug(slug) if kind == 'image' else slug
        for name, destination in [('keys.json', keystore.sidecar_path(slug)),
                                  ('highlights.json', HIGHLIGHTS_DIR/f'{slug}.json'),
                                  ('thumbnail.jpg', _thumb_path(target))]:
            source = self.trash.attachment(entry, name)
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix+'.restore-tmp')
                shutil.copy2(source, temporary)
                temporary.replace(destination)
        self.playlists.restore_memberships(metadata.get('playlists', []),
                                          image_slug(entry['slug']) if kind == 'image' else entry['slug'], key)
        if hasattr(self, 'games') and metadata.get('game_id'):
            self.games.associate(key, metadata['game_id'])
        if kind == 'clip':
            self._clips[slug] = target
            self._views[slug] = metadata.get('views', 0)
            _save_views(self._views)
            if metadata.get('media'):
                self._meta[slug] = metadata['media']
                self._meta_revisions[slug] = media_revision(target)
            self._issue_share_token(slug)  # Old public URLs are never revived.
            self.editor_project.on_clip_renamed(f"trash:{entry['id']}", slug)
        else:
            self._images[slug] = target
        self.trash.restored_paths[str(target)] = kind
        self.trash.save()

    async def _recover_trash(self):
        """Replay incomplete transactions before indexing and token creation."""
        for entry in list(self.trash.entries.values()):
            try:
                if entry['state'] == 'moving':
                    if self.trash.media(entry).is_file():
                        self._trash_detach(entry)
                        self.trash.commit(entry)
                    else:
                        source = Path(entry['original_dir'])/entry['name']
                        if source.is_file() and identity(source) == entry['identity']:
                            self.trash.discard(entry, restored=True)  # Move never happened.
                elif entry['state'] == 'restoring':
                    self.trash.cleanup_staging(entry)
                    target = Path(entry['restore_target'])
                    if target.is_file() and not target.is_symlink() and identity(target) == entry['restore_identity']:
                        self._trash_restore_metadata(entry, target)
                        self.trash.discard(entry, restored=True)
                    elif self.trash.media(entry).is_file():
                        self.trash.commit(entry)  # Safely retry from the UI.
                elif entry['state'] in {'deleting', 'restored'}:
                    if entry['state'] == 'deleting' and entry['kind'] == 'clip':
                        self.editor_project.on_clip_deleted(f"trash:{entry['id']}")
                    self.trash.discard(entry, restored=entry['state'] == 'restored')
            except (OSError, ValueError) as exc:
                log.warning('Trash transaction %s remains recoverable: %s', entry['id'], exc)

    def _index_restored_media(self):
        for raw, kind in self.trash.restored_paths.items():
            path = Path(raw)
            index = self._images if kind == 'image' else self._clips
            if path.is_file() and not path.is_symlink() and (path.stem not in index or index[path.stem] == path):
                index[path.stem] = path

    def _rename_restored_path(self, old, new):
        if getattr(self, 'trash', None) and str(old) in self.trash.restored_paths:
            self.trash.restored_paths[str(new)] = self.trash.restored_paths.pop(str(old))
            self.trash.save()

    async def _api_trash_move(self, req, kind):
        from .share import HIGHLIGHTS_DIR, _thumb_path, media_revision
        slug = req.match_info['slug']
        index = self._images if kind == 'image' else self._clips
        source = index.get(slug)
        if not source or not source.is_file():
            raise web.HTTPNotFound()
        if self._trash_conflict(slug):
            return web.json_response({'code':'trash.errors.busy'}, status=409)
        try:
            async with self._trash_lock, self._proxy_lock:
                if self._trash_conflict(slug, check_lock=False):
                    return web.json_response({'code':'trash.errors.busy'}, status=409)
                key = image_slug(slug) if kind == 'image' else slug
                project = self.editor_project.load() if kind == 'clip' else None
                metadata = dict(media_id=media_revision(source),game=self._game_for(key), game_id=self._game_id(key),
                                views=self._views.get(slug, 0) if kind == 'clip' else 0,
                                media=self._meta.get(slug, {}) if kind == 'clip' else {},
                                playlists=[p for p in self.playlists.list_playlists() if key in p['clip_slugs']],
                                editor_items=[it['id'] for it in (project or {}).get('items', []) if isinstance(it, dict) and it.get('clipId') == slug])
                attachments = {'thumbnail.jpg':_thumb_path(source)}
                if kind == 'clip':
                    attachments.update({'keys.json':keystore.sidecar_path(slug), 'highlights.json':HIGHLIGHTS_DIR/f'{slug}.json'})
                entry = self.trash.move(source, kind, metadata, attachments)
                self._trash_detach(entry)
                self.trash.commit(entry)
        except (OSError, ValueError) as exc:
            log.warning('Moving %s to Trash failed: %s', source, exc)
            if not source.exists():
                await self.broadcast({'type':'image_deleted' if kind == 'image' else 'clip_deleted','slug':slug})
            await self._broadcast_trash()
            return web.json_response({'code':f'trash.errors.{exc if isinstance(exc, TrashError) else "storage"}'}, status=409)
        await self.broadcast({'type':'image_deleted' if kind == 'image' else 'clip_deleted', 'slug':slug})
        if kind == 'clip':
            await self.broadcast({'type':'editor_project_changed'})
        await self._broadcast_playlists()
        await self._broadcast_trash()
        await self._publish_games()
        return web.json_response({'ok':True,'trash_id':entry['id']})

    async def _api_trash_list(self, req):
        return web.json_response(self._trash_snapshot(), headers={'Cache-Control':'no-store'})

    async def _api_trash_thumbnail(self, req):
        from .share import _make_thumb, _thumb_path
        try:
            async with self._trash_lock:
                entry = self.trash.get(req.match_info['tid'])
                thumbnail = self.trash.attachment(entry, 'thumbnail.jpg')
                if not thumbnail.is_file():
                    media = self.trash.media(entry)
                    if not media.is_file():
                        raise web.HTTPNotFound()
                    await _make_thumb(media)
                    cached = _thumb_path(media)
                    if not cached.is_file():
                        raise web.HTTPNotFound()
                    shutil.copy2(cached, thumbnail)
                    cached.unlink(missing_ok=True)
                # Read while holding the lock: a concurrent purge cannot race
                # the deferred open performed by FileResponse.
                data = thumbnail.read_bytes()
        except (OSError, ValueError):
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type='image/jpeg', headers={'Cache-Control':'private, max-age=3600'})

    async def _api_trash_action(self, req):
        body = await req.json()
        action = body.get('action')
        if action not in {'restore','purge'} or action == 'purge' and body.get('confirm') is not True:
            return web.json_response({'code':'trash.errors.confirm'}, status=400)
        ids = list(self.trash.entries) if body.get('all') is True else body.get('ids', [])
        if not isinstance(ids, list) or len(ids) > 10000 or any(not isinstance(tid, str) for tid in ids):
            return web.json_response({'code':'trash.errors.missing'}, status=400)
        if self._proxy_lock.locked() or self._exports.busy:
            return web.json_response({'code':'trash.errors.busy'}, status=409)
        results = []
        async with self._trash_lock, self._proxy_lock:
            for tid in dict.fromkeys(ids):
                try:
                    entry = self.trash.get(tid)
                    if entry['state'] == 'moving':
                        if not self.trash.media(entry).is_file():
                            raise TrashError('unavailable')
                        self._trash_detach(entry)
                        self.trash.commit(entry)
                    if action == 'purge':
                        if entry['kind'] == 'clip':
                            self.editor_project.on_clip_deleted(f'trash:{tid}')
                        self.trash.discard(entry)
                    else:
                        if entry['state'] in {'deleting','restored'}:
                            raise TrashError('storage')
                        index = self._images if entry['kind'] == 'image' else self._clips
                        from .share import HIGHLIGHTS_DIR
                        reserved = set(index)
                        if entry['kind'] == 'clip':
                            reserved |= {p.stem for p in HIGHLIGHTS_DIR.glob('*.json')} | {p.stem for p in keystore.KEYS_DIR.glob('*.json')}
                        destination = None
                        if body.get('destination') == 'library':
                            destination = resolve_path(self.cfg.output.image_directory if entry['kind'] == 'image' else self.cfg.output.directory)
                        stop = threading.Event()
                        task = asyncio.create_task(asyncio.to_thread(self.trash.restore_file, entry, destination, reserved, stop))
                        try:
                            target = await asyncio.shield(task)
                        except asyncio.CancelledError:
                            # Do not release the transaction locks while a
                            # worker could still publish or consume media.
                            stop.set()
                            await asyncio.gather(task, return_exceptions=True)
                            raise
                        self._trash_restore_metadata(entry, target)
                        self.trash.discard(entry, restored=True)
                        if entry['kind'] == 'clip':
                            await self.broadcast({'type':'clip_saved','clip':self._clip_json(target.stem,target,entry['metadata'].get('media',{}))})
                        else:
                            await self._broadcast_image(target.stem, target)
                    results.append({'id':tid,'ok':True})
                except (OSError, ValueError) as exc:
                    log.warning('Trash %s %s failed: %s', action, tid, exc)
                    results.append({'id':tid,'ok':False,'code':str(exc) if isinstance(exc, TrashError) else 'storage'})
        await self.broadcast({'type':'editor_project_changed'})
        await self._broadcast_playlists()
        await self._publish_games()
        await self._broadcast_trash()
        return web.json_response({'ok':all(result['ok'] for result in results), 'results':results})

    async def _trash_cleanup_loop(self):
        try:
            while True:
                async with self._trash_lock:
                    changed = False
                    for tid in self.trash.cleanup_candidates(self.cfg.output.trash_retention_days):
                        try:
                            entry = self.trash.get(tid)
                            restored = entry['state'] == 'restored'
                            if entry['kind'] == 'clip' and not restored:
                                self.editor_project.on_clip_deleted(f'trash:{tid}')
                            self.trash.discard(entry, restored=restored)
                            changed = True
                        except (OSError, ValueError) as exc:
                            log.warning('Trash expiration %s deferred: %s', tid, exc)
                    if changed:
                        await self._broadcast_trash()
                        await self.broadcast({'type':'editor_project_changed'})
                self._trash_wakeup.clear()
                try:
                    await asyncio.wait_for(self._trash_wakeup.wait(), timeout=3600)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
