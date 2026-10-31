"""Exact titles, stable media references and shared batch orchestration."""
import asyncio
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
try:
    import _sandbox
except ModuleNotFoundError:
    from tests import _sandbox
from vice import share, keys
from vice.config import Config
from vice.games import GameLibrary
from vice.jobs import ProcessingQueue
from vice.library import MediaLibrary, physical_target, rename_title


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cfg=Config();self.cfg.output.directory=str(self.root);self.cfg.output.image_directory=str(self.root)
        self.cfg.output.auto_playlist_by_game=True
        self.games=GameLibrary(self.root/'games.json')
        with mock.patch('vice.library.LIBRARY_PATH',self.root/'library.json'),mock.patch('vice.trash.TRASH_PATH',self.root/'trash.json'),mock.patch('vice.playlists.PLAYLISTS_PATH',self.root/'playlists.json'):
            self.server=share.ShareServer(self.cfg,games=self.games)
        self.server._jobs.path=self.root/'jobs.json'
        self.server.broadcast=mock.AsyncMock()
        patch=mock.patch('vice.share._ffprobe',new=mock.AsyncMock(return_value={'duration':4,'vcodec':'h264','width':1280,'height':720}));patch.start();self.addCleanup(patch.stop)
        patch=mock.patch('vice.share.probe_media',new=mock.AsyncMock(return_value={'width':1280,'height':720}));patch.start();self.addCleanup(patch.stop)
        self.paths=[]
        for name in ['First','Second','Third']:
            path=self.root/(name+'.mp4');path.write_bytes(name.encode());os.utime(path,ns=(1_000_000_000_123_456_789,)*2)
            self.server._clips[name]=path;self.paths.append(path)
            self.server.library.ensure(path,'clip')
        self.server._ensure_share_tokens()
        self.ids=[self.server.library.ensure(path,'clip')['id'] for path in self.paths]
    async def asyncTearDown(self):
        await asyncio.sleep(.01);await self.server.stop()
    def request(self,body=None,**match):return SimpleNamespace(match_info=match,json=mock.AsyncMock(return_value=body))
    async def preview(self,mode,options,ids=None):
        return json.loads((await self.server._api_library_preview(self.request({'ids':ids or self.ids,'mode':mode,'options':options}))).text)
    async def action(self,action,ids=None,**extra):
        return json.loads((await self.server._api_library_actions(self.request({'action':action,'ids':ids or self.ids,'confirm':True,**extra}))).text)

    async def test_exact_linux_titles_keep_id_timestamp_views_tokens_memberships_and_editor_references(self):
        path=self.paths[0];stamp=path.stat().st_mtime_ns;mid=self.ids[0]
        self.server._views[path.stem]=7
        playlist=self.server.playlists.create_custom('Favorites');self.server.playlists.add_clip(playlist['id'],path.stem)
        game=self.games.create({'name':'Rocket League','rules':{'executables':['RocketLeague.exe']}})
        self.games.associate(path.stem,game['id'])
        token=self.server._share_tokens[path.stem]
        from vice.editor import PROJECT_PATH
        with mock.patch('vice.editor.PROJECT_PATH',self.root/'project.json'):
            self.server.editor_project.save({'version':1,'tracks':[{'id':'V1','type':'video','label':'V1'}],'items':[{'id':'v','kind':'clip','trackId':'V1','clipId':path.stem,'start':0,'dur':1,'offset':0}]})
            before=self.server._clip_json(path.stem,path,{})
            for title in ['What a save!','WTF???','Rocket League - Double Tap',"C'est incroyable !","Ça, c'était beau.",'Nice shot (1v2) [OT]','  Épatant 🎮  ']:
                updated=await self.server._rename_media('clip',path.stem,title)
                path=self.root/(title+'.mp4')
                self.assertEqual(updated['display_title'],title);self.assertEqual(updated['name'],title+'.mp4')
                self.assertEqual(updated['library_id'],mid);self.assertEqual(updated['views'],7)
                self.assertEqual(updated['video_url'],before['video_url']);self.assertEqual(path.read_bytes(),b'First')
                self.assertEqual(path.stat().st_mtime_ns,stamp);self.assertEqual(self.games.clips[title],game['id'])
                self.assertEqual(self.server._share_tokens[title],token);self.assertIn(title,self.server.playlists.get(playlist['id'])['clip_slugs'])
                self.assertEqual(self.server.editor_project.load()['items'][0]['clipId'],title)
            self.assertTrue(all(call.args[0]['type']!='clip_saved' for call in self.server.broadcast.call_args_list))

    async def test_impossible_filenames_keep_the_exact_display_title_and_original_path_across_restart(self):
        path=self.paths[0]
        for title in ['Rocket/League','nul\0title','.','..','../outside','長'*100]:
            updated=await self.server._rename_media('clip',path.stem,title)
            self.assertEqual(updated['display_title'],title);self.assertEqual(updated['name'],path.name);self.assertTrue(updated['metadata_only']);self.assertFalse(updated['physical_rename'])
            restarted=MediaLibrary(self.server.library.path)
            self.assertEqual(restarted.ensure(path,'clip')['id'],self.ids[0]);self.assertEqual(restarted.title(restarted.get(self.ids[0])),title)
        self.assertFalse((self.root.parent/'outside.mp4').exists())

    async def test_collisions_and_empty_titles_never_overwrite_files(self):
        for title in ['Second','']:
            with self.assertRaises(ValueError):await self.server._rename_media('clip','First',title)
        self.assertEqual(self.paths[0].read_bytes(),b'First');self.assertEqual(self.paths[1].read_bytes(),b'Second')
        with mock.patch('vice.library_api.move_exclusive',side_effect=FileExistsError()):
            with self.assertRaisesRegex(ValueError,'collision'):await self.server._rename_media('clip','First','new')
        self.assertIn('First',self.server._clips)

    async def test_rename_preserves_cached_thumbnail_video_audio_discord_and_keyframes(self):
        path=self.paths[0];old_revision=share.media_revision(path)
        files=[share._thumb_path(path),share._proxy_path(path),share._audio_preview_path(path,0),share._discord_path(path)]
        for i,cache in enumerate(files):cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(str(i).encode())
        info={'timestamps':[0,1.1,2.5]};self.server._keyframes._results[(path,old_revision)]=info
        updated=await self.server._rename_media('clip','First','First renamed')
        new=self.root/updated['name']
        targets=[share._thumb_path(new),share._proxy_path(new),share._audio_preview_path(new,0),share._discord_path(new)]
        self.assertEqual([p.read_bytes() for p in targets],[b'0',b'1',b'2',b'3'])
        with mock.patch('vice.keyframes.probe_keyframes',new=mock.AsyncMock()) as probe:
            self.assertEqual(await self.server._keyframes.get(new),info);probe.assert_not_called()

    async def test_images_use_the_same_exact_title_identity_and_rename_events(self):
        path=self.root/'Shot.png';path.write_bytes(b'image');self.server._images[path.stem]=path
        old=self.server._image_basic_json(path.stem,path)
        updated=await self.server._rename_media('image','Shot',"Ça, c'était beau.")
        self.assertEqual(updated['display_title'],"Ça, c'était beau.");self.assertEqual(updated['image_url'],old['image_url']);self.assertEqual(updated['library_id'],old['library_id'])
        event=next(call.args[0] for call in self.server.broadcast.call_args_list if call.args[0]['type']=='image_renamed')
        self.assertEqual(event['old_slug'],'Shot')

    async def test_clip_list_in_flight_during_rename_returns_current_identity_and_title(self):
        gate,probing=asyncio.Event(),asyncio.Event()
        async def held_probe(path):
            probing.set();await gate.wait()
            return {'duration':4,'vcodec':'h264'}
        with mock.patch('vice.share._ffprobe',new=held_probe),mock.patch('vice.share._make_thumb',new=mock.AsyncMock()):
            pending=asyncio.create_task(self.server._api_clips(None))
            await asyncio.wait_for(probing.wait(),2)
            await self.server._rename_media('clip','First','Renamed while loading!')
            gate.set();response=await asyncio.wait_for(pending,2)
        items=json.loads(response.text)['clips']
        self.assertEqual([item['library_id'] for item in items],self.ids)
        self.assertEqual(items[0]['display_title'],'Renamed while loading!')
        self.assertEqual(items[0]['duration'],4)
        self.assertNotIn('First',[item['slug'] for item in items])

    async def test_image_list_in_flight_during_rename_keeps_dimensions_and_current_title(self):
        path=self.root/'Shot.png';path.write_bytes(b'image');self.server._images['Shot']=path
        mid=self.server.library.ensure(path,'image')['id']
        gate,probing=asyncio.Event(),asyncio.Event()
        async def held_probe(path):
            probing.set();await gate.wait()
            return {'width':640,'height':480}
        with mock.patch('vice.share.probe_media',new=held_probe),mock.patch('vice.share._make_thumb',new=mock.AsyncMock()):
            pending=asyncio.create_task(self.server._api_images(None))
            await asyncio.wait_for(probing.wait(),2)
            await self.server._rename_media('image','Shot','Renamed screenshot!')
            gate.set();response=await asyncio.wait_for(pending,2)
        items=json.loads(response.text)['images']
        self.assertEqual(len(items),1);self.assertEqual(items[0]['library_id'],mid)
        self.assertEqual(items[0]['display_title'],'Renamed screenshot!')
        self.assertEqual((items[0]['width'],items[0]['height']),(640,480))

    async def test_preview_replace_prefix_suffix_number_and_pattern_match_applied_names(self):
        cases=[('replace',{'find':'i','replace':' ? '},['F ? rst','Second','Th ? rd']),('prefix',{'text':'🎮 '},['🎮 First','🎮 Second','🎮 Third']),('suffix',{'text':' !'},['First !','Second !','Third !']),('number',{'prefix':'Clip ','width':3,'start':2,'suffix':'?'},['Clip 002?','Clip 003?','Clip 004?']),('pattern',{'pattern':'{title} [{index:03d}] {date}','start':1},['First [001] 2001-09-09','Second [002] 2001-09-09','Third [003] 2001-09-09'])]
        for mode,options,expected in cases:
            result=await self.preview(mode,options);self.assertTrue(result['valid']);self.assertEqual([plan['title'] for plan in result['items']],expected)
        result=await self.preview('number',{'prefix':'Clip ','width':3,'start':2,'suffix':'?'})
        applied=await self.action('rename',plans=result['items'])
        self.assertTrue(all(item['ok'] for item in applied['results']))
        self.assertEqual([self.server.library.title(self.server.library.get(mid)) for mid in self.ids],['Clip 002?','Clip 003?','Clip 004?'])

    async def test_preview_and_apply_reject_duplicate_targets_before_any_change(self):
        result=await self.preview('pattern',{'pattern':'Same'})
        self.assertFalse(result['valid']);self.assertTrue(any(plan.get('code')=='collision' for plan in result['items']))
        # Even if a client ignores the preview, duplicate names cannot publish.
        applied=await self.action('rename',plans=result['items'])
        self.assertTrue(all(not item['ok'] for item in applied['results']));self.assertTrue(self.paths[0].exists())

    async def test_stale_preview_is_rejected_instead_of_changing_the_requested_names(self):
        result=await self.preview('prefix',{'text':'new '})
        await self.server._rename_media('clip','Second','Changed by another window')
        applied=await self.action('rename',plans=result['items'])
        self.assertTrue(all(not item['ok'] for item in applied['results']));self.assertTrue(self.paths[0].exists())

    async def test_external_content_change_invalidates_reviewed_rename_before_mutation(self):
        result=await self.preview('prefix',{'text':'new '})
        self.paths[0].write_bytes(b'Edited externally on the same inode')
        applied=await self.action('rename',plans=result['items'])
        self.assertTrue(all(not item['ok'] and item['code']=='changed' for item in applied['results']))
        self.assertTrue(all(path.exists() for path in self.paths))
        self.assertNotEqual(self.server.library.get(self.ids[0])['revision'],result['items'][0]['revision'])

    async def test_bulk_trash_reports_partial_failure_and_restore_preserves_exact_title_id(self):
        await self.server._rename_media('clip','First','Game / impossible filename')
        result=await self.action('trash',[self.ids[0],'missing-id',self.ids[1]])
        self.assertEqual([r['ok'] for r in result['results']],[True,False,True]);self.assertFalse(self.paths[0].exists())
        entries=list(self.server.trash.entries.values());self.assertEqual(len(entries),2)
        response=await self.server._api_trash_action(self.request({'action':'restore','ids':[e['id'] for e in entries]}))
        self.assertEqual(response.status,200)
        restored=self.server._clip_json('First',self.paths[0],{})
        self.assertEqual(restored['library_id'],self.ids[0]);self.assertEqual(restored['display_title'],'Game / impossible filename')
        self.assertTrue(all(call.args[0]['type']!='clip_saved' for call in self.server.broadcast.call_args_list))

    async def test_bulk_playlist_moves_and_game_assignment_do_not_move_or_rewrite_media(self):
        source=self.server.playlists.create_custom('From');target=self.server.playlists.create_custom('To')
        for path in self.paths:self.server.playlists.add_clip(source['id'],path.stem)
        result=await self.action('playlist-move',playlist_id=target['id'],source_playlist_id=source['id'])
        self.assertTrue(all(r['ok'] for r in result['results']));self.assertEqual(self.server.playlists.get(source['id'])['clip_slugs'],[])
        game=self.games.create({'name':'Rocket League','rules':{'executables':['RocketLeague.exe']}})
        await self.action('game',game_id=game['id'])
        self.assertTrue(all(self.games.clips[path.stem]==game['id'] for path in self.paths))
        auto=next(p for p in self.server.playlists.list_playlists() if p.get('game_id')==game['id'])
        self.assertEqual(len(auto['clip_slugs']),3)
        await self.action('game',game_id=None)
        self.assertTrue(all(path.stem not in self.games.clips for path in self.paths))
        self.assertEqual(len(self.server.playlists.get(target['id'])['clip_slugs']),3)
        for path in self.paths:self.assertEqual(path.stat().st_mtime_ns,1_000_000_000_123_456_789)

    async def test_queued_job_identity_survives_reopening_and_blocks_unsafe_physical_rename(self):
        queue=self.server._jobs;queue.start=mock.Mock()
        job=await queue.submit('trim','First.mp4',{'slug':'First'},source_revision=share.media_revision(self.paths[0]),source_media_ids=[self.ids[0]],mode='replace')
        with self.assertRaisesRegex(ValueError,'busy'):await self.server._rename_media('clip','First','new physical name')
        await self.server._rename_media('clip','First','new / display title')
        reopened=ProcessingQueue(mock.AsyncMock(),mock.AsyncMock(),path=queue.path)
        self.assertEqual(reopened.snapshot()[0]['source_media_ids'],[self.ids[0]])
        self.assertEqual(reopened.snapshot()[0]['status'],'queued');self.assertEqual(reopened.snapshot()[0]['mode'],'replace')
        self.assertEqual(reopened.snapshot()[0]['id'],job['id'])

    async def test_replacement_trim_keeps_id_and_historical_date_but_refreshes_content_urls(self):
        before=self.server._clip_json('First',self.paths[0],{})
        async def spawn(*args,**kwargs):
            Path(args[-1]).write_bytes(b'trimmed bytes');return SimpleNamespace(returncode=0,communicate=mock.AsyncMock(return_value=(b'',b'')))
        with mock.patch('vice.share.asyncio.create_subprocess_exec',side_effect=spawn),mock.patch('vice.share._trim_result_problem',new=mock.AsyncMock(return_value=None)):
            response=await self.server._api_trim(self.request({'start':0,'end':1,'copy':False},slug='First'))
        self.assertTrue(json.loads(response.text)['ok']);after=self.server._clip_json('First',self.paths[0],{})
        self.assertEqual(after['library_id'],before['library_id']);self.assertNotEqual(after['video_url'],before['video_url']);self.assertEqual(after['created_at'],before['created_at'])

    async def test_fresh_recording_under_reused_filename_gets_new_id_and_drops_old_title(self):
        await self.server._rename_media('clip','First','old / display')
        self.paths[0].write_bytes(b'new recording');self.server.add_clip(self.paths[0])
        after=self.server._clip_json('First',self.paths[0],{})
        self.assertNotEqual(after['library_id'],self.ids[0]);self.assertEqual(after['display_title'],'First')
        with self.assertRaises(ValueError):self.server._library_source(self.ids[0])

    async def test_stable_local_urls_and_public_token_survive_unicode_rename(self):
        from aiohttp.test_utils import TestClient,TestServer
        client=TestClient(TestServer(self.server._local_app));await client.start_server();self.addAsyncCleanup(client.close)
        before=self.server._clip_json('First',self.paths[0],{})
        response=await client.get(before['video_url']);self.assertEqual(await response.read(),b'First')
        await self.server._rename_media('clip','First',"Ça? A #1 + 2%")
        response=await client.get(before['video_url']);self.assertEqual(response.status,200);self.assertEqual(await response.read(),b'First')
        self.assertEqual(response.headers['Cache-Control'],'no-cache')
        path=self.root/"Ça? A #1 + 2%.mp4";after=self.server._clip_json(path.stem,path,{})
        self.assertEqual(before['share_url'],after['share_url'])

    async def test_pattern_injection_and_malformed_titles_are_rejected(self):
        for pattern in ['{title.__class__}','{index:100000d}','{index!r}','{unknown}']:
            result=await self.preview('pattern',{'pattern':pattern});self.assertFalse(result['valid'])
        for title in [None,1,{},'a'*4097]:
            with self.assertRaises(ValueError):physical_target(self.paths[0],title)

    async def test_corrupt_metadata_is_preserved_and_does_not_rewrite_recordings(self):
        for i,invalid in enumerate(['not json','[]','{"version":1,"media":{"bad":null}}']):
            path=self.root/f'broken-{i}.json';path.write_text(invalid)
            library=MediaLibrary(path);library.ensure(self.paths[0],'clip')
            backups=list(self.root.glob(f'{path.name}.invalid-*'));self.assertEqual(backups[0].read_text(),invalid)
            self.assertEqual(self.paths[0].read_bytes(),b'First');self.assertEqual(path.stat().st_mode&0o777,0o600)

    async def test_maximum_length_linux_names_preserve_titles_and_use_bounded_internal_cache_names(self):
        path=self.paths[0]
        keys.save_sidecar('First',[[0,1,'SPACE']]);share._save_highlights('First',[{'id':'1','time':.5,'label':'Win'}])
        cache=share._thumb_path(path);cache.parent.mkdir(exist_ok=True,parents=True);cache.write_bytes(b'thumb')
        title='é'*125+'a'  # 251 UTF-8 bytes, plus .mp4 = Linux NAME_MAX.
        result=await self.server._rename_media('clip','First',title)
        target=self.root/result['name'];self.assertTrue(target.is_file());self.assertEqual(result['display_title'],title)
        self.assertEqual(share._thumb_path(target).read_bytes(),b'thumb');self.assertEqual(keys.load_sidecar(title),[[0,1,'SPACE']])
        self.assertEqual(share._load_highlights(title)[0]['label'],'Win')
        for internal in [share._thumb_path(target),share._proxy_path(target),share._audio_preview_path(target,0),keys.sidecar_path(title),share._highlight_path(title)]:
            self.assertLessEqual(len(internal.name.encode()),255)

    async def test_full_selection_validation_rejects_malformed_batch_requests(self):
        for body in [[],{'ids':[{}],'mode':'prefix'}, {'ids':self.ids,'mode':'prefix','options':[]}, {'ids':self.ids,'mode':'prefix','options':{'text':None}}, {'action':'trash','ids':['id'],'plans':[{}],'confirm':True}]:
            response=await (self.server._api_library_actions(self.request(body)) if isinstance(body,dict) and 'action' in body else self.server._api_library_preview(self.request(body)))
            self.assertEqual(response.status,400)

    async def test_detected_games_assignment_accepts_stable_ids_after_physical_rename(self):
        game=self.games.create({'name':'Rocket League','rules':{'executables':['RocketLeague.exe']}})
        await self.server._rename_media('clip','First','Renamed elsewhere!')
        response=await self.server._api_game_assign(self.request({'media_ids':[self.ids[0]],'confirm':True},gid=game['id']))
        self.assertEqual(response.status,200);self.assertEqual(self.games.clips['Renamed elsewhere!'],game['id'])

    async def test_legal_reserved_prefix_filenames_never_collide_with_image_membership(self):
        image=self.root/'photo.png';image.write_bytes(b'image');self.server._images['photo']=image
        self.server.library.ensure(image,'image')
        playlist=self.server.playlists.create_custom('Mixed');self.server.playlists.add_clip(playlist['id'],'img:photo');self.server.playlists.add_clip(playlist['id'],'First')
        keys.save_sidecar('First',[[0,1,'SPACE']])
        updated=await self.server._rename_media('clip','First','img:photo')
        self.assertEqual(updated['name'],'img:photo.mp4');self.assertEqual(updated['display_title'],'img:photo');self.assertEqual(updated['library_id'],self.ids[0]);self.assertNotEqual(updated['slug'],'img:photo')
        members=self.server.playlists.get(playlist['id'])['clip_slugs'];self.assertIn('img:photo',members);self.assertIn(updated['slug'],members)
        self.assertEqual(keys.load_sidecar(updated['slug']),[[0,1,'SPACE']]);self.assertEqual(self.server._images['photo'],image)
        trashed=await self.action('trash',[self.ids[0]]);self.assertTrue(trashed['results'][0]['ok']);self.assertNotIn(updated['slug'],self.server._clips)
        response=await self.server._api_trash_action(self.request({'action':'restore','ids':list(self.server.trash.entries)}));self.assertEqual(response.status,200)
        self.assertIn(updated['slug'],self.server._clips);self.assertIn('img:photo',self.server.playlists.get(playlist['id'])['clip_slugs'])
        self.assertIn(updated['slug'],self.server.playlists.get(playlist['id'])['clip_slugs'])
