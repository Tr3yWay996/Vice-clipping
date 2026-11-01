import asyncio
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

try:
    import _sandbox
except ModuleNotFoundError:
    from tests import _sandbox
from vice.audio_warnings import AudioWarningPolicy, preferences
from vice.config import Config, RecordingConfig
from vice.editor import validate_project, build_export_cmd, Source, EditorProjectStore


class WarningPolicyTests(unittest.TestCase):
    def track(self, state):
        return {"id": "auto:game", "name": "Game", "enabled": True, "state": state}

    def test_normal_silence_and_intentional_mute_never_warn_by_default(self):
        policy = AudioWarningPolicy()
        for _ in range(100):
            for state in ("active", "connected", "quiet", "muted", "disabled"):
                self.assertEqual(policy.update([self.track(state)], {}), [])

    def test_failure_is_one_episode_until_recovery_and_name_changes_are_not_new_failures(
        self,
    ):
        policy = AudioWarningPolicy()
        first = policy.update([self.track("disconnected")], {})
        for _ in range(100):
            self.assertEqual(policy.update([self.track("disconnected")], {}), first)
        self.assertEqual(
            policy.update([self.track("missing_stream")], {})[0]["id"], first[0]["id"]
        )
        renamed = self.track("disconnected")
        renamed["name"] = "Custom name"
        self.assertEqual(policy.update([renamed], {})[0]["id"], first[0]["id"])
        self.assertEqual(policy.update([self.track("active")], {}), [])
        self.assertNotEqual(
            policy.update([self.track("disconnected")], {})[0]["id"], first[0]["id"]
        )

    def test_preferences_suppress_categories_sources_and_specific_conditions(self):
        policy = AudioWarningPolicy()
        self.assertEqual(
            policy.update([self.track("unsupported")], {"critical": False}), []
        )
        self.assertEqual(
            policy.update([self.track("missing_stream")], {"disconnected": False}), []
        )
        self.assertEqual(
            policy.update(
                [self.track("unsupported")], {"ignored_sources": ["auto:game"]}
            ),
            [],
        )
        self.assertEqual(
            policy.update(
                [self.track("missing_stream")],
                {"ignored_conditions": ["auto:game|missing_stream"]},
            ),
            [],
        )
        self.assertEqual(
            len(
                policy.update(
                    [self.track("unsupported")],
                    {"ignored_conditions": ["auto:game|missing_stream"]},
                )
            ),
            1,
        )
        self.assertEqual(
            policy.update([self.track("quiet")], {"silence": True})[0]["kind"],
            "silence",
        )

    def test_preferences_are_bounded_and_do_not_restart_capture(self):
        from vice.main import ViceDaemon

        self.assertEqual(
            preferences({"silence_seconds": float("nan")})["silence_seconds"], 180
        )
        self.assertEqual(preferences({"silence_seconds": 1})["silence_seconds"], 30)
        daemon = object.__new__(ViceDaemon)
        daemon.cfg = Config()
        signature = daemon._recording_signature()
        daemon.cfg.recording.audio_warning_preferences = {
            "silence": True,
            "silence_seconds": 60,
        }
        self.assertEqual(signature, daemon._recording_signature())

    def test_router_uses_configured_silence_duration_and_keeps_live_diagnostics(self):
        from vice.audio_router import AudioRouter

        cfg = Config()
        cfg.recording.audio_tracks = ["auto:game"]
        cfg.recording.audio_warning_preferences = {
            "silence": False,
            "silence_seconds": 90,
        }
        router = AudioRouter(cfg)
        router.target = {"executable": "game"}
        router.meters = mock.Mock(error=None)
        router.meters.read.return_value = [0, 0]
        router.slots["auto:game"] = {
            "id": "auto:game",
            "name": "Game",
            "enabled": True,
            "monitor": "private",
            "nodes": [1],
            "linked": True,
            "playing": True,
            "gain": 1,
        }
        router.last_signal["auto:game"] = 100
        with mock.patch("vice.audio_router.time.monotonic", return_value=131):
            self.assertEqual(router.snapshot()["tracks"][0]["state"], "connected")
        with mock.patch("vice.audio_router.time.monotonic", return_value=200):
            snapshot = router.snapshot()
            self.assertEqual(snapshot["tracks"][0]["state"], "quiet")
            self.assertEqual(snapshot["warnings"], [])
        cfg.recording.audio_warning_preferences["silence"] = True
        with mock.patch("vice.audio_router.time.monotonic", return_value=201):
            self.assertEqual(len(router.snapshot()["warnings"]), 1)


class ProjectAudioTests(unittest.TestCase):
    def project(self):
        return {
            "version": 1,
            "tracks": [
                {"id": "T1", "type": "text", "label": "Text"},
                {"id": "V1", "type": "video", "label": "Video"},
                {
                    "id": "A1",
                    "type": "audio",
                    "label": "My custom microphone name",
                    "muted": False,
                    "volume": 0.5,
                    "sourceKey": "recording:1",
                },
                {
                    "id": "A2",
                    "type": "audio",
                    "label": "My custom microphone name",
                    "muted": True,
                    "solo": True,
                },
            ],
            "items": [
                {
                    "id": "v",
                    "kind": "clip",
                    "trackId": "V1",
                    "clipId": "clip",
                    "start": 0,
                    "dur": 2,
                    "offset": 0,
                    "muted": True,
                },
                {
                    "id": "a",
                    "kind": "audio",
                    "trackId": "A1",
                    "clipId": "clip",
                    "start": 0,
                    "dur": 2,
                    "offset": 0,
                    "audioStream": 1,
                    "volume": 0.6,
                },
                {
                    "id": "b",
                    "kind": "audio",
                    "trackId": "A2",
                    "clipId": "clip",
                    "start": 0,
                    "dur": 2,
                    "offset": 0,
                    "audioStream": 2,
                    "volume": 1,
                },
            ],
        }

    def test_names_duplicate_labels_track_mute_volume_and_source_identity_survive_save(
        self,
    ):
        sources = {"clip": Source(Path("clip.mkv"), 2, 128, 72, True, audio_streams=3)}
        project, errors = validate_project(self.project(), sources)
        self.assertEqual(errors, [])
        self.assertEqual(project["tracks"][2]["label"], "My custom microphone name")
        self.assertEqual(project["tracks"][2]["sourceKey"], "recording:1")
        self.assertNotIn("solo", project["tracks"][3])
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch("vice.editor.PROJECT_PATH", Path(folder) / "project.json"),
        ):
            store = EditorProjectStore()
            store.save(project)
            self.assertEqual(store.load(), project)
        cmd = build_export_cmd(project, sources, Path("export.mp4"))
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("volume=0.3", graph)
        self.assertNotIn("[0:a:2]", graph)
        self.assertEqual(cmd.count("-map"), 2)

    def test_legacy_project_remains_compatible_and_solo_is_discarded(self):
        sources = {"clip": Source(Path("clip.mkv"), 2, 128, 72, True, audio_streams=3)}
        raw = self.project()
        raw["tracks"][2].pop("muted")
        raw["tracks"][2].pop("volume")
        project, errors = validate_project(raw, sources)
        self.assertFalse(errors)
        self.assertNotIn("muted", project["tracks"][2])
        self.assertNotIn("solo", project["tracks"][3])


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required"
)
class RealAudioWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def probe(self, path):
        return json.loads(
            subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]
            )
        )["streams"]

    async def test_mp4_mkv_titles_survive_copy_trim_and_video_reencode_with_all_tracks(
        self,
    ):
        from vice.recorder import _apply_track_titles
        from vice.media import probe_media

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for ext in ("mp4", "mkv"):
                source = root / ("clip." + ext)
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=s=128x72:r=10:d=1",
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=440:duration=1",
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=880:duration=1",
                        "-map",
                        "0:v",
                        "-map",
                        "1:a",
                        "-map",
                        "2:a",
                        "-c:v",
                        "libx264",
                        "-threads",
                        "1",
                        "-c:a",
                        "aac",
                        "-y",
                        str(source),
                    ],
                    check=True,
                    timeout=15,
                )
                stamp = 1_600_000_000_123_456_789
                os.utime(source, ns=(stamp, stamp))
                rc = RecordingConfig(audio_tracks=["default_output", "default_input"])
                await _apply_track_titles(source, rc)
                self.assertEqual(source.stat().st_mtime_ns, stamp)
                for kind in ("copy", "trim", "reencode"):
                    output = root / (kind + "." + ext)
                    if kind == "copy":
                        shutil.copy2(source, output)
                    else:
                        subprocess.run(
                            [
                                "ffmpeg",
                                "-v",
                                "error",
                                "-ss",
                                "0.1",
                                "-i",
                                str(source),
                                "-t",
                                "0.6",
                                "-map",
                                "0",
                                "-c",
                                "copy",
                                *(
                                    ["-c:v", "libx264", "-threads", "1"]
                                    if kind == "reencode"
                                    else []
                                ),
                                "-y",
                                str(output),
                            ],
                            check=True,
                            timeout=15,
                        )
                    streams = self.probe(output)
                    audio = [s for s in streams if s["codec_type"] == "audio"]
                    self.assertEqual([s["codec_name"] for s in audio], ["aac", "aac"])
                    self.assertEqual(
                        [
                            s["tags"].get("title", s["tags"].get("handler_name"))
                            for s in audio
                        ],
                        ["Desktop Audio", "Microphone"],
                    )
                    meta = await probe_media(output)
                    self.assertEqual(
                        [s["title"] for s in meta["audio_tracks"]],
                        ["Desktop Audio", "Microphone"],
                    )

    async def test_separate_export_is_named_and_muted_stem_is_silent_while_mixed_stays_default(
        self,
    ):
        from tests.test_audio_tracks import make_source

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.mkv"
            make_source(source)
            sources = {"clip": Source(source, 2, 128, 72, True, audio_streams=3)}
            project, errors = validate_project(ProjectAudioTests().project(), sources)
            self.assertFalse(errors)
            for separate in (False, True):
                output = root / ("stems.mp4" if separate else "mixed.mp4")
                subprocess.run(
                    build_export_cmd(project, sources, output, separate_audio=separate),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=True,
                    timeout=25,
                )
                audio = [s for s in self.probe(output) if s["codec_type"] == "audio"]
                self.assertEqual(len(audio), 2 if separate else 1)
                if separate:
                    self.assertEqual(
                        [s["tags"]["handler_name"] for s in audio],
                        ["My custom microphone name"] * 2,
                    )
                    raw = subprocess.check_output(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-i",
                            str(output),
                            "-map",
                            "0:a:1",
                            "-f",
                            "s16le",
                            "-",
                        ]
                    )
                    import array

                    self.assertLessEqual(
                        max(map(abs, array.array("h", raw)), default=0), 1
                    )
