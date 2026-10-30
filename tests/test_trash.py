import asyncio
import errno
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import _sandbox  # noqa
except ModuleNotFoundError:
    from tests import _sandbox  # noqa

from vice.trash import TrashError, TrashStore, identity
from vice.config import Config
from vice.games import GameLibrary
from vice import share, keys


class TrashStoreTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name);self.source=self.root/'Été #1.mp4';self.source.write_bytes(b'original media'*100)
        self.stamp=1_000_000_000_123_456_789;os.utime(self.source,ns=(self.stamp,self.stamp))
        self.clock=1_700_000_000*10**9
        self.store=TrashStore(self.root/'index.json',clock=lambda:self.clock)

    def move(self):
        entry=self.store.move(self.source,'clip',{'game':'Game','views':5})
        self.store.commit(entry);return entry

    def test_move_and_restore_preserve_bytes_nanoseconds_and_inode_without_copying(self):
        before=identity(self.source);digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        with mock.patch('vice.trash.shutil.copyfileobj',side_effect=AssertionError('Large media must not be copied')):
            entry=self.move();self.assertFalse(self.source.exists())
            self.assertEqual(identity(self.store.media(entry)),before)
            target=self.store.restore_file(entry)
        self.assertEqual(target,self.source);self.assertEqual(identity(target),before)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),digest)
        self.store.discard(entry,restored=True);self.assertTrue(target.exists());self.assertFalse(self.store.entries)
        self.assertEqual(self.store.path.stat().st_mode&0o777,0o600)

    def test_retention_uses_deletion_time_at_exact_boundary_and_never_is_permanent(self):
        entry=self.move();self.clock+=7*86400*10**9-1
        self.assertEqual(self.store.expired(7),[])
        self.assertGreater(self.store.snapshot(7)[0]['remaining_seconds'],0)
        self.clock+=1;self.assertEqual(self.store.expired(7),[entry['id']])
        self.assertEqual(self.store.expired(30),[])
        self.clock+=1000*86400*10**9;self.assertEqual(self.store.expired(0),[])
        self.assertIsNone(self.store.snapshot(0)[0]['remaining_seconds'])

    def test_filename_collision_and_reserved_library_slug_never_overwrite(self):
        entry=self.move();self.source.write_bytes(b'new recording')
        target=self.store.restore_file(entry,reserved={self.source.stem+' (restored 1)'})
        self.assertEqual(target.name,'Été #1 (restored 2).mp4')
        self.assertEqual(self.source.read_bytes(),b'new recording')
        self.assertEqual(target.stat().st_mtime_ns,self.stamp)

    def test_failed_move_leaves_source_and_metadata_untouched(self):
        with mock.patch.object(Path,'rename',side_effect=PermissionError('read only')):
            with self.assertRaises(PermissionError):self.move()
        self.assertTrue(self.source.exists());self.assertEqual(self.source.stat().st_mtime_ns,self.stamp)
        self.assertEqual(self.store.entries,{})

    def test_disconnected_storage_keeps_entry_and_can_be_reconnected(self):
        media_dir=self.root/'disk';media_dir.mkdir();self.source=self.source.rename(media_dir/self.source.name)
        entry=self.move();offline=self.root/'disconnected';media_dir.rename(offline)
        self.assertFalse(self.store.snapshot()[0]['available'])
        with self.assertRaises(TrashError):self.store.discard(entry)
        self.assertIn(entry['id'],self.store.entries)
        offline.rename(media_dir);self.store.discard(entry);self.assertNotIn(entry['id'],self.store.entries)

    def test_explicit_cross_disk_restore_copies_once_and_preserves_precision(self):
        entry=self.move();dest=self.root/'other';dest.mkdir()
        from vice.trash import move_exclusive
        calls=0
        def cross(source,target):
            nonlocal calls
            calls+=1
            if calls==1:raise OSError(errno.EXDEV,'different disk')
            return move_exclusive(source,target)
        with mock.patch('vice.trash.move_exclusive',side_effect=cross):
            target=self.store.restore_file(entry,dest)
        self.assertEqual(target.read_bytes(),b'original media'*100)
        self.assertEqual(target.stat().st_mtime_ns,self.stamp)
        self.assertFalse(self.store.media(entry).exists())

    def test_symlinks_and_unexpected_files_are_never_recursively_deleted(self):
        entry=self.move();outside=self.root/'outside';outside.write_bytes(b'keep')
        payload=self.store.media(entry);payload.unlink();payload.symlink_to(outside)
        with self.assertRaises(TrashError):self.store.discard(entry)
        self.assertEqual(outside.read_bytes(),b'keep')
        payload.unlink();payload.write_bytes(b'media')
        unknown=payload.parent/'unrelated.txt';unknown.write_bytes(b'keep too')
        with self.assertRaises(OSError):self.store.discard(entry)
        self.assertEqual(unknown.read_bytes(),b'keep too')
        with self.assertRaises(TrashError):self.store.get('../outside')

    def test_corrupt_index_is_not_overwritten(self):
        self.store.path.write_text('{damaged')
        with self.assertLogs('vice.trash',level='ERROR'):restored=TrashStore(self.store.path)
        with self.assertRaises(TrashError):restored.move(self.source,'clip',{})
        self.assertTrue(self.source.exists());self.assertEqual(self.store.path.read_text(),'{damaged')


class TrashApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);self.root=Path(directory.name)
        from vice import playlists, jobs, editor, trash
        targets={share:{'VIEWS_PATH':self.root/'views.json','SHARE_TOKENS_PATH':self.root/'tokens.json','THUMB_DIR':self.root/'thumbs','PROXY_DIR':self.root/'proxies','HIGHLIGHTS_DIR':self.root/'highlights'},keys:{'KEYS_DIR':self.root/'keys'},playlists:{'PLAYLISTS_PATH':self.root/'playlists.json'},jobs:{'JOBS_PATH':self.root/'jobs.json'},editor:{'PROJECT_PATH':self.root/'editor.json'},trash:{'TRASH_PATH':self.root/'trash.json'}}
        for module,values in targets.items():
            patch=mock.patch.multiple(module,**values);patch.start();self.addCleanup(patch.stop)
        cfg=Config();cfg.output.directory=str(self.root);cfg.output.image_directory=str(self.root)
        self.server=share.ShareServer(cfg,games=GameLibrary(self.root/'games.json'))
        self.server.broadcast=mock.AsyncMock()
        self.source=self.root/'old.mp4';self.source.write_bytes(b'original movie')
        self.stamp=1_000_000_000_123_456_789;os.utime(self.source,ns=(self.stamp,self.stamp))
        self.server._clips['old']=self.source
        self.server._meta['old']={'duration':10,'width':640,'height':360,'vcodec':'h264'}
        self.game=self.server.games.create({'name':'Game','rules':{'executables':['game.exe']}})
        self.server.games.associate('old',self.game['id'])
        self.server.playlists.record_auto('Game','old',game_id=self.game['id'])
        self.custom=self.server.playlists.create_custom('Keep membership');self.server.playlists.add_clip(self.custom['id'],'old')
        self.server._views['old']=12;self.old_token=self.server._issue_share_token('old')
        self.server.editor_project.save({'version':1,'tracks':[],'items':[{'id':'item','clipId':'old','start':3,'dur':4}]})
        keys.KEYS_DIR.mkdir();keys.sidecar_path('old').write_text('{"keys":"original"}')
        share.HIGHLIGHTS_DIR.mkdir();(share.HIGHLIGHTS_DIR/'old.json').write_text('[{"id":"1","time":4}]')
        share.THUMB_DIR.mkdir();share._thumb_path(self.source).write_bytes(b'cached jpeg')
    async def asyncTearDown(self):await self.server.stop()

    def request(self,body=None,**match):return SimpleNamespace(match_info=match,json=mock.AsyncMock(return_value=body))
    async def delete(self):
        response=await self.server._api_delete(self.request(slug='old'))
        self.assertEqual(response.status,200,response.text)
        return json.loads(response.text)['trash_id']
    async def action(self,action,ids,**options):
        response=await self.server._api_trash_action(self.request({'action':action,'ids':ids,**options}))
        self.assertEqual(response.status,200,response.text)
        return json.loads(response.text)

    async def test_clip_restore_keeps_all_metadata_and_rotates_public_tokens(self):
        original_project=self.server.editor_project.load();tid=await self.delete()
        self.assertNotIn('old',self.server._clips);self.assertNotIn(self.old_token,self.server._share_slugs)
        self.assertFalse(self.source.exists());self.assertIsNone(self.server.games.game_for('old'))
        self.assertFalse(any('old' in p['clip_slugs'] for p in self.server.playlists.list_playlists()))
        self.assertEqual(self.server.editor_project.load()['items'][0]['clipId'],f'trash:{tid}')
        self.assertEqual(self.server.trash.snapshot()[0]['game'],'Game')
        result=await self.action('restore',[tid]);self.assertTrue(result['ok'],result)
        self.assertEqual(self.source.read_bytes(),b'original movie');self.assertEqual(self.source.stat().st_mtime_ns,self.stamp)
        self.assertEqual(self.server._views['old'],12);self.assertEqual(self.server.games.clips['old'],self.game['id'])
        self.assertIn('old',self.server.playlists.get(self.custom['id'])['clip_slugs'])
        self.assertEqual(keys.sidecar_path('old').read_text(),'{"keys":"original"}')
        self.assertEqual(json.loads((share.HIGHLIGHTS_DIR/'old.json').read_text())[0]['time'],4)
        self.assertEqual(self.server.editor_project.load(),original_project)
        self.assertNotEqual(self.server._share_tokens['old'],self.old_token)
        self.assertNotIn(self.old_token,self.server._share_slugs)

    async def test_editor_tombstone_survives_stale_autosave_and_collision(self):
        project=self.server.editor_project.load();tid=await self.delete()
        response=await self.server._api_editor_save_project(self.request(project));self.assertEqual(response.status,200)
        self.source.write_bytes(b'unrelated new recording');self.server._clips['old']=self.source
        result=await self.action('restore',[tid]);self.assertTrue(result['ok'],result)
        restored=self.server.editor_project.load()['items'][0]['clipId']
        self.assertNotEqual(restored,'old');self.assertIn(restored,self.server._clips)
        self.assertEqual(self.source.read_bytes(),b'unrelated new recording')
        self.assertEqual(self.server._clips[restored].read_bytes(),b'original movie')

    async def test_jobs_and_active_encoders_block_deletion_without_changing_source(self):
        self.server._jobs.jobs=[{'status':'queued','payload':{'slug':'old'}}]
        response=await self.server._api_delete(self.request(slug='old'));self.assertEqual(response.status,409)
        self.assertEqual(self.server.trash.entries,{})
        self.server._jobs.jobs=[]
        async with self.server._proxy_lock:
            response=await self.server._api_delete(self.request(slug='old'));self.assertEqual(response.status,409)
        self.assertTrue(self.source.exists());self.assertEqual(self.server._views['old'],12)

    async def test_images_use_same_trash_and_bulk_purge_requires_explicit_confirmation(self):
        image=self.root/'shot.png';image.write_bytes(b'image');os.utime(image,ns=(self.stamp,self.stamp));self.server._images['shot']=image
        self.server.games.associate('img:shot',self.game['id']);self.server.playlists.add_clip(self.custom['id'],'img:shot')
        response=await self.server._api_image_delete(self.request(slug='shot'));self.assertEqual(response.status,200,response.text)
        image_id=json.loads(response.text)['trash_id'];clip_id=await self.delete()
        response=await self.server._api_trash_action(self.request({'action':'purge','all':True}));self.assertEqual(response.status,400)
        self.assertEqual(len(self.server.trash.entries),2)
        restored=await self.action('restore',[image_id]);self.assertTrue(restored['ok'],restored)
        self.assertEqual(image.stat().st_mtime_ns,self.stamp);self.assertEqual(self.server.games.clips['img:shot'],self.game['id'])
        purged=await self.action('purge',[clip_id],confirm=True);self.assertTrue(purged['ok'],purged)
        self.assertEqual(self.server.trash.entries,{})
        self.assertEqual(self.server.editor_project.load()['items'],[])

    async def test_restart_replays_move_and_restore_after_interruption(self):
        real_commit=self.server.trash.commit
        with mock.patch.object(self.server.trash,'commit',side_effect=OSError('interrupted')):
            response=await self.server._api_delete(self.request(slug='old'));self.assertEqual(response.status,409)
        path=self.server.trash.path;self.server.trash=TrashStore(path)
        await self.server._recover_trash();entry=next(iter(self.server.trash.entries.values()))
        self.assertEqual(entry['state'],'trashed');self.assertFalse(self.source.exists())
        with mock.patch.object(self.server,'_trash_restore_metadata',side_effect=OSError('interrupted')):
            result=await self.action('restore',[entry['id']]);self.assertFalse(result['ok'])
        self.assertTrue(self.source.exists())
        self.server.trash=TrashStore(path);await self.server._recover_trash()
        self.assertEqual(self.server.trash.entries,{})
        self.assertEqual(self.server._views['old'],12);self.assertIn('old',self.server._clips)
        self.assertEqual(self.source.stat().st_mtime_ns,self.stamp)

    async def test_daemon_expiration_without_ui_and_never_policy(self):
        tid=await self.delete();entry=self.server.trash.get(tid)
        self.server.trash.clock=lambda:entry['deleted_at_ns']+31*86400*10**9
        self.server.cfg.output.trash_retention_days=0
        task=asyncio.create_task(self.server._trash_cleanup_loop());await asyncio.sleep(.01)
        self.assertIn(tid,self.server.trash.entries)
        self.server.cfg.output.trash_retention_days=30;self.server._trash_wakeup.set();await asyncio.sleep(.01)
        self.assertNotIn(tid,self.server.trash.entries)
        task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_public_endpoints_and_unavailable_destination_with_explicit_alternative(self):
        from aiohttp.test_utils import TestClient, TestServer
        tid=await self.delete();entry=self.server.trash.get(tid)
        public=TestClient(TestServer(self.server._public_app));await public.start_server()
        try:
            self.assertEqual((await public.get(f'/v/{self.old_token}')).status,404)
            self.assertEqual((await public.get('/api/trash')).status,404)
            self.assertEqual((await public.get(f'/api/trash/{tid}/thumbnail')).status,404)
        finally:await public.close()
        current=self.root/'current';current.mkdir();self.server.cfg.output.directory=str(current)
        real_isdir=Path.is_dir
        with mock.patch.object(Path,'is_dir',lambda path:False if path==self.root else real_isdir(path)):
            result=await self.action('restore',[tid]);self.assertEqual(result['results'][0]['code'],'destination')
        result=await self.action('restore',[tid],destination='library');self.assertTrue(result['ok'],result)
        self.assertTrue((current/'old.mp4').is_file())
        self.assertIn(str(current/'old.mp4'),TrashStore(self.server.trash.path).restored_paths)

    async def test_delayed_image_thumbnail_cannot_reinsert_a_trashed_screenshot(self):
        image=self.root/'shot.png';image.write_bytes(b'image');self.server._images['shot']=image
        entered,release=asyncio.Event(),asyncio.Event()
        async def thumbnail(*args,**kwargs):entered.set();await release.wait()
        with mock.patch('vice.share._make_thumb',side_effect=thumbnail):
            task=asyncio.create_task(self.server._broadcast_image('shot',image));await entered.wait()
            result=await self.server._api_image_delete(self.request(slug='shot'));self.assertEqual(result.status,200)
            release.set();await task
        self.assertFalse(any(call.args[0].get('type')=='image_saved' for call in self.server.broadcast.call_args_list))

    async def test_headless_cleanup_works_with_sharing_disabled(self):
        from vice.main import ViceDaemon
        tid=await self.delete();self.server.trash.get(tid)['deleted_at_ns']-=31*86400*10**9;self.server.trash.save()
        daemon=ViceDaemon.__new__(ViceDaemon);daemon.cfg=self.server.cfg;daemon.cfg.sharing.enabled=False
        task=asyncio.create_task(daemon._headless_trash_cleanup());await asyncio.sleep(.01)
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertNotIn(tid,TrashStore(self.server.trash.path).entries)

    async def test_invalid_retention_is_rejected_without_changing_config(self):
        response=await self.server._api_set_config(self.request({'output':{'trash_retention_days':-1}}))
        self.assertEqual(response.status,400);self.assertEqual(self.server.cfg.output.trash_retention_days,30)

    async def test_bulk_restore_continues_after_one_unavailable_item(self):
        tid=await self.delete();image=self.root/'shot.png';image.write_bytes(b'image');self.server._images['shot']=image
        response=await self.server._api_image_delete(self.request(slug='shot'));image_id=json.loads(response.text)['trash_id']
        self.server.trash.media(self.server.trash.get(tid)).unlink()
        result=await self.action('restore',[tid,image_id]);self.assertFalse(result['ok'])
        self.assertFalse(result['results'][0]['ok']);self.assertTrue(result['results'][1]['ok']);self.assertTrue(image.exists())
        self.assertIn(tid,self.server.trash.entries)

    async def test_crash_before_rename_rolls_back_journal_without_detaching_source(self):
        with mock.patch.object(Path,'rename',side_effect=SystemExit('crash before filesystem move')):
            with self.assertRaises(SystemExit):self.server.trash.move(self.source,'clip',{})
        self.server.trash=TrashStore(self.server.trash.path);await self.server._recover_trash()
        self.assertEqual(self.server.trash.entries,{})
        self.assertTrue(self.source.is_file());self.assertEqual(self.server._views['old'],12)
        self.assertEqual(self.server.games.clips['old'],self.game['id']);self.assertEqual(self.server._share_tokens['old'],self.old_token)

    async def test_cancelled_cross_filesystem_restore_keeps_original_and_cleans_partial(self):
        import threading
        tid=await self.delete();entry=self.server.trash.get(tid);destination=self.root/'alternative';destination.mkdir()
        stop=threading.Event();stop.set()
        with mock.patch('vice.trash.move_exclusive',side_effect=OSError(errno.EXDEV,'different disk')):
            with self.assertRaises(TrashError):self.server.trash.restore_file(entry,destination,stop=stop)
        self.assertEqual(self.server.trash.media(entry).read_bytes(),b'original movie')
        self.assertFalse((destination/'old.mp4').exists());self.assertEqual(list(destination.iterdir()),[])
        self.server.trash=TrashStore(self.server.trash.path);await self.server._recover_trash()
        self.assertEqual(self.server.trash.get(tid)['state'],'trashed')

    async def test_stale_editor_export_cannot_use_a_replacement_recording(self):
        project={'version':1,'tracks':[{'id':'V1','type':'video','label':'V1'},{'id':'T1','type':'text','label':'T1'}],
                 'items':[{'id':'item','kind':'clip','trackId':'V1','clipId':'old','start':0,'dur':2,'offset':0}]}
        self.server.editor_project.save(project);await self.delete()
        self.source.write_bytes(b'unrelated recording');self.server._clips['old']=self.source
        self.server._meta['old']={'duration':10,'width':640,'height':360,'vcodec':'h264','audio_streams':0}
        response=await self.server._api_editor_export(self.request({'project':project,'background':True}))
        self.assertEqual(response.status,400,response.text)
        self.assertTrue(any('missing' in error for error in json.loads(response.text)['errors']))
        self.assertEqual(self.server._jobs.jobs,[]);self.assertEqual(self.source.read_bytes(),b'unrelated recording')

    async def test_legacy_export_preparing_for_encoder_blocks_source_move(self):
        waiting=asyncio.create_task(asyncio.Event().wait())
        self.server._exports._task=waiting
        try:
            response=await self.server._api_delete(self.request(slug='old'))
            self.assertEqual(response.status,409)
            self.assertTrue(self.source.exists());self.assertEqual(self.server.trash.entries,{})
        finally:
            waiting.cancel();await asyncio.gather(waiting,return_exceptions=True)
            self.server._exports._task=None
