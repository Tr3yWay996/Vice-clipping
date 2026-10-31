"""Capture latency sequencing and end-to-end recording identity regressions."""
import asyncio
import copy
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
try:
    import _sandbox  # noqa
except ModuleNotFoundError:
    from tests import _sandbox  # noqa
from vice.active_window import _candidate_windows_wmctrl, process_identity
from vice.config import Config, UIConfig
from vice.games import GameLibrary
from vice.main import ViceDaemon
from vice.share import ShareServer
from vice.recorder import capture_screenshot


def rules(**kw):
    return {key:kw.get(key,[]) for key in ('executables','paths','classes','steam_ids','titles')}


class ProtonRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'games.json'
        self.games = GameLibrary(self.path)
        self.game = self.games.create({'name':'Rocket League', 'rules':rules(executables=['RocketLeague.exe'])})
        self.proc = mock.patch('vice.active_window.process_identity',return_value={}); self.proc.start(); self.addCleanup(self.proc.stop)
        for name,value in [('read_steam_app_id',None),('steam_game_name',None),('window_title','')]:
            patch = mock.patch('vice.active_window.'+name,return_value=value);patch.start();self.addCleanup(patch.stop)

    def test_full_and_truncated_comm_resolve_manual_identity_and_survive_restart(self):
        for process in ['RocketLeague.exe','RocketLeague.ex']:
            for executable in ['', 'wine64-preloader']:
                window = {'process':process,'class':'','executable':executable}
                found = self.games.resolve(window,bundled=[])
                self.assertEqual(found['id'], self.game['id'])
                self.assertIsNotNone(found['last_detected'])
        self.games = GameLibrary(self.path)
        self.assertEqual(self.games.resolve({'process':'RocketLeague.ex'},bundled=[])['id'], self.game['id'])

    def test_full_proton_path_and_steam_id_take_precedence_over_truncated_comm(self):
        self.proc.stop()
        with mock.patch('vice.active_window.process_identity',return_value={'executable':'RocketLeague.exe','executable_path':'Z:/Games/RocketLeague/Binaries/Win64/RocketLeague.exe'}):
            self.assertEqual(self.games.resolve({'pid':81,'process':'RocketLeague.ex','steam_app_id':'252950'})['id'],self.game['id'])

    def test_ambiguous_truncation_and_unrelated_apps_are_not_classified(self):
        self.games.create({'name':'Other', 'rules':rules(executables=['RocketLeague.extra.exe'])})
        self.assertIsNone(self.games.resolve({'process':'RocketLeague.ex'},bundled=[]))
        for window in [{}, {'process':'firefox','title':'Rocket League'}, {'process':'wine64'}, {'process':'RocketLeague'},
                       {'process':'RocketLeague.ex','executable':'differentgame.exe'}]:
            self.assertIsNone(self.games.resolve(window,bundled=[],suggestions=False))

    def test_dotted_visible_class_is_preserved_and_matches_exact_class_rule(self):
        self.games.edit(self.game['id'],{'rules':rules(classes=['RocketLeague.exe'])})
        with mock.patch('vice.active_window._run',return_value='0x123 0 88 rocketleague.exe.RocketLeague.exe host Rocket League'), mock.patch('vice.active_window._read_proc_comm',return_value='wine'):
            window = _candidate_windows_wmctrl()[0]
        self.assertEqual(window['class'],'rocketleague.exe')
        self.assertEqual(self.games.resolve(window,bundled=[])['id'],self.game['id'])

    def test_proton_loader_cmdline_recovers_full_executable(self):
        self.proc.stop()
        with mock.patch('vice.active_window.os.readlink',return_value='/usr/bin/wine64-preloader'), mock.patch.object(Path,'read_text',return_value='RocketLeague.ex'), mock.patch.object(Path,'read_bytes',return_value=b'Z:\\games\\RocketLeague.exe\0-noother\0'):
            identity = process_identity(333)
        self.assertEqual(identity['executable'],'RocketLeague.exe')

    def test_focused_and_kde_fallback_detection_attach_id_without_discord_or_filename_tags(self):
        daemon=ViceDaemon.__new__(ViceDaemon);daemon.cfg=Config();daemon.cfg.discord.enabled=False
        daemon.cfg.output.tag_clips_with_game=False;daemon.games=self.games
        window={'process':'RocketLeague.ex','class':'','pid':0}
        for focused in [window,None]:
            with mock.patch('vice.active_window.get_active_window',return_value=copy.deepcopy(focused)), mock.patch('vice.active_window.list_candidate_windows',return_value=[copy.deepcopy(window)]):
                self.assertIsNone(daemon._clip_game_tag())
            self.assertEqual(daemon._last_clip_game_id,self.game['id'])
            self.assertEqual(daemon._last_clip_game,'Rocket League')

    def test_boost_config_validation(self):
        for value in [None,'bad',float('nan'),float('inf'),0,9]:
            self.assertEqual(UIConfig(playback_boost=value).playback_boost,2)
        self.assertEqual(UIConfig(playback_boost=2.25).playback_boost,2.25)


class RecordingPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.games=GameLibrary(self.root/'games.json')
        self.game=self.games.create({'name':'Rocket League','rules':rules(executables=['RocketLeague.exe'])})
        self.cfg=Config();self.cfg.output.directory=str(self.root/'clips');self.cfg.output.image_directory=str(self.root/'images');self.cfg.output.auto_playlist_by_game=True
        with mock.patch('vice.playlists.PLAYLISTS_PATH',self.root/'playlists.json'):
            self.server=ShareServer(self.cfg,games=self.games)
        self.server.broadcast=mock.AsyncMock()
        patch=mock.patch('vice.share._make_thumb',new=mock.AsyncMock());patch.start();self.addCleanup(patch.stop)
        patch=mock.patch('vice.share.probe_media',new=mock.AsyncMock(return_value={'width':2560,'height':1440}));patch.start();self.addCleanup(patch.stop)
        patch=mock.patch('vice.share._ffprobe',new=mock.AsyncMock(return_value={'duration':1}));patch.start();self.addCleanup(patch.stop)
        self.daemon=ViceDaemon.__new__(ViceDaemon);self.daemon.cfg=self.cfg;self.daemon.games=self.games;self.daemon.share=self.server
        self.daemon._display_override=None;self.daemon._last_clip_game='Replay game';self.daemon._last_clip_game_id='replay-id'
    async def asyncTearDown(self):
        tasks=list(getattr(self.daemon,'_screenshot_background',()))
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        await asyncio.sleep(.01);await self.server.stop()

    async def test_recorded_clip_and_image_use_stable_id_even_without_name_and_refresh_counts(self):
        clip=self.root/'new.mp4';clip.write_bytes(b'video')
        image=self.root/'shot.png';image.write_bytes(b'image')
        self.server.add_clip(clip,game_id=self.game['id']);self.server.add_image(image,game_id=self.game['id'])
        await asyncio.sleep(.01)
        self.assertEqual(self.games.clips,{'new':self.game['id'],'img:shot':self.game['id']})
        playlist=self.server.playlists.list_playlists()[0]
        self.assertEqual(set(playlist['clip_slugs']),{'new','img:shot'})
        self.assertEqual(self.server._games_snapshot()['games'][0]['clip_count'],1)
        restored=GameLibrary(self.games.path)
        self.assertEqual(restored.game_for('new'),'Rocket League');self.assertEqual(restored.game_for('img:shot'),'Rocket League')

    async def test_detected_proton_game_reaches_recorder_save_callback_and_live_library(self):
        daemon=self.daemon
        daemon._clip_count=0;daemon.key_ring=None;daemon._ready=True;daemon._session_active=False
        daemon.recorder=SimpleNamespace(name='gpu-screen-recorder');daemon.hotkeys_available=True;daemon._recorder_error=''
        self.cfg.output.tag_clips_with_game=False;self.cfg.discord.enabled=False
        window={'process':'RocketLeague.ex','class':'','pid':0}
        with mock.patch('vice.active_window.get_active_window',return_value=window),mock.patch('vice.active_window.process_identity',return_value={}),mock.patch('vice.active_window.read_steam_app_id',return_value=None):
            self.assertIsNone(daemon._clip_game_tag())
        self.assertEqual(daemon._last_clip_game_id,self.game['id'])
        clip=self.root/'Vice_Clip_1.mp4';clip.write_bytes(b'recorded')
        daemon._on_clip_saved(clip)
        await asyncio.sleep(.01)
        self.assertEqual(self.games.clips[clip.stem],self.game['id'])
        self.assertIn(clip.stem,self.server.playlists.list_playlists()[0]['clip_slugs'])
        self.assertIsNotNone(self.server._games_snapshot()['games'][0]['last_detected'])
        self.assertEqual(self.server._games_snapshot()['games'][0]['clip_count'],1)
        self.assertIsNone(daemon._last_clip_game_id)

    async def test_reviewed_bulk_assignment_preserves_bytes_timestamps_tokens_sidecars_and_custom_playlists(self):
        clip=self.root/'old.mp4';clip.write_bytes(b'original');image=self.root/'old.png';image.write_bytes(b'image')
        stamp=1_000_000_000_123_456_789;os.utime(clip,ns=(stamp,stamp))
        self.server._clips['old']=clip;self.server._images['old']=image
        self.server._ensure_share_tokens();token=self.server._share_tokens['old']
        custom=self.server.playlists.create_custom('Favorites');self.server.playlists.add_clip(custom['id'],'old')
        request=SimpleNamespace(match_info={'gid':self.game['id']},json=mock.AsyncMock(return_value={'slugs':['old','img:old'],'confirm':True}))
        response=await self.server._api_game_assign(request)
        self.assertEqual(response.status,200);self.assertEqual(clip.read_bytes(),b'original');self.assertEqual(clip.stat().st_mtime_ns,stamp)
        self.assertEqual(self.server._share_tokens['old'],token);self.assertIn('old',self.server.playlists.get(custom['id'])['clip_slugs'])
        self.assertEqual(self.games.game_for('old'),'Rocket League');self.assertEqual(self.games.game_for('img:old'),'Rocket League')
        events=[call.args[0] for call in self.server.broadcast.call_args_list]
        self.assertTrue(any(event['type']=='clip_updated' and event['clip']['game_id']==self.game['id'] for event in events))
        self.assertTrue(any(event['type']=='image_updated' and event['image']['game_id']==self.game['id'] for event in events))

    async def test_assignment_validates_entire_selection_and_requires_confirmation(self):
        from aiohttp import web
        clip=self.root/'old.mp4';clip.write_bytes(b'old');self.server._clips['old']=clip
        for body in [{'slugs':['old']},{'slugs':[],'confirm':True},{'slugs':[{}],'confirm':True}]:
            response=await self.server._api_game_assign(SimpleNamespace(match_info={'gid':self.game['id']},json=mock.AsyncMock(return_value=body)))
            self.assertEqual(response.status,400)
        with self.assertRaises(web.HTTPNotFound):
            await self.server._api_game_assign(SimpleNamespace(match_info={'gid':self.game['id']},json=mock.AsyncMock(return_value={'slugs':['old','missing'],'confirm':True})))
        self.assertNotIn('old',self.games.clips)

    async def test_capture_and_notification_do_not_wait_for_detection_clipboard_or_thumbnail(self):
        gate=threading.Event();clipboard=asyncio.Event();thumbnail=asyncio.Event();capture_started=asyncio.Event()
        def detect():
            gate.wait(5);return 'Rocket League',self.game['id']
        async def capture(out,*args):
            capture_started.set();out.write_bytes(b'actual-image');return out
        async def copy_image(out):await clipboard.wait();return True,''
        async def thumb(out):await thumbnail.wait()
        try:
            with mock.patch.object(self.daemon,'_detect_recording_game',side_effect=detect),mock.patch('vice.main.capture_screenshot',side_effect=capture),mock.patch('vice.main.copy_image_to_clipboard',side_effect=copy_image),mock.patch('vice.main.audio.play_screenshot'),mock.patch('vice.share._make_thumb',side_effect=thumb):
                await asyncio.wait_for(self.daemon._take_screenshot(),1)
                await asyncio.sleep(.01)
                self.assertTrue(capture_started.is_set());self.assertEqual(len(self.server._images),1)
                events=[call.args[0] for call in self.server.broadcast.call_args_list]
                self.assertTrue(any(event['type']=='image_saved' for event in events))
                self.assertFalse(clipboard.is_set());self.assertFalse(thumbnail.is_set())
                self.assertEqual((self.daemon._last_clip_game,self.daemon._last_clip_game_id),('Replay game','replay-id'))
                gate.set();clipboard.set();thumbnail.set()
                await asyncio.gather(*list(self.daemon._screenshot_background))
                slug=next(iter(self.server._images));self.assertEqual(self.games.clips['img:'+slug],self.game['id'])
        finally:gate.set();clipboard.set();thumbnail.set()

    async def test_screenshot_burst_reuses_detection_without_waiting_for_slow_clipboard(self):
        gate=threading.Event();clipboard=asyncio.Event()
        def detect():gate.wait(5);return 'Rocket League',self.game['id']
        async def capture(out,*args):out.write_bytes(b'actual-image');return out
        async def copy_image(out):await clipboard.wait();return True,''
        try:
            with mock.patch.object(self.daemon,'_detect_recording_game',side_effect=detect) as detection,mock.patch('vice.main.capture_screenshot',side_effect=capture),mock.patch('vice.main.copy_image_to_clipboard',side_effect=copy_image),mock.patch('vice.main.audio.play_screenshot'):
                await self.daemon._take_screenshot();await self.daemon._take_screenshot()
                self.assertEqual(len(self.server._images),2);self.assertEqual(detection.call_count,1)
                gate.set();clipboard.set()
                await asyncio.gather(*list(self.daemon._screenshot_background))
                self.assertEqual(len(self.games.clips),2)
        finally:gate.set();clipboard.set()

    async def test_capture_failure_never_registers_or_copies_an_image(self):
        with mock.patch.object(self.daemon,'_detect_recording_game',return_value=(None,None)),mock.patch('vice.main.capture_screenshot',side_effect=RuntimeError('target gone')),mock.patch('vice.main.copy_image_to_clipboard',new=mock.AsyncMock()) as clipboard,mock.patch('vice.main.audio.play_clip_failed'):
            await self.daemon._take_screenshot()
            self.assertFalse(self.server._images);clipboard.assert_not_called()
            self.assertTrue(any(call.args[0]['type']=='image_error' for call in self.server.broadcast.call_args_list))

    async def test_delayed_detection_cannot_tag_replacement_under_same_path(self):
        from vice.media import media_revision
        image=self.root/'shot.png';image.write_bytes(b'first');self.server._images['shot']=image
        revision=media_revision(image);image.unlink();image.write_bytes(b'replacement')
        future=asyncio.get_running_loop().create_future();future.set_result(('Rocket League',self.game['id']))
        await self.daemon._tag_screenshot(image,future,revision)
        self.assertNotIn('img:shot',self.games.clips)

    async def test_recent_game_snapshot_keeps_filename_tag_and_clipboard_failure_is_reported_after_registration(self):
        self.daemon._observed_recording_game=(time.monotonic(),'Rocket League',self.game['id'])
        async def capture(out,*args):out.write_bytes(b'actual-image');return out
        with mock.patch.object(self.daemon,'_detect_recording_game') as detect,mock.patch('vice.main.capture_screenshot',side_effect=capture),mock.patch('vice.main.copy_image_to_clipboard',new=mock.AsyncMock(return_value=(False,'clipboard unavailable'))),mock.patch('vice.main.audio.play_screenshot'):
            await self.daemon._take_screenshot()
            await asyncio.gather(*list(self.daemon._screenshot_background))
            detect.assert_not_called()
            slug=next(iter(self.server._images));self.assertIn('Rocket',slug)
            self.assertEqual(self.games.clips['img:'+slug],self.game['id'])
            self.assertTrue(any(call.args[0]['type']=='image_copy_failed' for call in self.server.broadcast.call_args_list))

    async def test_boost_config_roundtrips_through_existing_toml_settings(self):
        from vice import config
        self.cfg.ui.playback_boost=3.25
        with mock.patch.object(config,'CONFIG_DIR',self.root),mock.patch.object(config,'CONFIG_PATH',self.root/'vice.toml'):
            config.save(self.cfg)
            self.assertEqual(config.load().ui.playback_boost,3.25)



class ScreenshotProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_and_cancellation_reap_gsr_and_remove_partial_image(self):
        for exception in [asyncio.TimeoutError(),asyncio.CancelledError()]:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'shot.png';path.write_bytes(b'partial')
                proc=SimpleNamespace(returncode=None,kill=mock.Mock(),communicate=mock.AsyncMock(side_effect=[exception,(b'',b'')]))
                with mock.patch('vice.recorder._gsr_prefix',return_value=['gpu-screen-recorder']),mock.patch('vice.recorder._gsr_capture_target',return_value='screen'),mock.patch('vice.recorder.asyncio.create_subprocess_exec',return_value=proc):
                    with self.assertRaises(asyncio.CancelledError if isinstance(exception,asyncio.CancelledError) else RuntimeError):
                        await capture_screenshot(path,Config().recording)
                proc.kill.assert_called_once();self.assertEqual(proc.communicate.await_count,2);self.assertFalse(path.exists())

    async def test_validated_recording_target_avoids_duplicate_monitor_probe(self):
        from vice import recorder
        rc=Config().recording;rc.display='DP-1'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shot.png'
            async def finish():path.write_bytes(b'unchanged-resolution-png');return b'',b''
            proc=SimpleNamespace(returncode=0,communicate=mock.AsyncMock(side_effect=finish))
            with mock.patch.dict(recorder._screenshot_targets,clear=True),mock.patch('vice.recorder._resolve_display_option',return_value={'id':'DP-1'}) as resolve:
                self.assertEqual(recorder._gsr_capture_target(rc),'DP-1');resolve.assert_called_once()
                with mock.patch('vice.recorder._gsr_prefix',return_value=['gpu-screen-recorder']),mock.patch('vice.recorder.asyncio.create_subprocess_exec',return_value=proc) as spawn:
                    await capture_screenshot(path,rc)
                resolve.assert_called_once()
                self.assertEqual(spawn.call_args.args,('gpu-screen-recorder','-w','DP-1','-o',str(path)))

    async def test_missing_gsr_never_writes_an_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shot.png'
            with mock.patch('vice.recorder._gsr_prefix',return_value=None):
                with self.assertRaisesRegex(RuntimeError,'not installed'):
                    await capture_screenshot(path,Config().recording)
            self.assertFalse(path.exists())
