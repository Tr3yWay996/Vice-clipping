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
