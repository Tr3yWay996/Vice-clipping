import asyncio, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from vice.timeline_previews import TimelinePreviews


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class RealTimelinePreviews(unittest.IsolatedAsyncioTestCase):
    async def test_real_waveform_silence_tone_streams_offset_and_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mkv"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=s=128x72:r=4:d=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "aevalsrc=if(lt(t\\,1)\\,0\\,0.7*sin(440*2*PI*t)):s=8000:d=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=8000:cl=stereo",
                    "-t",
                    "2",
                    "-map",
                    "0:v",
                    "-map",
                    "1:a",
                    "-map",
                    "2:a",
                    "-c:v",
                    "ffv1",
                    "-threads",
                    "1",
                    "-c:a",
                    "pcm_f32le",
                    str(source),
                ],
                check=True,
                timeout=15,
            )
            service = TimelinePreviews(root / "cache")
            try:
                full = await service.get(source, "wave", 0, 2, 0)
                peaks = json.loads(full.read_text())["peaks"]
                self.assertEqual(len(peaks), 1024)
                self.assertLess(max(peaks[:500]), 0.001)
                self.assertGreater(max(peaks[550:]), 0.45)
                silent = await service.get(source, "wave", 0, 2, 1)
                self.assertEqual(max(json.loads(silent.read_text())["peaks"]), 0)
                offset = await service.get(source, "wave", 1, 1, 0)
                self.assertGreater(min(json.loads(offset.read_text())["peaks"]), 0.3)
                with __import__("unittest.mock", fromlist=["patch"]).patch(
                    "vice.timeline_previews.asyncio.create_subprocess_exec",
                    side_effect=AssertionError("must reuse cache"),
                ):
                    self.assertEqual(await service.get(source, "wave", 0, 2, 0), full)
                first = await service.get(source, "frame", 0)
                second = await service.get(source, "frame", 1.5)
                self.assertNotEqual(first.read_bytes(), second.read_bytes())
                before = service.key(source, "wave", 0, 2, 0)
                stamp = source.stat().st_mtime_ns
                replacement = root / "replacement"
                shutil.copyfile(source, replacement)
                os.utime(replacement, ns=(stamp, stamp))
                replacement.replace(source)
                self.assertNotEqual(service.key(source, "wave", 0, 2, 0), before)
            finally:
                await service.close()

    async def test_failed_analysis_does_not_publish_fake_waveform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "broken"
            source.write_text("not media")
            service = TimelinePreviews(root / "cache")
            try:
                with self.assertRaises(RuntimeError):
                    await service.get(source, "wave", 0, 1, 0)
                self.assertEqual(list((root / "cache").iterdir()), [])
            finally:
                await service.close()

    async def test_ten_minute_two_track_analysis_is_deduplicated_and_concurrency_bounded(
        self,
    ):
        import time

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ten-minutes.mkv"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=8000:duration=600",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=8000:cl=stereo",
                    "-t",
                    "600",
                    "-map",
                    "0:a",
                    "-map",
                    "1:a",
                    "-c:a",
                    "flac",
                    "-threads",
                    "1",
                    str(source),
                ],
                check=True,
                timeout=30,
            )
            service = TimelinePreviews(root / "cache")

            class CountingLimit:
                def __init__(self):
                    self.sem = asyncio.Semaphore(2)
                    self.active = 0
                    self.maximum = 0
                    self.entries = 0

                async def __aenter__(self):
                    await self.sem.acquire()
                    self.active += 1
                    self.entries += 1
                    self.maximum = max(self.maximum, self.active)

                async def __aexit__(self, *_):
                    self.active -= 1
                    self.sem.release()

            limit = CountingLimit()
            service.lock = limit
            try:
                started = time.monotonic()
                results = await asyncio.gather(
                    *(
                        service.get(source, "wave", 0, 600, stream)
                        for stream in [0, 1, 0, 1, 0, 1]
                    )
                )
                elapsed = time.monotonic() - started
                self.assertEqual(limit.entries, 2)
                self.assertLessEqual(limit.maximum, 2)
                self.assertEqual(len(set(results)), 2)
                self.assertGreater(
                    max(json.loads(results[0].read_text())["peaks"]), 0.01
                )
                self.assertEqual(max(json.loads(results[1].read_text())["peaks"]), 0)
                cached = time.monotonic()
                await service.get(source, "wave", 0, 600, 0)
                cached = time.monotonic() - cached
                print(
                    f"PERF ten-minute stereo preview: two source tracks, six callers, {limit.entries} FFmpeg jobs, max concurrency {limit.maximum}, cold {elapsed:.3f}s, cached {cached:.6f}s"
                )
            finally:
                await service.close()
