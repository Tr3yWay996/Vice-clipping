import asyncio
import base64
import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
try:
    import _sandbox  # noqa
except ModuleNotFoundError:
    from tests import _sandbox  # noqa
from vice.games import GameLibrary, display_name
from vice.game_icons import ArtworkStore
from vice.config import Config
from vice.share import ShareServer
from vice.playlists import PlaylistStore


def rules(**values):
    return {field:values.get(field,[]) for field in ('executables','paths','classes','steam_ids','titles')}


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'games.json';self.library=GameLibrary(self.path)
        self.proc=mock.patch('vice.active_window.process_identity',return_value={});self.proc.start();self.addCleanup(self.proc.stop)
        self.steam=mock.patch('vice.active_window.read_steam_app_id',return_value=None);self.steam.start();self.addCleanup(self.steam.stop)
        self.name=mock.patch('vice.active_window.steam_game_name',return_value=None);self.name.start();self.addCleanup(self.name.stop)
        self.title=mock.patch('vice.active_window.window_title',return_value='');self.title.start();self.addCleanup(self.title.stop)

    def pending(self, process='KFGame.exe'):
        window={'process':process,'class':process,'pid':0}
        self.assertIsNone(self.library.resolve(window,bundled=[]))
        return window,self.library.snapshot()[-1]

    def test_unknown_game_confirmed_name_and_artwork_survive_restart_and_database_changes(self):
        window,game=self.pending()
        self.library.edit(game['id'],{'name':'Killing Floor 2','confirm':True})
        self.library.associate('historical-clip',game['id'])
        restored=GameLibrary(self.path)
        found=restored.resolve(window,bundled=[{'name':'Incorrect update','matches':['kfgame.exe']}])
        self.assertEqual(display_name(found),'Killing Floor 2');self.assertEqual(found['id'],game['id'])
        self.assertEqual(restored.game_for('historical-clip'),'Killing Floor 2')
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_rejection_later_enable_remove_and_repeated_suggestions(self):
        for action in ['reject','later']:
            window,game=self.pending(action+'Game.exe')
            self.library.action(game['id'],action)
            before=len(self.library.snapshot())
            self.assertIsNone(self.library.resolve(window,bundled=[]));self.assertEqual(len(self.library.snapshot()),before)
            restored=GameLibrary(self.path);self.assertIsNone(restored.resolve(window,bundled=[]))
            restored.action(game['id'],'enable');self.assertEqual(restored.resolve(window,bundled=[])['id'],game['id'])
        self.library=GameLibrary(self.path)
        window,game=self.pending('RemovalGame.exe');self.library.associate('clip',game['id']);name=game['name']
        self.library.action(game['id'],'remove');self.assertNotIn(game['id'],[g['id'] for g in self.library.snapshot()])
        self.assertIsNone(self.library.resolve(window,bundled=[]));self.assertEqual(self.library.game_for('clip'),name)

    def test_browser_titles_and_generic_launchers_do_not_become_games(self):
        for process in ['firefox','discord','steam','wine','explorer.exe','services.exe']:
            self.assertIsNone(self.library.resolve({'process':process,'class':process,'title':'Killing Floor 2'},bundled=[]))
        self.assertEqual(self.library.snapshot(),[])
        self.assertIsNone(self.library.resolve({'process':'KFGame.exe'},suggestions=False,bundled=[]))
        self.assertEqual(self.library.snapshot(),[])

    def test_truncated_proton_comm_uses_full_executable_and_local_steam_precedes_builtin(self):
        self.proc.stop()
        with mock.patch('vice.active_window.process_identity',return_value={'executable':'VeryLongUnlistedGame.exe','executable_path':'Z:/games/VeryLongUnlistedGame.exe'}):
            self.library.resolve({'process':'VeryLongUnliste','class':'Game'},bundled=[])
        game=self.library.snapshot()[0]
        self.assertIn('verylongunlistedgame.exe',game['rules']['executables'])
        with mock.patch('vice.active_window.read_steam_app_id',return_value='232090'),mock.patch('vice.active_window.steam_game_name',return_value='Local Steam Title'):
            found=self.library.resolve({'process':'KFGame.exe'},bundled=[{'name':'Wrong bundled title','matches':['kfgame.exe']}])
        self.assertEqual(display_name(found),'Local Steam Title');self.assertEqual(found['source'],'steam')

    def test_specific_title_globs_are_user_defined_and_conflicts_are_atomic(self):
        game=self.library.create({'name':'My Game','rules':rules(classes=['custom.game'],titles=['My Game *'])})
        self.assertEqual(self.library.resolve({'process':'native','title':'My Game chapter 2'},bundled=[])['id'],game['id'])
        before=copy.deepcopy(self.library.snapshot())
        for fields in [rules(titles=['*']),rules(executables=['wine']),rules(classes=['custom.game'])]:
            with self.assertRaises(ValueError):self.library.create({'name':'Other','rules':fields})
        self.assertEqual(self.library.snapshot(),before)
        self.library.edit(game['id'],{'rules':rules(executables=['different.exe'])})
        self.assertIsNone(self.library.resolve({'process':'native','class':'custom.game'},bundled=[]))

    def test_duplicate_merge_keeps_target_identity_and_all_clip_associations(self):
        one=self.library.create({'name':'First','rules':rules(executables=['first.exe'])})
        two=self.library.create({'name':'Second','rules':rules(executables=['second.exe'])})
        self.library.associate('one',one['id']);self.library.associate('two',two['id'])
        self.library.action(one['id'],'merge',two['id'])
        self.assertEqual(self.library.clips,{'one':two['id'],'two':two['id']})
        self.assertEqual(self.library.resolve({'process':'first.exe'},bundled=[])['id'],two['id'])
        self.assertEqual(len(self.library.snapshot()),1)

    def test_identical_display_names_do_not_merge_distinct_games(self):
        first=self.library.create({'name':'First game','rules':rules(executables=['first.exe'])})
        self.library.edit(first['id'],{'name':'Minecraft'})
        result=self.library.resolve({'process':'minecraft'},bundled=[{'name':'Minecraft','matches':['minecraft']}])
        self.assertNotEqual(result['id'],first['id'])
        self.assertEqual(display_name(result),'Minecraft')

    def test_legacy_aliases_migrate_but_explicit_edits_always_win(self):
        from vice.config import DiscordCustomGame
        custom = [DiscordCustomGame(name='Legacy title', matches=['kfgame'])]
        self.library.import_legacy(custom)
        game = self.library.snapshot()[0]
        self.library.edit(game['id'], {'name':'Killing Floor 2'})
        window = {'process':'KFGame-Win64.exe'}
        self.assertEqual(display_name(self.library.resolve(window, custom, bundled=[])), 'Killing Floor 2')
        custom[0].matches = ['unrelated.exe']
        self.library.import_legacy(custom)
        self.assertEqual(display_name(self.library.resolve(window, custom, bundled=[])), 'Killing Floor 2')
        self.library.edit(game['id'], {'rules':rules(executables=['new.exe'])})
        self.assertIsNone(self.library.resolve(window, custom, bundled=[], suggestions=False))
        self.assertEqual(self.library.resolve({'process':'new.exe'}, custom, bundled=[])['id'], game['id'])

    def test_linux_paths_remain_case_sensitive_and_removed_games_can_be_replaced(self):
        first = self.library.create({'name':'One', 'rules':rules(paths=['/games/Game'])})
        second = self.library.create({'name':'Two', 'rules':rules(paths=['/games/game'])})
        for path, expected in [('/games/Game',first),('/games/game',second)]:
            with mock.patch('vice.active_window.process_identity',return_value={'executable_path':path}):
                self.assertEqual(self.library.resolve({'process':'native'},bundled=[])['id'],expected['id'])
        self.library.action(first['id'],'remove')
        replacement = self.library.create({'name':'New identity','rules':rules(paths=['/games/Game'])})
        with mock.patch('vice.active_window.process_identity',return_value={'executable_path':'/games/Game'}):
            self.assertEqual(self.library.resolve({'process':'native'},bundled=[])['id'],replacement['id'])

    def test_damaged_library_is_preserved_for_recovery_without_blocking_recording(self):
        for contents in ['{broken', '{"version":1,"games":[{}]}']:
            self.path.write_text(contents)
            with self.assertLogs('vice.games',level='ERROR'):
                restored = GameLibrary(self.path)
            self.assertEqual(restored.snapshot(),[])
            backups = list(self.path.parent.glob('games.json.invalid-*'))
            self.assertTrue(any(path.read_text()==contents for path in backups))

    def test_identical_steam_titles_keep_distinct_application_identities(self):
        with mock.patch('vice.active_window.steam_game_name',return_value='Shared title'):
            first=self.library.resolve({'process':'game.exe','steam_app_id':'101'},bundled=[])
            second=self.library.resolve({'process':'game.exe','steam_app_id':'202'},bundled=[])
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(first['rules']['steam_ids'],['101'])
        self.assertEqual(second['rules']['steam_ids'],['202'])

    def test_clearing_rules_disables_recognition_but_retains_editable_history(self):
        game=self.library.ensure_name('Historical unknown title')
        self.library.edit(game['id'],{'name':'Corrected historical title','rules':rules()})
        self.assertEqual(display_name(GameLibrary(self.path).get(game['id'])),'Corrected historical title')
        self.assertIsNone(self.library.resolve({'process':'other'},bundled=[],suggestions=False))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class ArtworkTests(unittest.TestCase):
    # A tiny real PNG generated by FFmpeg avoids introducing Pillow.
    def setUp(self):
        import subprocess
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=ArtworkStore(self.root/'art')
        self.png=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=16x16','-frames:v','1','-threads','1','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,check=True).stdout

    def test_import_preview_persistence_offline_reset_and_remote_metadata(self):
        asset=self.store.import_image(self.png)
        self.assertTrue(self.store.asset_path(asset).is_file());self.assertIsNone(self.store.remote_url(asset))
        library=GameLibrary(self.root/'games.json')
        # Use the registry's own persistent artwork folder.
        store=ArtworkStore(self.root/'game-artwork');asset=store.import_image(self.png)
        game=library.create({'name':'Custom','rules':rules(executables=['custom.exe']),'artwork_override':asset})
        self.assertEqual(GameLibrary(library.path).get(game['id'])['artwork_override'],asset)
        library.action(game['id'],'reset-artwork');self.assertIsNone(library.get(game['id'])['artwork_override'])
        self.assertTrue(store.asset_path(asset).exists())
        with mock.patch('vice.game_icons._fetch_json') as network:
            self.assertEqual(store.search('Custom',False),[])
        network.assert_not_called()

    def test_malformed_images_size_limits_and_path_escape_are_rejected(self):
        for data in [b'<svg/>',b'\x89PNG\r\n\x1a\ngarbage',b'x'*(self.store.MAX_BYTES+1)]:
            with self.assertRaises(ValueError):self.store.import_image(data)
        with self.assertRaises(ValueError):self.store.asset_path('../../etc/passwd')
        with self.assertRaises(ValueError):self.store.prepare_discord('https://attacker.invalid',True)

    def test_search_is_local_catalog_matching_and_explicit_selection_is_cached(self):
        with mock.patch('vice.game_icons._name_map',return_value={'killing floor 2':'123','unrelated':'321'}),mock.patch('vice.game_icons._fetch_json',return_value={'icon':'abc'}),mock.patch('vice.game_icons.urllib.request.urlopen') as fetch:
            fetch.return_value.__enter__.return_value.read.return_value=self.png
            matches=self.store.search('Killing Floor',True);self.assertEqual(matches,[{'name':'killing floor 2','application_id':'123'}])
            asset=self.store.prepare_discord('123',True)
            self.assertEqual(self.store.remote_url(asset),'https://cdn.discordapp.com/app-icons/123/abc.png')
            self.assertEqual(fetch.call_args.args[0].full_url,'https://cdn.discordapp.com/app-icons/123/abc.png')


class GameApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.library=GameLibrary(self.root/'games.json')
        with mock.patch('vice.playlists.PLAYLISTS_PATH',self.root/'playlists.json'):
            self.server=ShareServer(Config(),games=self.library)
        self.server.broadcast=mock.AsyncMock()
    async def asyncTearDown(self):await self.server.stop()

    async def test_game_name_artwork_and_existing_playlist_identity_update_without_touching_media(self):
        game=self.library.create({'name':'Old','rules':rules(executables=['kfgame.exe'])})
        source=self.root/'Old recording.mp4';source.write_bytes(b'original')
        stamp=1_000_000_000_123_456_789;os.utime(source,ns=(stamp,stamp));before=hashlib.sha256(source.read_bytes()).hexdigest()
        self.server._clips[source.stem]=source
        self.library.associate(source.stem,game['id'])
        self.server.playlists.record_auto('Old',source.stem,game_id=game['id'])
        pid=self.server.playlists.list_playlists()[0]['id']
        self.server.playlists.create_custom('Keep me')
        self.library.edit(game['id'],{'name':'Killing Floor 2'})
        await self.server._publish_games()
        self.server.playlists.record_auto('Killing Floor 2','next-clip',game_id=game['id'])
        playlist=self.server.playlists.get(pid)
        self.assertEqual(playlist['name'],'Killing Floor 2');self.assertIn('next-clip',playlist['clip_slugs'])
        self.assertEqual(len(self.server.playlists.list_playlists()),2)
        clip=self.server._clip_json(source.stem,source,{})
        self.assertEqual(clip['game'],'Killing Floor 2');self.assertEqual(clip['game_id'],game['id'])
        self.assertEqual(source.stat().st_mtime_ns,stamp);self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
        self.assertEqual(source.name,'Old recording.mp4')

    async def test_local_only_routes_and_reclassification_do_not_modify_share_tokens(self):
        game=self.library.create({'name':'Game','rules':rules(executables=['game.exe'])})
        source=self.root/'clip.mp4';source.write_bytes(b'clip');self.server._clips['clip']=source
        self.server._issue_share_token('clip');token=self.server._share_tokens['clip']
        self.server.playlists.record_auto('Game','clip',game_id=game['id'])
        request=mock.Mock(match_info={'gid':game['id']});request.json=mock.AsyncMock(return_value={'action':'reclassify'})
        await self.server._api_game_action(request)
        self.assertEqual(self.library.clips['clip'],game['id']);self.assertEqual(self.server._share_tokens['clip'],token)
        public={route.resource.canonical for route in self.server._public_app.router.routes()}
        self.assertFalse(any('game' in route for route in public))
        with mock.patch('vice.game_icons._fetch_json') as fetch:
            request.json=mock.AsyncMock(return_value={'query':'private title'})
            result=await self.server._api_game_artwork_search(request)
        self.assertEqual(result.status,409);fetch.assert_not_called()

    async def test_reused_unknown_recording_does_not_inherit_old_game_membership(self):
        game=self.library.create({'name':'Old game','rules':rules(executables=['old.exe'])})
        source=self.root/'reused.mp4';source.write_bytes(b'new recording')
        self.library.associate(source.stem,game['id'])
        self.server.playlists.record_auto('Old game',source.stem,game_id=game['id'])
        custom=self.server.playlists.create_custom('My playlist')
        self.server.playlists.get(custom['id'])['clip_slugs'].append(source.stem)
        self.server._broadcast_clip=mock.AsyncMock()
        self.server.add_clip(source)
        await asyncio.sleep(0)
        self.assertIsNone(self.library.game_for(source.stem))
        self.assertIsNone(self.server.playlists.game_for(source.stem))
        self.assertIn(source.stem,self.server.playlists.get(custom['id'])['clip_slugs'])


class FullProcessIdentityTests(unittest.TestCase):
    def test_wine_command_line_recovers_the_untruncated_windows_executable(self):
        from vice.active_window import process_identity
        with mock.patch('vice.active_window.os.readlink',return_value='/usr/bin/wine64-preloader'), \
             mock.patch.object(Path,'read_text',return_value='VeryLongGame-Wi'), \
             mock.patch.object(Path,'read_bytes',return_value=b'wine64\0Z:\\games\\VeryLongGame-Win64-Shipping.exe\0'):
            identity=process_identity(42)
        self.assertEqual(identity['executable'],'VeryLongGame-Win64-Shipping.exe')
        self.assertIn('VeryLongGame-Win64-Shipping.exe',identity['executable_path'])

    def test_unreadable_cmdline_keeps_the_available_executable_identity(self):
        from vice.active_window import process_identity
        with mock.patch('vice.active_window.os.readlink',return_value='/games/VeryLongNativeGame'), \
             mock.patch.object(Path,'read_text',side_effect=PermissionError):
            identity=process_identity(42)
        self.assertEqual(identity['executable'],'VeryLongNativeGame')


class GameHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_local_api_upload_preview_save_and_public_isolation(self):
        if not shutil.which('ffmpeg'):self.skipTest('FFmpeg required')
        import aiohttp
        import subprocess
        from aiohttp.test_utils import TestClient, TestServer
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);library=GameLibrary(root/'games.json')
            with mock.patch('vice.playlists.PLAYLISTS_PATH',root/'playlists.json'):
                server=ShareServer(Config(),games=library)
            client=TestClient(TestServer(server._local_app));await client.start_server()
            public=TestClient(TestServer(server._public_app));await public.start_server()
            try:
                result=await (await client.post('/api/games',json={'name':'Test Game','rules':rules(executables=['test.exe'])})).json()
                gid=result['id']
                png=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=16x16','-frames:v','1','-threads','1','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,check=True).stdout
                form=aiohttp.FormData();form.add_field('file',png,filename='Été #1.png',content_type='image/png')
                uploaded=await (await client.post(f'/api/games/{gid}/artwork',data=form)).json()
                self.assertIn('asset',uploaded);self.assertIsNone(library.get(gid)['artwork_override'])
                response=await client.get(uploaded['url']);self.assertEqual(response.status,200)
                self.assertEqual(response.headers['Content-Type'],'image/png')
                socket=await client.ws_connect('/ws')
                response=await client.patch(f'/api/games/{gid}',json={'name':'Corrected','artwork_override':uploaded['asset']})
                self.assertEqual(response.status,200)
                event=await asyncio.wait_for(socket.receive_json(),2)
                self.assertEqual(event['type'],'games_changed')
                self.assertEqual(event['games'][0]['name'],'Corrected')
                self.assertEqual(event['games'][0]['artwork_override'],uploaded['asset'])
                await socket.close()
                snapshot=await (await client.get('/api/games')).json()
                self.assertEqual(snapshot['games'][0]['name'],'Corrected')
                self.assertEqual(snapshot['games'][0]['artwork_override'],uploaded['asset'])
                self.assertEqual((await public.get('/api/games')).status,404)
                self.assertEqual((await public.get(uploaded['url'])).status,404)
                self.assertEqual(GameLibrary(library.path).get(gid)['artwork_override'],uploaded['asset'])
            finally:
                await client.close();await public.close();await server.stop()


class RecordingIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_keeps_its_starting_identity_and_uses_corrected_name_when_saved(self):
        from vice.main import ViceDaemon
        with tempfile.TemporaryDirectory() as directory:
            library = GameLibrary(Path(directory)/'games.json')
            game = library.create({'name':'Original title','rules':rules(executables=['custom.exe'])})
            daemon = ViceDaemon.__new__(ViceDaemon)
            daemon.games = library
            daemon.cfg = Config()
            daemon._session_active = False
            daemon._pending_recording_apply = False
            path = Path(directory)/'Vice_Session_1.mp4'
            daemon.recorder = mock.Mock(start_session=mock.AsyncMock(return_value=path),stop_session=mock.AsyncMock(return_value=path))
            daemon.share = mock.Mock(broadcast=mock.AsyncMock(),add_clip=mock.Mock(return_value='local link'))
            with mock.patch('vice.active_window.get_active_window',return_value={'process':'custom.exe'}), \
                 mock.patch('vice.active_window.process_identity',return_value={}), \
                 mock.patch('vice.active_window.read_steam_app_id',return_value=None), \
                 mock.patch('vice.audio.play_session_start'), mock.patch('vice.audio.play_session_end'):
                await daemon._start_session()
                self.assertEqual(daemon._session_game_id, game['id'])
                library.edit(game['id'],{'name':'Corrected title'})
                await daemon._stop_session()
                await asyncio.sleep(0)
            daemon.share.add_clip.assert_called_once_with(path,game='Corrected title',game_id=game['id'])
            self.assertEqual(path.name,'Vice_Session_1.mp4')
