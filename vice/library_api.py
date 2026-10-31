"""Shared media rename and inexpensive batch orchestration over existing stores."""
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from aiohttp import web
from .jobs import TERMINAL
from .library import MediaLibrary, physical_target, rename_title
from .playlists import image_slug
from .trash import move_exclusive


class LibraryAPI:
    def _init_library(self):
        self.library = MediaLibrary()
        self._library_lock = asyncio.Lock()

    def _sync_job_sources(self):
        from .media import media_revision
        changed=False
        for job in self._jobs.jobs:
            if not job.get('mode'):
                job['mode']=('copy' if job.get('payload',{}).get('copy') else 'replace') if job['operation']=='trim' else job['operation']
                changed=True
            if job.get('source_media_ids'):continue
            payload=job.get('payload',{})
            revisions=payload.get('source_revisions',{}) or ({payload['slug']:job.get('source_revision')} if payload.get('slug') else {})
            ids=[]
            for slug,revision in revisions.items():
                path=self._clips.get(slug)
                if path and path.exists() and media_revision(path)==revision:
                    ids.append(self.library.ensure(path,'clip')['id'])
            if ids:job['source_media_ids']=ids;changed=True
        if changed:self._jobs.save()

    def _library_slug(self, path, kind='clip', mid=None):
        # Legacy playlists prefix images with img:. Keep a disjoint clip
        # namespace without restricting legal Linux filenames or display titles.
        if kind=='clip' and path.stem.startswith(('img:','vid:')):
            return 'vid:'+(mid or self.library.ensure(path,kind)['id'])
        return path.stem

    def _library_fields(self, path, kind):
        entry = self.library.ensure(path, kind)
        return {'library_id':entry['id'], 'display_title':self.library.title(entry), 'content_revision':entry['revision']}

    def _library_items(self, kind):
        index = self._clips if kind=='clip' else self._images
        items=[]
        for slug,path in index.items():
            try:items.append((slug,path,path.stat().st_mtime))
            except FileNotFoundError:continue
        return [(slug,path) for slug,path,_ in sorted(items,key=lambda item:item[2],reverse=True)]

    def _library_source(self, mid):
        entry = self.library.get(mid)
        if not entry or entry.get('trashed') or entry.get('replaced'):
            raise ValueError('missing')
        path = Path(entry['path'])
        index = self._images if entry['kind'] == 'image' else self._clips
        if index.get(self._library_slug(path,entry['kind'],mid)) != path or not path.is_file():
            raise ValueError('missing')
        current = self.library.ensure(path, entry['kind'])
        if current['id'] != mid:
            raise ValueError('changed')
        return current, path, index

    def _library_busy(self, mid, slug):
        current=self._jobs.current
        for job in self._jobs.jobs:
            if job['status'] in TERMINAL:continue
            payload=job.get('payload',{})
            if mid in job.get('source_media_ids',[]) or payload.get('slug')==slug or slug in payload.get('source_revisions',{}):return True
        # Legacy on-demand proxy/export work does not yet have a source ID.
        return (self._proxy_lock.locked() and current is None) or (self._exports.busy and current is None)

    def _rename_plan(self, mid, title, owner=None):
        entry,path,index = self._library_source(mid)
        target = physical_target(path, title)
        slug = self._library_slug(path,entry['kind'],mid)
        new_slug = self._library_slug(target,entry['kind'],mid)
        # Metadata-only changes are safe during encodes. Filename changes are
        # deliberately blocked while any job still owns this source.
        physical = target != path
        if physical:
            if self._trash_lock.locked() or (self._library_busy(mid,slug) and owner is None):
                raise ValueError('busy')
            if target.exists() or (new_slug in index and index[new_slug] != path):
                raise ValueError('collision')
            from . import keys
            from .share import _highlight_path
            if entry['kind'] == 'clip' and new_slug!=slug and (keys.sidecar_path(new_slug).exists() or _highlight_path(new_slug).exists()):
                raise ValueError('collision')
        return dict(id=mid, kind=entry['kind'], slug=slug, title=title, filename=target.name,
                    physical_rename=physical, metadata_only=target == path and title != path.stem,
                    previous_title=self.library.title(entry), revision=entry['revision'], path=str(target))

    async def _rename_media(self, kind, slug, title, owner=None):
        from . import keys
        from .share import (_current_cache_files, _discord_path, media_revision,
                            _highlight_path, _thumb_path, _proxy_path, _audio_preview_path, _save_views, _purge_slug_thumbs, _purge_slug_proxies)
        index = self._images if kind == 'image' else self._clips
        path = index.get(slug)
        if not path or not path.is_file(): raise ValueError('missing')
        entry = self.library.ensure(path, kind)
        async with self._library_lock:
            plan = self._rename_plan(entry['id'], title,owner)
            target = Path(plan['path'])
            new_slug=self._library_slug(target,kind,entry['id'])
            old_revision = media_revision(path)
            cached = _current_cache_files(path)
            old_thumb,old_proxy=_thumb_path(path),_proxy_path(path)
            discord = _discord_path(path)
            if discord.exists(): cached.append(discord)
            meta = self._meta.get(slug, {}) if kind == 'clip' else {}
            editor_changed=False
            if target != path:
                # Linux no-replace publication also closes external filename races.
                try:move_exclusive(path, target)
                except FileExistsError:raise ValueError('collision')
                self._rename_restored_path(path, target)
                new_revision = media_revision(target)
                self._keyframes.renamed(path,target,old_revision)
                _purge_slug_thumbs(path.stem,keep=frozenset(cached));_purge_slug_proxies(path.stem,keep=frozenset(cached))
                for cache in cached:
                    if cache==old_thumb:destination=_thumb_path(target)
                    elif cache==old_proxy:destination=_proxy_path(target)
                    elif cache==discord:destination=_discord_path(target)
                    else:
                        match=re.search(r'_audio_(\d+)\.m4a$',cache.name)
                        if not match:continue
                        destination=_audio_preview_path(target,int(match.group(1)))
                    try: cache.replace(destination)
                    except OSError: pass  # Cache misses are recoverable; media stays safe.
                # Retain insertion order for recordings with equal timestamps.
                renamed_index={new_slug if key==slug else key:target if key==slug else value for key,value in index.items()}
                index.clear();index.update(renamed_index)
                old_key = image_slug(slug) if kind == 'image' else slug
                new_key = image_slug(new_slug) if kind == 'image' else new_slug
                self.games.rename_clip(old_key, new_key)
                self.playlists.on_clip_renamed(old_key, new_key)
                if kind == 'clip':
                    self._meta.pop(slug,None);self._meta_revisions.pop(slug,None)
                    if meta:
                        self._meta[new_slug] = meta;self._meta_revisions[new_slug] = new_revision
                    old_hl = _highlight_path(slug)
                    if old_hl.exists(): old_hl.rename(_highlight_path(new_slug))
                    keys.move_sidecar(slug,new_slug)
                    if slug in self._views:
                        self._views[new_slug] = self._views.pop(slug);_save_views(self._views)
                    self._move_share_token(slug,new_slug)
                    editor_changed=self.editor_project.on_clip_renamed(slug,new_slug)
            self.library.adopt(entry['id'],target,title=title)
            item = self._image_basic_json(new_slug,target) if kind == 'image' else self._clip_json(new_slug,target,meta)
            await self.broadcast({'type':f'{kind}_renamed', 'old_slug':slug, kind:item})
            # A startup/trim probe can still be pending. Do not make a title
            # edit wait for it; enrich the current identity asynchronously.
            if kind=='clip' and not meta:
                asyncio.create_task(self._broadcast_clip(new_slug,target))
            if editor_changed:await self.broadcast({'type':'editor_project_changed'})
            if target!=path:await self._broadcast_playlists()
            await self._publish_games()
            return dict(item, ok=True, physical_rename=target != path, metadata_only=plan['metadata_only'])

    async def _api_library_audio(self, req):
        try:entry,path,index=self._library_source(req.match_info['mid'])
        except ValueError:raise web.HTTPNotFound()
        if entry['kind']!='clip':raise web.HTTPNotFound()
        req.match_info['slug']=self._library_slug(path,entry['kind'],entry['id'])
        return await self._audio_track(req)

    async def _api_library_file(self, req):
        try: entry,path,index = self._library_source(req.match_info['mid'])
        except ValueError: raise web.HTTPNotFound()
        asset = req.match_info['asset']
        req.match_info['slug'] = self._library_slug(path,entry['kind'],entry['id']);req.match_info['ref'] = req.match_info['slug']
        handlers = {'video':self._video,'thumbnail':self._thumb,'image':self._image_file,'image-thumbnail':self._image_thumb}
        if asset not in handlers or (asset in {'image','image-thumbnail'}) != (entry['kind']=='image'):
            raise web.HTTPNotFound()
        return await handlers[asset](req)

    async def _api_library_preview(self, req):
        body = await req.json()
        if not isinstance(body,dict):return web.json_response({'code':'library.errors.selection'},status=400)
        ids = body.get('ids', [])
        if not isinstance(ids,list) or not ids or len(ids)>1000 or any(not isinstance(mid,str) for mid in ids) or len(set(ids))!=len(ids):
            return web.json_response({'code':'library.errors.selection'},status=400)
        options = body.get('options', {})
        if not isinstance(options,dict) or any(not isinstance(value,(str,int)) for value in options.values()):
            return web.json_response({'code':'library.errors.pattern'},status=400)
        items=[];targets={}
        for i,mid in enumerate(ids):
            try:
                entry,path,index=self._library_source(mid)
                start=int(options.get('start',1))
                if not 0<=start<=1_000_000_000: raise ValueError('pattern')
                slug=self._library_slug(path,entry['kind'],mid)
                key=image_slug(slug) if entry['kind']=='image' else slug
                title=rename_title(body['mode'],options,self.library.title(entry),start+i,path,self._game_for(key))
                plan=self._rename_plan(mid,title)
                if plan['path'] in targets:
                    plan['code']='collision';items[targets[plan['path']]]['code']='collision'
                targets[plan['path']]=len(items)
                plan.pop('path',None);items.append(plan)
            except (ValueError,TypeError,KeyError,OSError) as exc:
                items.append({'id':mid,'code':str(exc) if isinstance(exc,ValueError) else 'pattern'})
        return web.json_response({'items':items,'valid':not any('code' in item for item in items)})

    async def _api_library_actions(self, req):
        body=await req.json()
        if not isinstance(body,dict):return web.json_response({'code':'library.errors.selection'},status=400)
        action=body.get('action');ids=body.get('ids',[])
        if action not in {'rename','trash','game','playlist-add','playlist-remove','playlist-move','paths','share-links','reveal'} or not isinstance(ids,list) or not ids or len(ids)>1000 or any(not isinstance(mid,str) for mid in ids):
            return web.json_response({'code':'library.errors.selection'},status=400)
        if action in {'trash','rename','game','playlist-move','playlist-remove'} and body.get('confirm') is not True:
            return web.json_response({'code':'library.errors.confirm'},status=400)
        raw_plans=body.get('plans',[])
        if not isinstance(raw_plans,list) or any(not isinstance(plan,dict) or not isinstance(plan.get('id'),str) for plan in raw_plans):
            return web.json_response({'code':'library.errors.selection'},status=400)
        plans={plan['id']:plan for plan in raw_plans}
        results=[]
        # A known collision blocks a rename batch before its first mutation.
        if action=='rename':
            targets=set()
            try:
                for mid in ids:
                    plan=plans[mid];entry,path,index=self._library_source(mid)
                    if plan.get('previous_title')!=self.library.title(entry) or plan.get('revision')!=entry['revision']: raise ValueError('changed')
                    current=self._rename_plan(mid,plan['title'])
                    if current['path'] in targets: raise ValueError('collision')
                    targets.add(current['path'])
            except (ValueError,KeyError) as exc:
                return web.json_response({'results':[{'id':mid,'ok':False,'code':str(exc) if isinstance(exc,ValueError) else 'changed'} for mid in ids]})
        reveal=set()
        for mid in dict.fromkeys(ids):
            try:
                entry,path,index=self._library_source(mid);kind=entry['kind'];slug=self._library_slug(path,kind,mid)
                key=image_slug(slug) if kind=='image' else slug
                result={'id':mid,'ok':True}
                if action=='rename': result['item']=await self._rename_media(kind,slug,plans[mid]['title'])
                elif action=='trash':
                    response=await self._api_trash_move(SimpleNamespace(match_info={'slug':slug}),kind)
                    data=json.loads(response.text)
                    if response.status>=400 or not data.get('ok'): raise ValueError(data.get('code','storage'))
                elif action=='game':
                    gid=body.get('game_id')
                    if gid is None:
                        self.games.delete_clip(key);self.playlists.clear_auto_membership(key)
                    else: self.assign_media_game([key],gid)
                elif action.startswith('playlist-'):
                    pid=body.get('playlist_id');playlist=self.playlists.get(pid)
                    if not playlist: raise ValueError('playlist')
                    if action=='playlist-remove': self.playlists.remove_clip(pid,key)
                    else:
                        if action=='playlist-move':
                            source=self.playlists.get(body.get('source_playlist_id'))
                            if not source or source.get('kind')!='custom' or source['id']==pid: raise ValueError('playlist')
                        self.playlists.add_clip(pid,key)
                        if action=='playlist-move': self.playlists.remove_clip(source['id'],key)
                elif action=='paths':result['value']=str(path)
                elif action=='share-links':
                    if kind!='clip':raise ValueError('share')
                    result['value']=self.share_url(slug)
                elif action=='reveal':reveal.add(path.parent)
                if action in {'game','playlist-add','playlist-remove','playlist-move'}:
                    item=self._image_basic_json(slug,path) if kind=='image' else self._clip_json(slug,path,self._meta.get(slug,{}))
                    await self.broadcast({'type':f'{kind}_updated',kind:item})
                results.append(result)
            except (ValueError,KeyError,OSError) as exc:
                results.append({'id':mid,'ok':False,'code':str(exc) if isinstance(exc,ValueError) else 'storage'})
            await asyncio.sleep(0)
        if action=='reveal':
            from .share import _xdg_open
            for folder in reveal: asyncio.create_task(_xdg_open(folder))
        if action in {'game','playlist-add','playlist-remove','playlist-move'}:
            await self._broadcast_playlists();await self._publish_games()
        return web.json_response({'results':results})
