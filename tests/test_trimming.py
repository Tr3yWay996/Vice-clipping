"""Timestamp and cache regressions for trimming; no desktop or GPU required."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import _sandbox  # noqa: F401
except ModuleNotFoundError:
    from tests import _sandbox  # noqa: F401

from vice import share
from vice.config import Config
from vice.media import media_revision


class TrimTimestampTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'old.mp4'
        self.source.write_bytes(b'original')
        self.timestamp = 1_000_000_000_123_456_789
        os.utime(self.source, ns=(self.timestamp, self.timestamp))
        self.before = self.source.stat()
        cfg = Config()
        cfg.output.directory = str(self.root)
        self.server = share.ShareServer(cfg)
        self.server._clips['old'] = self.source
        self.server._meta['old'] = {'duration': 9, 'vcodec': 'h264'}
        self.req = mock.Mock(match_info={'slug': 'old'})
        self.req.json = mock.AsyncMock(return_value={'start': 1, 'end': 3})
        self.commands = []
        self.fail = False

        async def spawn(*cmd, **kwargs):
            self.commands.append(cmd)
            Path(cmd[-1]).write_bytes(b'newvideo')  # deliberately SAME size
            return mock.Mock(returncode=1 if self.fail else 0,
                             communicate=mock.AsyncMock(return_value=(b'', b'failed' if self.fail else b'')))

        patches = [
            mock.patch.object(asyncio, 'create_subprocess_exec', spawn),
            mock.patch.object(share, '_trim_result_problem', mock.AsyncMock(return_value=None)),
            mock.patch.object(share, '_trim_encoder_candidates', return_value=['libx264']),
            mock.patch.object(share, '_video_bitrate', mock.AsyncMock(return_value=None)),
            mock.patch.object(share, 'THUMB_DIR', self.root / 'thumbs'),
            mock.patch.object(share, 'PROXY_DIR', self.root / 'proxies'),
            mock.patch.object(self.server, '_broadcast_clip', mock.AsyncMock()),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    async def trim(self):
        return json.loads((await self.server._api_trim(self.req)).text)

    async def test_replacement_preserves_nanoseconds_and_invalidates_every_cache(self):
        old_revision = media_revision(self.source)
        before_json = self.server._clip_json('old', self.source, {})
        thumb, proxy = share._thumb_path(self.source), share._proxy_path(self.source)
        discord = share._discord_path(self.source)
        audio = share._audio_preview_path(self.source, 1)
        for cache in [thumb, proxy, discord, audio]:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(b'stale')
        self.server._keyframes._results[(self.source, old_revision)] = {'timestamps': [0, 2]}
        self.assertTrue((await self.trim())['ok'])
        self.assertEqual(self.source.stat().st_mtime_ns, self.before.st_mtime_ns)
        self.assertEqual(self.source.stat().st_atime_ns, self.before.st_atime_ns)
        self.assertNotEqual(media_revision(self.source), old_revision)
        self.assertEqual(self.source.read_bytes(), b'newvideo')
        self.assertTrue(all(not c.exists() for c in [thumb, proxy, discord, audio]))
        self.assertNotIn('old', self.server._meta)
        self.assertFalse(self.server._keyframes._results)
        after_json = self.server._clip_json('old', self.source, {})
        self.assertEqual(after_json['created_at'], before_json['created_at'])
        self.assertNotEqual(after_json['video_url'], before_json['video_url'])
        self.assertIn('copy', self.commands[0])

    async def test_copy_inherits_timestamp_and_leaves_source_and_caches_alone(self):
        self.req.json.return_value['copy'] = True
        thumb = share._thumb_path(self.source)
        thumb.parent.mkdir(parents=True)
        thumb.write_bytes(b'valid')
        with mock.patch.object(self.server, 'add_clip'):
            result = await self.trim()
        self.assertTrue(result['ok'])
        target = self.root / (result['slug'] + '.mp4')
        self.assertEqual(target.stat().st_mtime_ns, self.before.st_mtime_ns)
        self.assertEqual(self.source.stat().st_mtime_ns, self.before.st_mtime_ns)
        self.assertEqual(self.source.read_bytes(), b'original')
        self.assertEqual(thumb.read_bytes(), b'valid')
        self.assertIn('old', self.server._meta)

    async def test_failed_encoding_keeps_source_metadata_and_removes_partial_file(self):
        self.fail = True
        result = await self.trim()
        self.assertFalse(result['ok'])
        self.assertEqual(self.source.stat().st_mtime_ns, self.before.st_mtime_ns)
        self.assertEqual(self.source.stat().st_ino, self.before.st_ino)
        self.assertEqual(self.source.read_bytes(), b'original')
        self.assertFalse(list(self.root.glob('*.trimming.*')))

    async def test_timestamp_restore_failure_does_not_publish(self):
        with mock.patch.object(os, 'utime', side_effect=OSError('timestamp failed')):
            result = await self.trim()
        self.assertFalse(result['ok'])
        self.assertEqual(self.source.stat().st_mtime_ns, self.before.st_mtime_ns)
        self.assertEqual(self.source.read_bytes(), b'original')
        self.assertFalse(list(self.root.glob('*.trimming.*')))

    async def test_trim_does_not_change_chronological_gallery_order(self):
        newer = self.root / 'newer.mp4'
        newer.write_bytes(b'new')
        os.utime(newer, ns=(self.timestamp + 20_000_000_000,) * 2)
        self.server._clips['newer'] = newer
        await self.trim()
        with mock.patch.object(share, '_make_thumb', mock.AsyncMock()), \
             mock.patch.object(self.server, '_get_meta', mock.AsyncMock(return_value={})):
            clips = json.loads((await self.server._api_clips(None)).text)['clips']
        self.assertEqual([c['slug'] for c in clips], ['newer', 'old'])

    async def test_copy_validation_failure_falls_back_without_dropping_audio(self):
        with mock.patch.object(share, '_trim_result_problem', mock.AsyncMock(side_effect=['bad GOP', None])):
            self.assertTrue((await self.trim())['ok'])
        self.assertEqual(len(self.commands), 2)
        self.assertIn('libx264', self.commands[1])
        self.assertIn('-map', self.commands[1])
        audio = self.commands[1].index('-c:a')
        self.assertEqual(self.commands[1][audio + 1], 'copy')


class RealTrimAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_reencoding_preserves_source_codec_and_each_recorded_audio_track(self):
        import shutil
        import subprocess
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('FFmpeg is not installed')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for encoder, codec in [('libx264', 'h264'), ('libx265', 'hevc')]:
                with self.subTest(codec=codec):
                    path = root / f'{codec}.mp4'
                    extra = ['-x265-params', 'pools=1:frame-threads=1:log-level=error'] if codec == 'hevc' else []
                    subprocess.run([
                        'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=10:duration=3',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
                        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=3',
                        '-map', '0:v', '-map', '1:a', '-map', '2:a',
                        '-c:v', encoder, '-threads', '1', *extra, '-g', '100', '-c:a', 'aac', str(path),
                    ], check=True, capture_output=True, timeout=30)
                    timestamp = 1_000_000_000_123_456_789
                    os.utime(path, ns=(timestamp, timestamp))
                    cfg = Config()
                    cfg.output.directory = str(root)
                    server = share.ShareServer(cfg)
                    server._clips[codec] = path
                    request = mock.Mock(match_info={'slug': codec})
                    request.json = mock.AsyncMock(return_value={'start': .5, 'end': 2})
                    with mock.patch.object(share, '_trim_encoder_candidates', return_value=[encoder]), \
                         mock.patch.object(server, '_broadcast_clip', mock.AsyncMock()), \
                         mock.patch.object(share, '_trim_result_problem', mock.AsyncMock(side_effect=['unsafe GOP', None])):
                        response = await server._api_trim(request)
                    self.assertTrue(json.loads(response.text)['ok'], response.text)
                    self.assertEqual(path.stat().st_mtime_ns, timestamp)
                    streams = json.loads(subprocess.run([
                        'ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_name', '-of', 'json', str(path),
                    ], capture_output=True, check=True, timeout=10).stdout)['streams']
                    self.assertEqual([s['codec_name'] for s in streams if s['codec_type'] == 'video'], [codec])
                    self.assertEqual([s['codec_name'] for s in streams if s['codec_type'] == 'audio'], ['aac', 'aac'])
