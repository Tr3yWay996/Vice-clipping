import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import _sandbox  # noqa: F401
except ModuleNotFoundError:
    from tests import _sandbox  # noqa: F401

from vice import keyframes
from vice.config import Config
from vice.share import ShareServer


def metadata(times, **stream):
    return {'streams': [{'codec_type': 'video', 'avg_frame_rate': '60/1',
                         'r_frame_rate': '60/1', 'duration': '10', **stream}],
            'frames': [{'key_frame': 1, 'pts_time': str(t)} for t in times]}


class KeyframeParsingTests(unittest.TestCase):
    def test_irregular_timestamps_are_sorted_deduplicated_and_not_rounded(self):
        result = keyframes.parse_keyframes(metadata([4.4, 0, 1.02, 4.4, 2.7], nb_frames='600'))
        self.assertEqual(result['timestamps'], [0, 1.02, 2.7, 4.4])
        self.assertEqual(result['total_frames'], 600)
        self.assertFalse(result['frames_estimated'])
        self.assertAlmostEqual(result['average_interval'], 4.4 / 3)
        self.assertAlmostEqual(result['min_interval'], 1.02)
        self.assertAlmostEqual(result['max_interval'], 1.7)

    def test_variable_frame_rate_count_is_explicitly_estimated(self):
        result = keyframes.parse_keyframes(metadata([0, 0.8, 3.7], avg_frame_rate='2997/100', r_frame_rate='60/1'))
        self.assertTrue(result['frames_estimated'])
        self.assertEqual(result['total_frames'], 300)
        self.assertEqual(result['average_fps'], 29.97)
        self.assertEqual(result['nominal_fps'], 60)
        self.assertAlmostEqual(result['average_interval'], 1.85)

    def test_missing_malformed_negative_and_decode_timestamps_are_not_keys(self):
        data = metadata(['N/A', 'nan', 'inf', -1, 20, 0])
        data['frames'] += [{'key_frame': 1, 'pts_time': 'bad', 'best_effort_timestamp_time': '1.234'},
                           {'key_frame': 1, 'pkt_dts_time': '2'}, {'key_frame': 0, 'pts_time': '3'}]
        result = keyframes.parse_keyframes(data)
        self.assertEqual(result['timestamps'], [0, 1.234])

    def test_origin_matches_container_presentation_timeline(self):
        data = metadata([7, 8.234, 9], start_time='7')
        data['format'] = {'start_time': '7'}
        self.assertEqual(keyframes.parse_keyframes(data)['timestamps'], [0, 1.234, 2])

    def test_empty_or_single_keyframe_has_no_interval_statistics(self):
        for times in [[], [0]]:
            result = keyframes.parse_keyframes(metadata(times, avg_frame_rate='0/0', r_frame_rate='N/A'))
            self.assertIsNone(result['average_interval'])
            self.assertIsNone(result['min_interval'])
            self.assertIsNone(result['max_interval'])
            self.assertIsNone(result['total_frames'])

    def test_missing_stream_is_rejected(self):
        with self.assertRaises(ValueError):
            keyframes.parse_keyframes({})


class KeyframeCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_during_probe_creation_reaps_the_decoder(self):
        real_spawn = asyncio.create_subprocess_exec
        started, release = asyncio.Event(), asyncio.Event()
        child = None

        async def spawn(*args, **kwargs):
            nonlocal child
            child = await real_spawn(sys.executable, '-c', 'import time; time.sleep(60)', **kwargs)
            started.set()
            await release.wait()
            return child

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'clip.mp4'
            path.touch()
            cache = keyframes.KeyframeCache()
            with mock.patch.object(asyncio, 'create_subprocess_exec', spawn):
                request = asyncio.create_task(cache.get(path))
                try:
                    await asyncio.wait_for(started.wait(), 2)
                    shutdown = asyncio.create_task(cache.close())
                    await asyncio.sleep(0)
                    release.set()
                    await asyncio.wait_for(shutdown, 2)
                    with self.assertRaises(asyncio.CancelledError):
                        await request
                    self.assertIsNotNone(child.returncode)
                finally:
                    release.set()
                    if child is not None and child.returncode is None:
                        child.kill()
                        await child.communicate()
                    await cache.close()
                    await asyncio.gather(request, return_exceptions=True)

    async def test_reopen_and_concurrent_requests_reuse_probe_but_replacement_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'clip.mp4'
            path.write_bytes(b'first')
            cache = keyframes.KeyframeCache()
            with mock.patch.object(keyframes, 'probe_keyframes', mock.AsyncMock(return_value={'timestamps': [0, 1]})) as probe:
                await asyncio.gather(cache.get(path), cache.get(path))
                await cache.get(path)
                self.assertEqual(probe.await_count, 1)
                old_time = path.stat().st_mtime_ns
                replacement = path.with_suffix('.tmp')
                replacement.write_bytes(b'other')
                os.utime(replacement, ns=(old_time, old_time))
                replacement.replace(path)
                cache.invalidate(path)
                await cache.get(path)
                self.assertEqual(probe.await_count, 2)
                cache.invalidate(path)
                await cache.get(path)
                self.assertEqual(probe.await_count, 3)
            await cache.close()

    async def test_result_from_file_replaced_during_analysis_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'clip.mp4'
            path.touch()
            cache = keyframes.KeyframeCache()
            async def probe(_):
                path.write_bytes(b'changed')
                return {'timestamps': [0]}
            with mock.patch.object(keyframes, 'probe_keyframes', probe):
                with self.assertRaises(ValueError):
                    await cache.get(path)
            self.assertFalse(cache._results)

    async def test_missing_ffprobe_failed_probe_and_invalid_json_are_nonfatal_api_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'clip.mp4'
            path.touch()
            server = ShareServer(Config())
            server._clips['clip'] = path
            request = mock.Mock(match_info={'slug': 'clip'})
            for error in [FileNotFoundError(), ValueError('invalid JSON'), asyncio.TimeoutError()]:
                with mock.patch.object(keyframes, 'probe_keyframes', mock.AsyncMock(side_effect=error)):
                    response = await server._api_keyframes(request)
                self.assertEqual(response.status, 503)
                self.assertIn('Free trimming', json.loads(response.text)['error'])
                self.assertFalse(server._keyframes._pending)

    async def test_cache_is_bounded(self):
        cache = keyframes.KeyframeCache()
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(keyframes, 'probe_keyframes', mock.AsyncMock(return_value={'timestamps': [0]})):
                for index in range(40):
                    path = Path(directory) / str(index)
                    path.touch()
                    await cache.get(path)
        self.assertLessEqual(len(cache._results), 32)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is not installed')
class RealKeyframeTests(unittest.IsolatedAsyncioTestCase):
    async def test_h264_and_hevc_vfr_irregular_keyframes_use_actual_presentation_times(self):
        with tempfile.TemporaryDirectory() as directory:
            for codec in ['libx264', 'libx265']:
                with self.subTest(codec=codec):
                    path = Path(directory) / f'{codec}.mp4'
                    extra = ['-x265-params', 'pools=1:frame-threads=1:log-level=error:min-keyint=1:scenecut=0'] if codec == 'libx265' else ['-sc_threshold', '0']
                    result = subprocess.run([
                        'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=64x64:rate=10:duration=4',
                        '-vf', 'select=not(eq(mod(n\\,4)\\,1))', '-fps_mode', 'vfr',
                        '-c:v', codec, '-threads', '1', '-g', '100', *extra,
                        '-force_key_frames', '0,0.7,2,3.2', '-output_ts_offset', '7', str(path),
                    ], capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    info = await keyframes.probe_keyframes(path)
                    self.assertEqual(len(info['timestamps']), 4)
                    for actual, expected in zip(info['timestamps'], [0, .7, 2, 3.2]):
                        self.assertAlmostEqual(actual, expected, places=5)
                    self.assertEqual(info['total_frames'], 30)
                    self.assertFalse(info['frames_estimated'])
