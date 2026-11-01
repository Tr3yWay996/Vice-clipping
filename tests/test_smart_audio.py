"""Smart capture routing, fail-closed identity, persistence and recording contracts."""

import asyncio
import copy
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import _sandbox
except ModuleNotFoundError:
    from tests import _sandbox

from vice.audio_graph import (
    capture_environment,
    capture_pairs,
    game_nodes,
    port_pairs,
    sink_name,
)
from vice.audio_matching import RuleMatcher, validate_rules
from vice.audio_router import AudioRouter, validate_sources
from vice.audio_streams import ApplicationStream
from vice.config import Config, RecordingConfig, load, save


def stream(n=1, executable="BeamNG.drive.x64", pid=42, **changes):
    values = dict(
        node_id=n,
        serial=str(n),
        name="FMOD Audio",
        application_id="",
        executable=executable,
        executable_path="/games/" + executable,
        pid=pid,
        node_name="FMOD Audio",
        destination="speakers",
        active=True,
    )
    return ApplicationStream(**(values | changes))


def obj(n, kind="Node", **properties):
    return {
        "id": n,
        "type": "PipeWire:Interface:" + kind,
        "info": {"props": properties},
    }


def routing_graph():
    name = sink_name("auto:game")
    return [
        obj(
            10,
            **{
                "node.name": name,
                "node.description": "ViceCapture_game",
                "wireplumber.is-virtual": True,
                "object.serial": 100,
                "pulse.module.id": 55,
            },
        ),
        obj(1, **{"media.class": "Stream/Output/Audio"}),
        obj(
            11, "Port", **{"node.id": 10, "audio.channel": "FL", "port.direction": "in"}
        ),
        obj(
            12, "Port", **{"node.id": 10, "audio.channel": "FR", "port.direction": "in"}
        ),
        obj(
            13,
            "Port",
            **{
                "node.id": 10,
                "audio.channel": "FL",
                "port.direction": "out",
                "port.monitor": True,
            },
        ),
        obj(
            14,
            "Port",
            **{
                "node.id": 10,
                "audio.channel": "FR",
                "port.direction": "out",
                "port.monitor": True,
            },
        ),
        obj(
            21, "Port", **{"node.id": 1, "audio.channel": "FL", "port.direction": "out"}
        ),
        obj(
            22, "Port", **{"node.id": 1, "audio.channel": "FR", "port.direction": "out"}
        ),
    ]


class SmartIdentityTests(unittest.TestCase):
    def test_game_uses_process_not_shared_middleware_and_survives_restart(self):
        streams = [
            stream(),
            stream(2, "other.exe", 43),
            stream(3, pid=99),
            stream(4, "zen", 42),
        ]
        self.assertEqual(
            [
                s.node_id
                for s in game_nodes(
                    streams,
                    {
                        "pids": [42],
                        "executable": "BeamNG.drive.x64",
                        "executable_path": "/games/BeamNG.drive.x64",
                    },
                )
            ],
            [1, 3],
        )
        self.assertEqual(game_nodes(streams, {"executable": "FMOD Audio"}), [])
        self.assertEqual(game_nodes(streams, None), [])
        self.assertEqual(
            game_nodes(
                streams,
                {"executable": "BeamNG.drive.x64", "executable_path": "/other/copy"},
            ),
            [],
        )

    def test_stereo_and_mono_ports_exclude_desktop_monitor(self):
        graph = routing_graph()
        self.assertEqual(port_pairs(graph, [1], 10), {(21, 11), (22, 12)})
        self.assertEqual(port_pairs(graph, [10], 10), set())
        mono = obj(
            25,
            "Port",
            **{"node.id": 2, "audio.channel": "MONO", "port.direction": "out"},
        )
        self.assertEqual(port_pairs(graph + [mono], [2], 10), {(25, 11), (25, 12)})

    def test_consumers_must_explicitly_target_the_private_source_without_fallback(self):
        graph = routing_graph()
        name = sink_name("auto:game")
        graph += [
            obj(
                30,
                **{
                    "media.class": "Stream/Input/Audio",
                    "target.object": name,
                    "node.dont-fallback": True,
                },
            ),
            obj(
                31,
                "Port",
                **{"node.id": 30, "audio.channel": "FL", "port.direction": "in"},
            ),
            obj(
                32,
                "Port",
                **{"node.id": 30, "audio.channel": "FR", "port.direction": "in"},
            ),
        ]
        self.assertEqual(capture_pairs(graph, graph[0]), {(13, 31), (14, 32)})
        graph[-3]["info"]["props"].pop("node.dont-fallback")
        self.assertEqual(capture_pairs(graph, graph[0]), set())

    def test_capture_environment_preserves_existing_properties(self):
        with mock.patch.dict(os.environ, {"PULSE_PROP": "application.id=vice"}):
            env = capture_environment()
        self.assertIn("application.id=vice", env["PULSE_PROP"])
        self.assertIn("node.dont-fallback=true", env["PULSE_PROP"])
        self.assertIn("node.linger=true", env["PULSE_PROP"])

    def test_regex_is_bounded_and_worker_is_reaped_after_timeout(self):
        matcher = RuleMatcher()
        self.addCleanup(matcher.close)
        self.assertEqual(
            matcher.evaluate(
                [{"field": "executable", "mode": "regex", "value": r"^beamng.*x64$"}],
                [stream()],
            ),
            [stream()],
        )
        worker = matcher.process
        with self.assertRaisesRegex(ValueError, "timeout"):
            matcher.evaluate(
                [{"field": "name", "mode": "regex", "value": "(a+)+$"}],
                [stream(name="a" * 10000 + "!")],
            )
        self.assertFalse(worker.is_alive())
        self.assertIsNone(matcher.process)
        self.assertEqual(
            matcher.evaluate(
                [{"field": "executable", "mode": "contains", "value": "beamng"}],
                [stream()],
            ),
            [stream()],
        )
        for rules in [
            [{"mode": "regex", "value": "["}],
            [{"value": ""}],
            [{"field": "pid", "value": "1"}],
        ]:
            with self.assertRaises(ValueError):
                validate_rules(rules)

    def test_rules_names_enabled_gain_and_legacy_tracks_persist(self):
        cfg = Config()
        cfg.recording.audio_tracks = ["auto:game", "device:oldmic", "app:Discord"]
        cfg.recording.audio_sources = {
            "auto:game": {
                "name": "Game",
                "enabled": False,
                "rules": [
                    {"field": "executable", "mode": "contains", "value": "beamng"}
                ],
            }
        }
        cfg.recording.audio_track_volumes = {"auto:game": 0.5, "device:oldmic": 1.2}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            with (
                mock.patch("vice.config.CONFIG_PATH", path),
                mock.patch("vice.config.CONFIG_DIR", Path(folder)),
            ):
                save(cfg)
                loaded = load()
        self.assertEqual(loaded.recording.audio_tracks, cfg.recording.audio_tracks)
        self.assertEqual(loaded.recording.audio_sources, cfg.recording.audio_sources)
        self.assertEqual(
            loaded.recording.audio_track_volumes, cfg.recording.audio_track_volumes
        )
        with self.assertRaises(ValueError):
            validate_sources(
                {"rule:bad": {"device": "device:vice_capture_123.monitor"}}
            )

    def test_stable_track_layout_mix_and_live_gain_are_not_applied_twice(self):
        from vice.recorder import (
            _gsr_audio_args,
            _separate_track_layout,
            _track_volumes,
        )

        rc = RecordingConfig(
            audio_tracks=["auto:game", "rule:mic"],
            audio_sources={"rule:mic": {"device": "default_input"}},
            audio_track_volumes={"auto:game": 0.5},
            capture_microphone=True,
        )
        args = _gsr_audio_args(rc)
        self.assertEqual(
            args,
            [
                "-a",
                "device:" + sink_name("auto:game") + ".monitor",
                "-a",
                "device:" + sink_name("rule:mic") + ".monitor",
            ],
        )
        self.assertEqual(
            _track_volumes(rc, _separate_track_layout(rc)[0], False), [1, 1]
        )
        rc.audio_tracks_mix_first = True
        self.assertEqual(len(_gsr_audio_args(rc)), 6)
        rc.capture_audio = False
        self.assertEqual(_separate_track_layout(rc)[0], ["rule:mic"])

    def test_smart_sessions_use_gsr_devices_on_x11_and_never_generic_desktop_fallback(
        self,
    ):
        from vice.recorder import GSRRecorder

        cfg = Config()
        cfg.recording.audio_tracks = ["auto:game"]
        recorder = GSRRecorder(cfg)
        with (
            mock.patch("vice.recorder.choose_encoder", return_value="h264_nvenc"),
            mock.patch("vice.recorder.gsr_source", return_value="native"),
            mock.patch.object(
                recorder,
                "_gsr_session_cmd",
                return_value=["gpu-screen-recorder", "private-monitor"],
            ) as gsr,
            mock.patch("vice.recorder._is_wayland", return_value=False),
        ):
            self.assertEqual(
                recorder._build_session_cmd(Path("/tmp/session.mp4")),
                ["gpu-screen-recorder", "private-monitor"],
            )
            gsr.assert_called_once()
        with (
            mock.patch("vice.recorder.choose_encoder", return_value="h264_nvenc"),
            mock.patch("vice.recorder.gsr_source", return_value=None),
        ):
            self.assertIsNone(recorder._build_session_cmd(Path("/tmp/session.mp4")))

    def test_editing_rules_names_and_levels_does_not_restart_replay(self):
        from vice.main import ViceDaemon

        daemon = object.__new__(ViceDaemon)
        daemon.cfg = Config()
        signature = daemon._recording_signature()
        daemon.cfg.recording.audio_sources = {
            "auto:game": {"name": "Game", "enabled": False, "rules": []}
        }
        daemon.cfg.recording.audio_track_volumes = {"auto:game": 0.2}
        self.assertEqual(signature, daemon._recording_signature())
        daemon.cfg.recording.audio_tracks = ["auto:game"]
        self.assertNotEqual(signature, daemon._recording_signature())


class SmartRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = Config()
        self.cfg.recording.audio_tracks = ["auto:game"]
        self.cfg.recording.audio_sources = {"auto:game": {"name": "Game"}}
        self.router = AudioRouter(self.cfg)
        self.router.command = mock.AsyncMock(return_value="55")
        self.router.graph = {n["id"]: n for n in routing_graph()}
        self.router.ready.set()
        self.router.streams = [stream()]
        self.router.target = {"pids": [42], "executable": "BeamNG.drive.x64"}
        self.router.meters = mock.Mock(error=None)
        self.router.meters.read.return_value = [0.1, 0.2]
        self.addAsyncCleanup(self.router.close)

    async def test_gsr_process_waits_for_explicit_sources_including_inside_flatpak(
        self,
    ):
        from vice.recorder import _spawn_capture

        source = "device:" + sink_name("auto:game") + ".monitor"
        for prefix in [
            ["gpu-screen-recorder"],
            [
                "flatpak",
                "run",
                "--command=gpu-screen-recorder",
                "com.dec05eba.gpu_screen_recorder",
            ],
        ]:
            process = mock.Mock(pid=1234)
            with (
                mock.patch(
                    "vice.recorder.asyncio.create_subprocess_exec",
                    new=mock.AsyncMock(return_value=process),
                ) as spawn,
                mock.patch("vice.recorder._register_capture"),
            ):
                await _spawn_capture(prefix + ["-a", source], asyncio.subprocess.PIPE)
            self.assertIn(
                "node.dont-fallback=true", spawn.call_args.kwargs["env"]["PULSE_PROP"]
            )
            self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            if prefix[0] == "flatpak":
                self.assertTrue(
                    any(
                        arg.startswith("--env=PULSE_PROP=")
                        for arg in spawn.call_args.args
                    )
                )

    async def test_private_sink_is_never_a_default_candidate_and_is_reused(self):
        await self.router._ensure_sink("auto:game")
        self.assertEqual(self.router.modules[sink_name("auto:game")], 55)
        self.assertIn("PortConfig", self.router.command.call_args.args)
        self.router.graph.clear()
        self.router.modules.clear()
        await self.router._ensure_sink("auto:game")
        args = self.router.command.call_args.args
        self.assertIn("module-null-sink", args)
        self.assertIn("wireplumber.is-virtual=true", args[-1])
        self.assertNotIn("priority.session", args[-1])
        self.assertTrue(args[-1].startswith("sink_properties='"))

    async def test_routes_only_selected_streams_without_moving_normal_playback(self):
        await self.router._reconcile()
        calls = [c.args for c in self.router.command.call_args_list]
        links = [c for c in calls if c[0] == "pw-link"]
        self.assertEqual(len(links), 2)
        self.assertTrue(all("-P" in c for c in links))
        self.assertFalse(
            any("move-sink-input" in c or "set-default-sink" in c for c in calls)
        )
        self.assertEqual(self.router.slots["auto:game"]["nodes"], [1])
        self.router.target = {"executable": "RocketLeague.exe"}
        self.router.command.reset_mock()
        await self.router._reconcile()
        self.assertEqual(self.router.slots["auto:game"]["nodes"], [])
        self.assertFalse(
            any(
                c.args[0] == "pw-link" and "-d" not in c.args
                for c in self.router.command.call_args_list
            )
        )

    async def test_live_gain_uses_linear_amplitude_and_disable_unlinks(self):
        self.cfg.recording.audio_track_volumes = {"auto:game": 0.5}
        await self.router._reconcile()
        volume = next(
            c.args
            for c in self.router.command.call_args_list
            if "set-source-volume" in c.args
        )
        self.assertAlmostEqual(float(volume[-1][:-2]), -6.0206, places=3)
        self.cfg.recording.audio_sources["auto:game"]["enabled"] = False
        await self.router._reconcile()
        self.assertEqual(self.router.slots["auto:game"]["nodes"], [])
        self.assertEqual(self.router.snapshot()["tracks"][0]["state"], "disabled")

    async def test_actual_capture_connection_is_distinct_from_stream_activity(self):
        await self.router._reconcile()
        self.assertFalse(self.router.snapshot()["tracks"][0]["recording_connected"])
        self.router.graph[60] = obj(
            60, **{"application.process.binary": "gpu-screen-recorder"}
        )
        self.router.graph[61] = obj(61, "Link")
        self.router.graph[61]["info"].update(
            {"output-node-id": 10, "input-node-id": 60}
        )
        self.assertTrue(self.router.snapshot()["tracks"][0]["recording_connected"])
        self.router.meters.read.return_value = None
        self.assertEqual(
            self.router.snapshot()["tracks"][0]["state"], "meter_unavailable"
        )
        self.router.error = "server_unavailable"
        self.assertEqual(self.router.snapshot()["tracks"][0]["state"], "disconnected")

    async def test_missing_game_and_regex_failure_never_fall_back_to_desktop(self):
        self.router.target = None
        await self.router._reconcile()
        self.assertEqual(self.router.snapshot()["tracks"][0]["state"], "missing_game")
        self.cfg.recording.audio_sources["auto:game"]["rules"] = [{"value": "x"}]
        self.router.matcher.evaluate = mock.Mock(
            side_effect=ValueError("audio.regex_timeout")
        )
        await self.router._reconcile()
        self.assertEqual(self.router.slots["auto:game"]["nodes"], [])
        self.assertEqual(self.router.slots["auto:game"]["error"], "audio.regex_timeout")

    async def test_monitor_leases_expire_and_samples_are_deleted(self):
        self.router.monitor_view("one", True)
        self.assertTrue(self.router.viewing())
        self.router.leases["one"] = time.monotonic() - 1
        self.assertFalse(self.router.viewing())
        folder = Path(tempfile.mkdtemp())
        (folder / "0.wav").write_bytes(b"sample")
        self.router.tests["test"] = (folder, time.monotonic())
        self.router.delete_test("test")
        self.assertFalse(folder.exists())

    async def test_unsupported_tools_prevent_start_instead_of_desktop_fallback(self):
        self.router.ready.clear()
        self.router.graph.clear()
        with mock.patch("vice.audio_router.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no desktop fallback"):
                await self.router.ensure_tracks()
        self.assertEqual(self.router.snapshot()["tracks"][0]["state"], "unsupported")


class SmartAudioAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from vice.share import ShareServer

        self.server = ShareServer(Config())
        self.router = AudioRouter(self.server.cfg)
        self.server.audio_router = self.router
        self.addAsyncCleanup(self.router.close)

    def request(self, body=None, **path):
        from types import SimpleNamespace

        return SimpleNamespace(json=mock.AsyncMock(return_value=body), match_info=path)

    async def test_match_preview_uses_compact_live_identity_and_rejects_bad_patterns(
        self,
    ):
        import json
        from aiohttp import web

        self.router.streams = [stream()]
        response = await self.server._api_audio_match(
            self.request(
                {
                    "rules": [
                        {"field": "executable", "mode": "contains", "value": "beamng"}
                    ]
                }
            )
        )
        self.assertEqual(json.loads(response.text), {"matches": [[1]]})
        with self.assertRaises(web.HTTPBadRequest):
            await self.server._api_audio_match(
                self.request({"rules": [{"value": "[", "mode": "regex"}]})
            )

    async def test_monitor_leases_and_test_sample_paths_are_bounded(self):
        from aiohttp import web

        with self.assertRaises(web.HTTPBadRequest):
            await self.server._api_audio_monitor(
                self.request({"token": "../bad", "enabled": True})
            )
        for i in range(8):
            await self.server._api_audio_monitor(
                self.request({"token": str(i), "enabled": True})
            )
        with self.assertRaises(web.HTTPTooManyRequests):
            await self.server._api_audio_monitor(
                self.request({"token": "new", "enabled": True})
            )
        with tempfile.TemporaryDirectory() as directory:
            self.router.tests["test"] = (Path(directory), time.monotonic())
            for index in ("../0", "123", "-1", "0"):
                with self.assertRaises(web.HTTPNotFound):
                    await self.server._api_audio_sample(
                        self.request(test="test", index=index)
                    )
        self.router.tests.clear()

    async def test_audio_rules_map_can_be_replaced_and_deleted_without_losing_legacy_sources(
        self,
    ):
        from tests.test_share_server import _JsonRequest
        import json

        source = {
            "rule:game": {
                "name": "Game",
                "enabled": True,
                "rules": [
                    {"field": "executable", "mode": "contains", "value": "beamng"}
                ],
            }
        }
        self.server.cfg.recording.audio_tracks = ["app:Discord", "rule:game"]
        with (
            mock.patch("vice.config.load", return_value=self.server.cfg),
            mock.patch("vice.config.save") as saved,
        ):
            await self.server._api_set_config(
                _JsonRequest({"recording": {"audio_sources": source}})
            )
            self.assertEqual(saved.call_args.args[0].recording.audio_sources, source)
            self.assertEqual(
                saved.call_args.args[0].recording.audio_tracks,
                ["app:Discord", "rule:game"],
            )
        with (
            mock.patch("vice.config.load", return_value=self.server.cfg),
            mock.patch("vice.config.save") as saved,
        ):
            await self.server._api_set_config(
                _JsonRequest({"recording": {"audio_sources": {}}})
            )
            self.assertEqual(saved.call_args.args[0].recording.audio_sources, {})

    async def test_capture_samples_fail_closed_and_reject_overlapping_tests(self):
        from aiohttp import web

        self.server.cfg.recording.audio_tracks = ["auto:game"]
        self.server.cfg.recording.audio_sources = {"auto:game": {"enabled": True}}
        result = await self.router.capture_test()
        self.assertEqual(result["tracks"][0]["state"], "disconnected")
        self.router.delete_test(result["id"])
        await self.router.test_lock.acquire()
        try:
            with self.assertRaises(web.HTTPConflict):
                await self.server._api_audio_test(self.request())
        finally:
            self.router.test_lock.release()


class SmartRecordedMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_track_titles_preserve_media_streams_and_historical_time(self):
        import shutil, json, subprocess

        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        from tests.test_audio_tracks import make_source
        from vice.recorder import _apply_track_titles

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recording.mkv"
            make_source(path)
            stamp = 1_600_000_000_123_456_789
            os.utime(path, ns=(stamp, stamp))
            rc = RecordingConfig(
                audio_tracks=["auto:game", "rule:mic", "app:Discord"],
                audio_sources={
                    "auto:game": {"name": "BeamNG game"},
                    "rule:mic": {"name": "My microphone", "device": "default_input"},
                },
            )
            await _apply_track_titles(path, rc)
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            probe = json.loads(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_streams",
                        "-of",
                        "json",
                        str(path),
                    ]
                )
            )["streams"]
            self.assertEqual(
                [item["codec_name"] for item in probe],
                ["ffv1", "pcm_s16le", "pcm_s16le", "pcm_s16le"],
            )
            self.assertEqual(
                [item["tags"]["title"] for item in probe[1:]],
                ["BeamNG game", "My microphone", "app:Discord"],
            )


class SmartGameIntentTests(unittest.TestCase):
    def test_steam_game_is_pinned_without_a_library_tag_and_alt_tab_does_not_retarget(
        self,
    ):
        from vice.main import ViceDaemon
        from types import SimpleNamespace

        daemon = object.__new__(ViceDaemon)
        daemon._window_capture_id = None
        daemon._resolve_game = mock.Mock(return_value=None)
        process = mock.Mock(pid=42)
        process.create_time.return_value = 100
        process.children.return_value = [SimpleNamespace(pid=43)]
        with (
            mock.patch(
                "vice.active_window.get_active_window",
                return_value={"pid": 42, "window_id": "game"},
            ),
            mock.patch(
                "vice.active_window.process_identity",
                return_value={
                    "executable": "BeamNG.drive.x64",
                    "executable_path": "/games/BeamNG.drive.x64",
                },
            ),
            mock.patch("vice.active_window.read_steam_app_id", return_value="284160"),
            mock.patch("psutil.Process", return_value=process),
        ):
            target = daemon._audio_game_target()
        self.assertEqual(target["pids"], [42, 43])
        daemon._resolve_game.assert_not_called()
        with (
            mock.patch(
                "vice.active_window.get_active_window",
                return_value={"pid": 9, "window_id": "browser"},
            ),
            mock.patch(
                "vice.active_window.process_identity",
                return_value={"executable": "zen"},
            ),
            mock.patch("psutil.Process", return_value=process),
        ):
            target = daemon._audio_game_target()
        self.assertEqual(target["executable"], "BeamNG.drive.x64")
        self.assertEqual(target["pid"], 42)

    def test_native_game_desktop_entry_is_independent_of_library_recognition(self):
        from vice.audio_target import native_game

        with mock.patch(
            "vice.audio_target.desktop_game_rules",
            return_value=[("supertux2", "supertux2")],
        ):
            self.assertTrue(
                native_game({"class": "SuperTux2"}, {"executable": "supertux2"})
            )
            self.assertFalse(native_game({"class": "Zen"}, {"executable": "zen"}))
