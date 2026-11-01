#!/usr/bin/env python3
"""Opt-in real PCM tests on an isolated PipeWire/WirePlumber 0.5+ instance.

Run from the repository root: python tools/test-smart-audio.py.
Does not require a GPU, an audible output, root, or a running desktop.
"""

import asyncio, json, math, os, sys, wave, array, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vice.audio_router import AudioRouter
from vice.config import Config
from vice.audio_graph import sink_name, capture_environment


async def wait(check, timeout=8):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if check():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("Timed out waiting for audio state")


def peak(path):
    with wave.open(str(path)) as f:
        values = array.array("h", f.readframes(f.getnframes()))
    return max(map(abs, values), default=0) / 32768


def amplitude(values, freq):
    # Coherent measurement on actual captured PCM, not merely metadata.
    samples = values[::2]
    n = min(len(samples), 48000)
    samples = samples[-n:]
    return (
        2
        * abs(
            sum(
                value
                / 32768
                * complex(
                    math.cos(2 * math.pi * freq * i / 48000),
                    math.sin(2 * math.pi * freq * i / 48000),
                )
                for i, value in enumerate(samples)
            )
        )
        / max(1, n)
    )


async def exercise(folder):
    cfg = Config()
    cfg.recording.audio_tracks = ["auto:game", "rule:music"]
    cfg.recording.audio_sources = {
        "auto:game": {"name": "Game"},
        "rule:music": {
            "name": "Music",
            "rules": [
                {"field": "executable", "mode": "exact", "value": "music-player"}
            ],
        },
    }
    target = None
    router = AudioRouter(cfg, game_target=lambda: target, recorder_state=lambda: True)
    players = []
    recorders = []
    try:
        await router.start()
        await router.ensure_tracks()
        router.monitor_view("integration", True)
        try:
            await router.command(
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=test_speakers",
                "channels=2",
            )
        except RuntimeError:
            pass
        await router.command("pactl", "set-default-sink", "test_speakers")
        for frequency in (440, 880, 330):
            await router.command(
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:duration=35:sample_rate=48000",
                "-ac",
                "2",
                "-y",
                str(folder / f"{frequency}.wav"),
            )
        await wait(lambda: router.slots.get("auto:game", {}).get("monitor"))
        originalMonitor = router.slots["auto:game"]["monitor"]
        # Keep one recorder client alive while sources come and go.
        raw = open(str(folder / "continuous.raw"), "wb")
        recorder = await asyncio.create_subprocess_exec(
            "parec",
            "--raw",
            "--format=s16le",
            "--rate=48000",
            "--channels=2",
            "--device=" + originalMonitor,
            "--property=application.process.binary=gpu-screen-recorder",
            stdout=raw,
            env=capture_environment(),
        )
        recorders.append(recorder)
        await asyncio.sleep(0.4)

        async def play(name, binary, freq):
            proc = await asyncio.create_subprocess_exec(
                "paplay",
                "--device=test_speakers",
                "--property=application.name=" + name,
                "--property=application.process.binary=" + binary,
                str(folder / f"{freq}.wav"),
                stderr=asyncio.subprocess.DEVNULL,
            )
            players.append(proc)
            return proc

        music = await play("Music", "music-player", 880)
        beam = await play("FMOD Audio", "BeamNG.drive.x64", 440)
        target = {"executable": "BeamNG.drive.x64", "pids": [beam.pid]}
        router.changed.set()
        await wait(
            lambda: any(
                track["state"] == "active"
                for track in router.snapshot()["tracks"]
                if track["id"] == "auto:game"
            )
        )
        await wait(
            lambda: any(
                app["levels"] and max(app["levels"]) > 0.01
                for app in router.snapshot()["applications"]
            )
        )
        sample = await router.capture_test()
        assert [track["state"] for track in sample["tracks"]] == [
            "captured",
            "captured",
        ], sample
        game = router.tests[sample["id"]][0] / "0.wav"
        musicPath = router.tests[sample["id"]][0] / "1.wav"
        with wave.open(str(game)) as f:
            values = array.array("h", f.readframes(f.getnframes()))
        assert amplitude(values, 440) > 0.04 and amplitude(values, 880) < 0.002, (
            amplitude(values, 440),
            amplitude(values, 880),
        )
        assert peak(musicPath) > 0.04
        assert router.snapshot()["tracks"][0]["recording_connected"], router.snapshot()
        print(
            "PASS start before game, FMOD executable identity, actual stereo meters, recorder connection, separate music and game sample FFT",
            flush=True,
        )
        target = None
        router.changed.set()
        await asyncio.sleep(0.4)
        assert router.target["executable"] == "BeamNG.drive.x64"
        oldBeam = beam.pid
        beam.terminate()
        await beam.wait()
        await wait(
            lambda: not any(
                app["pid"] == oldBeam for app in router.snapshot()["applications"]
            )
        )
        beam = await play("FMOD Audio", "BeamNG.drive.x64", 440)
        await wait(
            lambda: any(
                app["pid"] == beam.pid and app["tracks"] == [1]
                for app in router.snapshot()["applications"]
            )
        )
        assert (
            recorder.returncode is None
            and router.slots["auto:game"]["monitor"] == originalMonitor
        )
        print(
            "PASS alt-tab retention and application restart/new node ids without restarting recording or changing track",
            flush=True,
        )
        rocket = await play("Rocket League", "RocketLeague.exe", 330)
        target = {"executable": "RocketLeague.exe", "pids": [rocket.pid]}
        router.changed.set()
        await wait(
            lambda: any(
                app["pid"] == rocket.pid and app["tracks"] == [1]
                for app in router.snapshot()["applications"]
            )
        )
        sample = await router.capture_test()
        game = router.tests[sample["id"]][0] / "0.wav"
        with wave.open(str(game)) as f:
            values = array.array("h", f.readframes(f.getnframes()))
        assert (
            amplitude(values, 330) > 0.04
            and amplitude(values, 440) < 0.002
            and amplitude(values, 880) < 0.002
        )
        assert recorder.returncode is None
        await router.command(
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=audible",
            "channels=2",
        )
        await router.command("pactl", "set-default-sink", "audible")
        # Explicitly move the game playback stream like a device switch/session manager.
        inputs = json.loads(
            await router.command("pactl", "-f", "json", "list", "sink-inputs")
        )
        stream = next(
            item
            for item in inputs
            if item.get("properties", {}).get("application.process.binary")
            == "RocketLeague.exe"
        )
        await router.command(
            "pactl", "move-sink-input", str(stream["index"]), "audible"
        )
        await asyncio.sleep(0.5)
        assert router.slots["auto:game"]["linked"] and recorder.returncode is None
        print(
            "PASS game switch excludes old game and music, output-device move retains private capture source",
            flush=True,
        )
        cfg.recording.audio_track_volumes["auto:game"] = 0.5
        router.changed.set()
        await wait(lambda: router.slots["auto:game"]["gain"] == 0.5)
        sample = await router.capture_test()
        half = peak(router.tests[sample["id"]][0] / "0.wav")
        assert 0.035 < half < 0.05, half
        cfg.recording.audio_sources["auto:game"]["enabled"] = False
        router.changed.set()
        await wait(lambda: router.snapshot()["tracks"][0]["state"] == "disabled")
        sample = await router.capture_test()
        assert sample["tracks"][0]["state"] == "disabled"
        print(
            "PASS live capture gain (measured half-amplitude), per-track disable, disposable test sample cleanup",
            flush=True,
        )
        assert recorder.returncode is None
        # Remove every normal output. Private capture nodes must never become defaults
        # or acquire normal playback links, even with no remaining real speakers.
        graph = json.loads(await router.command("pw-dump"))
        for node in graph:
            props = node.get("info", {}).get("props", {})
            if (
                props.get("media.class") == "Audio/Sink"
                and not props.get("wireplumber.is-virtual")
                and "pulse.module.id" in props
            ):
                await router.command(
                    "pactl", "unload-module", str(props["pulse.module.id"])
                )
        await asyncio.sleep(0.5)
        default = (await router.command("pactl", "get-default-sink")).strip()
        assert not default.startswith("vice_capture_"), default
        print(
            "PASS capture sinks cannot become system defaults after output devices disappear",
            flush=True,
        )
    finally:
        for proc in players + recorders:
            if proc.returncode is None:
                proc.terminate()
        await asyncio.gather(
            *(proc.wait() for proc in players + recorders), return_exceptions=True
        )
        if "raw" in locals():
            raw.close()
        await router.close()


def main():
    import tempfile, subprocess, shutil, signal

    required = (
        "pipewire",
        "pipewire-pulse",
        "wireplumber",
        "pw-dump",
        "pw-cli",
        "pw-link",
        "pactl",
        "parec",
        "paplay",
        "ffmpeg",
        "dbus-daemon",
    )
    missing = [tool for tool in required if not shutil.which(tool)]
    if missing:
        raise SystemExit("Missing native test tools: " + ", ".join(missing))
    # These processes own a fresh private socket and bus. Never use/restart the
    # desktop's services, default devices, routes, or configuration/state.
    with tempfile.TemporaryDirectory(prefix="vice-audio-integration-") as directory:
        folder = Path(directory)
        runtime = folder / "runtime"
        runtime.mkdir(mode=0o700)
        os.environ.update(
            XDG_RUNTIME_DIR=str(runtime),
            PULSE_SERVER="unix:" + str(runtime / "pulse/native"),
            PIPEWIRE_REMOTE="pipewire-0",
            XDG_STATE_HOME=str(folder / "state"),
            XDG_CONFIG_HOME=str(folder / "config"),
            XDG_CACHE_HOME=str(folder / "cache"),
            DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(runtime / "bus"),
        )
        processes = []
        logs = []
        try:
            for command in [
                [
                    "dbus-daemon",
                    "--session",
                    "--nofork",
                    "--address=" + os.environ["DBUS_SESSION_BUS_ADDRESS"],
                ],
                ["pipewire"],
                ["pipewire-pulse"],
                ["wireplumber"],
            ]:
                output = open(folder / (command[0] + ".log"), "wb")
                logs.append(output)
                processes.append(
                    subprocess.Popen(
                        command, stdout=output, stderr=output, start_new_session=True
                    )
                )
            for _ in range(100):
                result = subprocess.run(
                    ["pactl", "info"], capture_output=True, timeout=2
                )
                if result.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Private Pulse server did not start")
            asyncio.run(exercise(folder))
        except BaseException:
            for output in logs:
                output.flush()
                print(
                    Path(output.name).read_text(errors="replace")[-2000:],
                    file=sys.stderr,
                )
            raise
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
            for proc in processes:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            for output in logs:
                output.close()


if __name__ == "__main__":
    main()
