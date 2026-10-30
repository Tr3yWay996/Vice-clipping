"""Local-control API for the shared game library and its cached artwork."""
import asyncio
from aiohttp import web
from .game_icons import ArtworkStore
from .games import display_name


class GameLibraryAPI:
    def _game_for(self, slug):
        registry = getattr(self, 'games', None)
        return (registry.game_for(slug) if registry else None) or self.playlists.game_for(slug)

    def _game_id(self, slug):
        registry = getattr(self, 'games', None)
        return (registry.clips.get(slug) if registry else None) or next((p.get('game_id') for p in self.playlists.list_playlists() if p.get('kind') == 'auto' and slug in p.get('clip_slugs', [])), None)

    def _game_playlists(self):
        result = self.playlists.list_playlists()
        registry = getattr(self, 'games', None)
        if registry:
            for playlist in result:
                game = registry.get(playlist.get('game_id'))
                if game:
                    playlist['artwork_url'] = self._artwork_url(game)
        return result

    @staticmethod
    def _artwork_url(game):
        asset = game.get('artwork_override') or game.get('automatic_artwork')
        return f'/api/game-artwork/{asset}' if asset else None

    def _games_snapshot(self):
        games = self.games.snapshot()
        for game in games:
            slugs = {slug for slug, gid in self.games.clips.items() if gid == game['id']}
            for playlist in self.playlists.list_playlists():
                if playlist.get('game_id') == game['id']:
                    slugs.update(playlist.get('clip_slugs', []))
            game['clip_count'] = sum(slug in self._clips for slug in slugs)
            game['artwork_url'] = self._artwork_url(game)
        return {'games':games, 'revision':self.games.revision}

    def _queue_games_changed(self):
        loop = self._games_loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._schedule_games_changed)

    def _schedule_games_changed(self):
        if not self._games_loop:
            return
        self._games_dirty = True
        if self._games_task is None or self._games_task.done():
            self._games_task = asyncio.create_task(self._flush_game_changes())

    async def _flush_game_changes(self):
        while self._games_dirty:
            self._games_dirty = False
            await self._publish_games()

    def _refresh_local_game_art(self):
        store = ArtworkStore(self.games.path.parent/'game-artwork')
        for game in self.games.snapshot():
            if self._games_stopping:
                return
            key = (game['id'], self.cfg.ui.game_online_lookup)
            if key in self._games_art_checked or game.get('automatic_artwork') or game['status'] not in {'recognized','confirmed'}:
                continue
            self._games_art_checked.add(key)
            asset = next((asset for sid in game['rules']['steam_ids'] if (asset := store.local_steam(sid))), None)
            if not asset and self.cfg.ui.game_online_lookup:
                try:
                    exact = [match for match in store.search(game['name'], True) if match['name'].casefold() == game['name'].casefold()]
                    if len(exact) == 1:
                        asset = store.prepare_discord(exact[0]['application_id'], True)
                except Exception:
                    pass  # Offline fallback must never prevent recognition.
            if asset:
                with self.games.lock:
                    current = self.games.get(game['id'])
                    if current and not current.get('automatic_artwork'):
                        current['automatic_artwork'] = asset
                        self.games.save()

    def _sync_game_playlists(self):
        self.games.import_legacy(self.cfg.discord.custom_games)
        changed = False
        for playlist in self.playlists.list_playlists():
            if playlist.get('kind') != 'auto':
                continue
            game = self.games.get(playlist.get('game_id')) or self.games.ensure_name(playlist.get('game') or playlist['name'])
            current = self.playlists.get(playlist['id'])
            name = display_name(game)
            if current.get('game_id') != game['id'] or current.get('game') != name:
                if current['name'] == current.get('game') or not current.get('edited'):
                    current['name'] = name
                current.update(game_id=game['id'], game=name)
                changed = True
        if changed:
            self.playlists.save()

    async def _publish_games(self):
        async with self._games_lock:
            self._sync_game_playlists()
            await self.broadcast({'type':'games_changed', **self._games_snapshot()})
            await self._broadcast_playlists()
            if self._games_loop:
                self._games_art_dirty = True
                if self._games_art_task is None or self._games_art_task.done():
                    self._games_art_task = asyncio.create_task(self._load_game_art())

    async def _load_game_art(self):
        while self._games_art_dirty and not self._games_stopping:
            self._games_art_dirty = False
            await asyncio.to_thread(self._refresh_local_game_art)

    async def _api_games(self, req):
        self._sync_game_playlists()
        return web.json_response(self._games_snapshot(), headers={'Cache-Control':'no-store'})

    def _required_game(self, req):
        game = self.games.get(req.match_info['gid'])
        if not game or game['status'] == 'removed':
            raise web.HTTPNotFound()
        return game

    async def _api_game_create(self, req):
        try:
            game = self.games.create(await req.json())
        except ValueError as exc:
            return web.json_response({'ok':False, 'code':str(exc)}, status=409)
        await self._publish_games()
        return web.json_response({'ok':True, 'id':game['id']})

    async def _api_game_edit(self, req):
        game = self._required_game(req)
        try:
            self.games.edit(game['id'], await req.json())
        except ValueError as exc:
            return web.json_response({'ok':False, 'code':str(exc)}, status=409)
        await self._publish_games()
        return web.json_response({'ok':True})

    async def _api_game_action(self, req):
        game = self._required_game(req)
        body = await req.json()
        action = body.get('action')
        try:
            if action == 'reclassify':
                slugs = set()
                for playlist in self.playlists.list_playlists():
                    if playlist.get('game_id') == game['id']:
                        for slug in playlist.get('clip_slugs', []):
                            if slug in self._clips or slug.startswith('img:') and slug[4:] in self._images:
                                slugs.add(slug)
                self.games.associate_many(slugs, game['id'])
            elif action == 'merge':
                target = self.games.get(body.get('target'))
                if not target or target['status'] in {'removed','pending','rejected','deferred'}:
                    raise ValueError('target')
                self.games.action(game['id'], action, target['id'])
                self.playlists.merge_game(game['id'], target['id'], display_name(target))
            else:
                self.games.action(game['id'], action)
                if action == 'reset-artwork':
                    self._games_art_checked.discard((game['id'], self.cfg.ui.game_online_lookup))
        except ValueError as exc:
            return web.json_response({'ok':False, 'code':str(exc)}, status=409)
        await self._publish_games()
        return web.json_response({'ok':True})

    async def _api_game_artwork_file(self, req):
        try:
            path = ArtworkStore(self.games.path.parent/'game-artwork').asset_path(req.match_info['asset'])
        except ValueError:
            raise web.HTTPNotFound()
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Content-Type':'image/png', 'X-Content-Type-Options':'nosniff',
                                              'Cache-Control':'private, max-age=31536000, immutable'})

    async def _api_game_artwork(self, req):
        if req.match_info['gid'] != 'new':
            self._required_game(req)
        store = ArtworkStore(self.games.path.parent/'game-artwork')
        try:
            reader = await req.multipart()
            part = await reader.next()
            if part is None:
                raise ValueError('artwork')
            data = bytearray()
            while chunk := await part.read_chunk():
                data.extend(chunk)
                if len(data) > store.MAX_BYTES:
                    raise ValueError('artwork')
            asset = await asyncio.to_thread(store.import_image, bytes(data))
        except (ValueError, AssertionError):
            return web.json_response({'ok':False,'code':'artwork'}, status=400)
        return web.json_response({'ok':True,'asset':asset,'url':f'/api/game-artwork/{asset}'})

    async def _api_game_artwork_search(self, req):
        if req.match_info['gid'] != 'new':
            self._required_game(req)
        if not self.cfg.ui.game_online_lookup:
            return web.json_response({'ok':False,'code':'online'}, status=409)
        body = await req.json()
        store = ArtworkStore(self.games.path.parent/'game-artwork')
        try:
            matches = await asyncio.to_thread(store.search, body.get('query',''), True)
        except Exception:
            return web.json_response({'ok':False,'code':'offline'}, status=502)
        return web.json_response({'ok':True,'matches':matches})

    async def _api_game_artwork_preview(self, req):
        if req.match_info['gid'] != 'new':
            self._required_game(req)
        if not self.cfg.ui.game_online_lookup:
            return web.json_response({'ok':False,'code':'online'}, status=409)
        body = await req.json()
        store = ArtworkStore(self.games.path.parent/'game-artwork')
        try:
            asset = await asyncio.to_thread(store.prepare_discord, body.get('application_id'), True)
        except Exception:
            return web.json_response({'ok':False,'code':'artwork'}, status=400)
        return web.json_response({'ok':True,'asset':asset,'url':f'/api/game-artwork/{asset}'})
