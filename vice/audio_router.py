"""Persistent private capture sinks with event-driven PipeWire fan-out.

Only links into Vice-owned virtual sinks change. Applications keep their audible
links and GSR retains the same capture devices for its entire replay lifetime.
"""

from __future__ import annotations
import asyncio
import copy
import codecs
import json
import logging
import math
import re
import os
import shutil
import time
from dataclasses import asdict
from .audio_graph import (
    AUTO_GAME,
    managed,
    sink_name,
    props,
    graph_objects,
    port_pairs,
    game_nodes,
    capture_pairs,
    capture_environment,
)
from .audio_matching import RuleMatcher, validate_rules
from .audio_meter import PeakMonitor
from .audio_streams import parse_streams, enrich_streams

log = logging.getLogger(__name__)


def validate_sources(value):
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError("audio.sources")
    for key, source in value.items():
        if not isinstance(key, str) or not (
            key == AUTO_GAME or key.startswith("rule:") and key[5:].isalnum()
        ):
            raise ValueError("audio.sources")
        if not isinstance(source, dict):
            raise ValueError("audio.sources")
        if (
            not isinstance(source.get("name", ""), str)
            or len(source.get("name", "")) > 120
        ):
            raise ValueError("audio.name")
        if type(source.get("enabled", True)) is not bool:
            raise ValueError("audio.sources")
        validate_rules(source.get("rules", []))
        device = source.get("device")
        if device is not None and (
            not isinstance(device, str)
            or not (
                device in {"default_input", "default_output"}
                or device.startswith("device:")
                and not device.startswith("device:vice_capture_")
            )
        ):
            raise ValueError("audio.device")
        if type(source.get("exclude", False)) is not bool:
            raise ValueError("audio.sources")
    return value


class AudioRouter:
    def __init__(self, cfg, *, game_target=None, publish=None, recorder_state=None):
        self.cfg = cfg
        self.game_target = game_target
        self.publish = publish
        self.recorder_state = recorder_state
        self.graph = {}
        self.streams = []
        self.target = None
        self.error = None
        self.slots = {}
        self.modules = {}
        self.matcher = RuleMatcher()
        self.meters = PeakMonitor()
        self.leases = {}
        self.tasks = []
        self.monitor = None
        self.changed = asyncio.Event()
        self.ready = asyncio.Event()
        self.lock = asyncio.Lock()
        self.closed = False
        from .audio_warnings import AudioWarningPolicy
        self.warning_policy = AudioWarningPolicy()
        self.last_signal = {}
        self.started = time.monotonic()
        self._last_status = None
        self._process_cache = {}
        self.tests = {}
        self.test_lock = asyncio.Lock()
        self.backend_supported = True
        self.port_configured = set()

    def configured(self):
        rc = self.cfg.recording
        from .recorder import _source_kind

        return [
            source
            for source in (rc.audio_tracks or [rc.gsr_audio_source])
            if managed(source)
            and (rc.capture_audio or _source_kind(rc, source) == "input")
        ]

    async def command(self, *args, timeout=5, env=None):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            proc.kill()
            await proc.communicate()
            raise
        if proc.returncode:
            raise RuntimeError(
                err.decode(errors="replace")[:300] or f"{args[0]} failed"
            )
        return out.decode(errors="replace")

    async def start(self):
        if self.tasks:
            return
        if not all(
            shutil.which(tool)
            for tool in ("pw-dump", "pw-link", "pw-cli", "pactl", "wireplumber")
        ):
            self.error = "tools_missing"
            return
        try:
            version = await self.command("wireplumber", "--version")
            if not re.search(r"\b(?:0\.(?:[5-9]|[1-9]\d)|[1-9]\d*\.)", version):
                raise RuntimeError("WirePlumber 0.5 or newer required")
        except (OSError, RuntimeError, asyncio.TimeoutError):
            self.error = "tools_missing"
            return
        self.closed = False
        self.tasks = [
            asyncio.create_task(self._graph_loop()),
            asyncio.create_task(self._route_loop()),
            asyncio.create_task(self._publish_loop()),
        ]
        try:
            await asyncio.wait_for(self.ready.wait(), 3)
        except asyncio.TimeoutError:
            self.error = "server_unavailable"

    async def close(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []
        if self.monitor and self.monitor.returncode is None:
            self.monitor.terminate()
            await self.monitor.wait()
        await asyncio.to_thread(self.meters.close)
        await asyncio.to_thread(self.matcher.close)
        for module in list(self.modules.values()):
            try:
                await self.command("pactl", "unload-module", str(module))
            except Exception:
                pass
        self.modules.clear()
        for folder, created in self.tests.values():
            shutil.rmtree(folder, ignore_errors=True)
        self.tests.clear()

    async def _graph_loop(self):
        while not self.closed:
            try:
                self.monitor = await asyncio.create_subprocess_exec(
                    "pw-dump",
                    "-m",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                decoder = json.JSONDecoder()
                buffer = ""
                utf8 = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while True:
                    raw = await self.monitor.stdout.read(65536)
                    if not raw:
                        raise RuntimeError("PipeWire graph disconnected")
                    buffer += utf8.decode(raw)
                    if len(buffer) > 32 * 1024 * 1024:
                        raise RuntimeError("PipeWire graph too large")
                    while buffer.strip():
                        buffer = buffer.lstrip()
                        try:
                            items, end = decoder.raw_decode(buffer)
                        except json.JSONDecodeError:
                            break
                        buffer = buffer[end:]
                        significant = False
                        for item in items:
                            kind = item.get(
                                "type", self.graph.get(item["id"], {}).get("type", "")
                            )
                            significant |= kind.rsplit(":", 1)[-1] in {
                                "Node",
                                "Port",
                                "Link",
                                "Metadata",
                            }
                            if item.get("info") is None:
                                self.graph.pop(item["id"], None)
                            else:
                                previous = self.graph.get(item["id"], {})
                                info = {
                                    **previous.get("info", {}),
                                    **item.get("info", {}),
                                }
                                info["props"] = {
                                    **props(previous),
                                    **(item.get("info", {}).get("props") or {}),
                                }
                                self.graph[item["id"]] = {
                                    **previous,
                                    **item,
                                    "info": info,
                                }
                        self.streams = await asyncio.to_thread(
                            enrich_streams,
                            parse_streams(list(self.graph.values())),
                            self._process_cache,
                        )
                        self.ready.set()
                        if significant:
                            self.changed.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.error = "server_unavailable"
                self.ready.clear()
                self.graph.clear()
                self.streams = []
                self.modules.clear()
                self.port_configured.clear()
                self.changed.set()
            finally:
                if self.monitor and self.monitor.returncode is None:
                    self.monitor.terminate()
                    await self.monitor.wait()
            await asyncio.sleep(2)

    async def ensure_tracks(self):
        await self.start()
        if not self.tasks or not self.ready.is_set() or not self.graph:
            raise RuntimeError(
                "Smart audio requires PipeWire, pw-dump, pw-link and pactl; no desktop fallback was selected."
            )
        async with self.lock:
            for source in self.configured():
                await self._ensure_sink(source)
        self.changed.set()
        # Module creation and graph discovery are asynchronous. Wait for the
        # private source to be configured before GSR opens its Pulse device.
        deadline = time.monotonic() + 3
        while any(
            self.slots.get(source, {}).get("capture_node") is None
            for source in self.configured()
        ):
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "Private capture devices are not ready; no desktop fallback was selected."
                )
            await asyncio.sleep(0.02)
        for slot in self.snapshot()["tracks"]:
            if slot["state"] not in {"active", "connected", "disabled"}:
                log.warning(
                    "Audio track %s is unresolved at recording start (%s)",
                    slot["name"],
                    slot["state"],
                )

    async def _ensure_sink(self, source):
        name = sink_name(source)
        nodes = graph_objects(list(self.graph.values()), "Node")
        existing = next(
            (node for node in nodes if props(node).get("node.name") == name), None
        )
        if existing:
            ep = props(existing)
            if (
                not str(ep.get("node.description", "")).startswith("ViceCapture_")
                or ep.get("wireplumber.is-virtual") not in (True, "true")
                or "priority.session" in ep
            ):
                raise RuntimeError("Private capture source name is occupied or unsafe")
            if "pulse.module.id" in ep:
                self.modules[name] = int(ep["pulse.module.id"])
            identity = (existing["id"], ep.get("object.serial"))
            if identity not in self.port_configured:
                # WirePlumber deliberately ignores these sinks: they can never
                # become defaults. Configure DSP ports and exact consumer links ourselves.
                await self.command(
                    "pw-cli",
                    "set-param",
                    str(existing["id"]),
                    "PortConfig",
                    "{ direction: Input, mode: dsp, monitor: true, control: false, format: { mediaType: audio, mediaSubtype: raw, format: F32P, rate: 48000, channels: 2, position: [ FL, FR ] } }",
                )
                self.port_configured.add(identity)
            return name
        if name not in self.modules:
            out = await self.command(
                "pactl",
                "load-module",
                "module-null-sink",
                f"sink_name={name}",
                "channels=2",
                "rate=48000",
                "channel_map=front-left,front-right",
                f"sink_properties='device.description=ViceCapture_{name} wireplumber.is-virtual=true node.virtual=true'",
            )
            self.modules[name] = int(out.strip())
        return name

    def viewing(self):
        now = time.monotonic()
        self.leases = {key: until for key, until in self.leases.items() if until > now}
        return bool(self.leases)

    def monitor_view(self, token, enabled):
        if enabled:
            self.leases[token] = time.monotonic() + 45
        else:
            self.leases.pop(token, None)
        self.changed.set()

    async def _route_loop(self):
        while True:
            try:
                try:
                    await asyncio.wait_for(self.changed.wait(), 2)
                except asyncio.TimeoutError:
                    pass
                self.changed.clear()
                await asyncio.sleep(0.08)
                if self.game_target:
                    target = await asyncio.to_thread(self.game_target)
                    if target:
                        self.target = target
                if not self.ready.is_set():
                    self.error = "server_unavailable"
                    continue
                async with self.lock:
                    await self._reconcile()
                self.error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error = "routing_failed"
                log.warning("Audio routing unavailable: %s", exc)

    async def _reconcile(self):
        graph = list(self.graph.values())
        sources = self.cfg.recording.audio_sources
        wanted = {source: sources.get(source, {}) for source in self.configured()}
        if self.viewing():
            for stream in self.streams[:32]:
                wanted["meter:" + str(stream.serial or stream.node_id)] = {
                    "meter_node": stream.node_id,
                    "enabled": True,
                }
        meter_targets = set()
        nodes = graph_objects(graph, "Node")
        links = graph_objects(graph, "Link")
        self.port_configured.intersection_update(
            (n["id"], props(n).get("object.serial")) for n in nodes
        )
        active_names = set()
        for source, settings in wanted.items():
            name = await self._ensure_sink(source)
            active_names.add(name)
            destination = next(
                (n for n in nodes if props(n).get("node.name") == name), None
            )
            enabled = settings.get("enabled", True)
            error = None
            matches = []
            match_ids = []
            try:
                if not enabled:
                    matches = []
                elif "meter_node" in settings:
                    matches = [
                        s for s in self.streams if s.node_id == settings["meter_node"]
                    ]
                elif settings.get("device"):
                    device = settings["device"]
                    if device == "default_input":
                        node_name = (
                            await self.command("pactl", "get-default-source")
                        ).strip()
                    elif device == "default_output":
                        node_name = (
                            await self.command("pactl", "get-default-sink")
                        ).strip()
                    else:
                        node_name = device[7:]
                    node_name = node_name.removesuffix(".monitor")
                    matches = []
                    match_ids = [
                        n["id"] for n in nodes if props(n).get("node.name") == node_name
                    ]
                elif source == AUTO_GAME:
                    matches = game_nodes(self.streams, self.target)
                    if settings.get("rules"):
                        matches = await asyncio.to_thread(
                            self.matcher.evaluate, settings["rules"], self.streams
                        )
                else:
                    matches = await asyncio.to_thread(
                        self.matcher.evaluate, settings.get("rules", []), self.streams
                    )
                if enabled and settings.get("exclude"):
                    matches = [
                        stream for stream in self.streams if stream not in matches
                    ]
                if not settings.get("device"):
                    match_ids = [stream.node_id for stream in matches]
            except ValueError as exc:
                matches = []
                match_ids = []
                error = str(exc)
            desired = (
                port_pairs(
                    graph,
                    match_ids,
                    destination["id"],
                    allow_monitor=bool(settings.get("device")),
                )
                if destination
                else set()
            )
            if destination:
                identities = {
                    name,
                    str(destination["id"]),
                    str(props(destination).get("object.serial")),
                }
                for consumer in nodes:
                    cp = props(consumer)
                    if (
                        cp.get("media.class") == "Stream/Input/Audio"
                        and str(cp.get("target.object")) in identities
                        and cp.get("node.dont-fallback") in (True, "true")
                    ):
                        identity = (consumer["id"], cp.get("object.serial"))
                        if identity not in self.port_configured:
                            await self.command(
                                "pw-cli",
                                "set-param",
                                str(consumer["id"]),
                                "PortConfig",
                                "{ direction: Input, mode: dsp, monitor: false, control: false, format: { mediaType: audio, mediaSubtype: raw, format: F32P, rate: 48000, channels: 2, position: [ FL, FR ] } }",
                            )
                            self.port_configured.add(identity)
            captures = capture_pairs(graph, destination) if destination else set()
            desired |= captures
            owned = {}
            for link in links:
                lp = props(link)
                if lp.get("vice.capture") == name:
                    pair = (
                        link["info"].get("output-port-id"),
                        link["info"].get("input-port-id"),
                    )
                    owned[pair] = link["id"]
            # Remove stale owned fan-outs before adding the new game's routes.
            for pair, lid in owned.items():
                if pair not in desired:
                    try:
                        await self.command("pw-link", "-d", str(lid))
                    except RuntimeError:
                        pass  # An application may have exited first.
            for pair in desired - owned.keys():
                await self.command(
                    "pw-link",
                    *(() if pair in captures else ("-P",)),
                    "-p",
                    json.dumps({"vice.capture": name}),
                    str(pair[0]),
                    str(pair[1]),
                )
            monitor = name + ".monitor"
            gain = (
                float(self.cfg.recording.audio_track_volumes.get(source, 1))
                if managed(source)
                else 1
            )
            if destination and self.slots.get(source, {}).get("applied_gain") != gain:
                await self.command(
                    "pactl",
                    "set-source-volume",
                    monitor,
                    ("0%" if gain <= 0 else f"{20*math.log10(min(2,gain)):.4f}dB"),
                )
            if enabled and destination:
                meter_targets.add(monitor)
            self.slots[source] = {
                "id": source,
                "name": settings.get("name")
                or ("Recorded Game Audio" if source == AUTO_GAME else source),
                "enabled": enabled,
                "nodes": match_ids,
                "source_muted": bool(matches)
                and all(stream.muted for stream in matches),
                "playing": any(stream.active for stream in matches)
                or bool(
                    settings.get("device")
                    and any(
                        n["info"].get("state") == "running"
                        for n in nodes
                        if n["id"] in match_ids
                    )
                ),
                "monitor": monitor,
                "gain": gain,
                "applied_gain": gain if destination else None,
                "linked": bool(desired - captures) and error is None,
                "capture_node": destination["id"] if destination else None,
                "ambiguous": len({(s.executable, s.application_id) for s in matches})
                > 1,
                "error": error,
                "target": copy.deepcopy(self.target) if source == AUTO_GAME else None,
            }
        # Unused meter taps are removed, not left connected to private audio.
        for source in list(self.slots):
            if source not in wanted:
                self.slots.pop(source, None)
        for name, module in list(self.modules.items()):
            if name not in active_names:
                await self.command("pactl", "unload-module", str(module))
                self.modules.pop(name, None)
        self.meters.set_targets(meter_targets)

    def snapshot(self):
        now = time.monotonic()
        tracks = []
        recording = bool(self.recorder_state and self.recorder_state())
        graph = list(self.graph.values())
        consumers = {
            node["id"]
            for node in graph_objects(graph, "Node")
            if str(props(node).get("application.process.binary", "")).rsplit("/", 1)[-1]
            in {"gpu-screen-recorder", "gpu_screen_recorder"}
        }
        captured = {
            link["info"].get("output-node-id")
            for link in graph_objects(graph, "Link")
            if link["info"].get("input-node-id") in consumers
        }
        for source in self.configured():
            slot = dict(
                self.slots.get(
                    source,
                    {
                        "id": source,
                        "name": self.cfg.recording.audio_sources.get(source, {}).get(
                            "name"
                        )
                        or source,
                        "enabled": self.cfg.recording.audio_sources.get(source, {}).get(
                            "enabled", True
                        ),
                        "nodes": [],
                        "linked": False,
                    },
                )
            )
            levels = self.meters.read(slot.get("monitor", ""))
            if levels and max(levels) > 0.003:
                self.last_signal[source] = now
            from .audio_warnings import preferences

            threshold = preferences(self.cfg.recording.audio_warning_preferences)[
                "silence_seconds"
            ]
            if not slot.get("playing") or not slot.get("linked"):
                self.last_signal[source] = now
            self.last_signal.setdefault(source, now)
            quiet = now - self.last_signal[source] > threshold
            slot["levels"] = levels
            slot["recording_connected"] = slot.get("capture_node") in captured
            if not slot["enabled"]:
                state = "disabled"
            elif self.error == "tools_missing" or not self.backend_supported:
                state = "unsupported"
            elif self.error or not slot.get("monitor"):
                state = "disconnected"
            elif (
                source == AUTO_GAME
                and not self.target
                and not self.cfg.recording.audio_sources.get(source, {}).get("rules")
            ):
                state = "missing_game"
            elif not slot.get("nodes"):
                state = "missing_stream"
            elif (
                not slot.get("linked") or recording and not slot["recording_connected"]
            ):
                state = "disconnected"
            elif slot.get("source_muted") or slot.get("gain", 1) <= 0:
                state = "muted"
            elif levels is None:
                state = "meter_unavailable"
            elif quiet and slot.get("playing"):
                state = "quiet"
            elif max(levels) > 0.003:
                state = "active"
            else:
                state = "connected"
            slot["state"] = state
            slot["recording"] = recording
            tracks.append(slot)
        from .recorder import _separate_track_layout

        layout, mixed = _separate_track_layout(self.cfg.recording)
        if not layout and self.cfg.recording.capture_audio:
            layout = [self.cfg.recording.gsr_audio_source]

        def belongs(stream, source):
            if managed(source):
                return stream.node_id in self.slots.get(source, {}).get("nodes", [])
            if source.startswith("app:"):
                return stream.name.casefold() == source[4:].casefold()
            if source.startswith("app-inverse:"):
                return stream.name.casefold() != source[12:].casefold()
            return False

        applications = []
        for stream in self.streams:
            item = asdict(stream)
            item["levels"] = self.meters.read(
                sink_name("meter:" + str(stream.serial or stream.node_id)) + ".monitor"
            )
            item["tracks"] = [
                i + 1
                for i, source in enumerate(layout)
                if not (mixed and i == 0)
                and any(belongs(stream, part) for part in source.split("|"))
            ]
            applications.append(item)
        return {
            "supported": bool(self.tasks),
            "backend_supported": self.backend_supported,
            "error": self.error,
            "meter_error": self.meters.error,
            "tracks": tracks,
            "warnings": self.warning_policy.update(
                tracks, self.cfg.recording.audio_warning_preferences, self.error
            ),
            "applications": applications,
            "recording": recording,
        }

    async def _publish_loop(self):
        while True:
            for tid, (folder, created) in list(self.tests.items()):
                if time.monotonic() - created > 600:
                    self.delete_test(tid)
            snapshot = self.snapshot()
            viewing = self.viewing()
            if not viewing:
                snapshot["applications"] = []
                for track in snapshot["tracks"]:
                    track["levels"] = None
            serialized = json.dumps(snapshot, sort_keys=True)
            if self.publish and (viewing or serialized != self._last_status):
                await self.publish({"type": "audio_state", "audio": snapshot})
                self._last_status = serialized
            await asyncio.sleep(0.1 if self.viewing() else 1)

    def delete_test(self, tid):
        item = self.tests.pop(tid, None)
        if item:
            shutil.rmtree(item[0], ignore_errors=True)

    async def capture_test(self):
        import tempfile, uuid, wave, math, array
        from pathlib import Path
        from .recorder import _separate_track_layout

        # Do not manipulate GSR or flush its buffer to test audio.
        layout, _ = _separate_track_layout(self.cfg.recording)
        if not layout:
            layout = (
                [self.cfg.recording.gsr_audio_source]
                if self.cfg.recording.capture_audio
                else []
            )
        layout = layout[:16]
        while len(self.tests) >= 8:
            self.delete_test(next(iter(self.tests)))
        tid = uuid.uuid4().hex
        folder = Path(tempfile.mkdtemp(prefix="vice-audio-test-"))
        self.tests[tid] = (folder, time.monotonic())

        async def sample(index, source):
            name = (
                self.cfg.recording.audio_sources.get(source, {}).get("name") or source
            )
            result = {
                "index": index,
                "name": name,
                "source": source,
                "state": "unsupported",
            }
            if managed(source):
                slot = self.slots.get(source, {})
                if not slot.get("enabled", True):
                    return dict(result, state="disabled")
                device = slot.get("monitor")
                if not device or not slot.get("linked"):
                    return dict(result, state="disconnected")
            elif source == "default_output":
                device = (
                    await self.command("pactl", "get-default-sink")
                ).strip() + ".monitor"
            elif source == "default_input":
                device = (await self.command("pactl", "get-default-source")).strip()
            elif source.startswith("device:"):
                device = source[7:]
            else:
                return result
            try:
                path = folder / (str(index) + ".wav")
                await self.command(
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "pulse",
                    "-i",
                    device,
                    "-t",
                    "3",
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_s16le",
                    "-y",
                    str(path),
                    timeout=10,
                    env=capture_environment() if managed(source) else None,
                )

                def analyze():
                    with wave.open(str(path)) as audio:
                        data = array.array("h", audio.readframes(audio.getnframes()))
                    import sys

                    if sys.byteorder != "little":
                        data.byteswap()
                    peak = [
                        max(
                            (abs(value) / 32768 for value in data[channel::2]),
                            default=0,
                        )
                        for channel in (0, 1)
                    ]
                    rms = math.sqrt(
                        sum((value / 32768) ** 2 for value in data) / max(1, len(data))
                    )
                    return peak, 20 * math.log10(max(1e-9, rms))

                peak, db = await asyncio.to_thread(analyze)
                return dict(
                    result,
                    state="captured" if db > -65 else "quiet",
                    levels=peak,
                    rms_db=db,
                    url=f"/api/audio/tests/{tid}/{index}",
                )
            except (OSError, RuntimeError, asyncio.TimeoutError, wave.Error):
                return dict(result, state="disconnected")

        try:
            return {
                "id": tid,
                "duration": 3,
                "tracks": await asyncio.gather(
                    *(sample(i, source) for i, source in enumerate(layout))
                ),
            }
        except BaseException:
            self.delete_test(tid)
            raise
