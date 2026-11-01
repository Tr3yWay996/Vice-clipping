"""Pure PipeWire routing plans. Never reroute an application's audible output."""

from __future__ import annotations
import hashlib
import os

AUTO_GAME = "auto:game"


def managed(source):
    return source == AUTO_GAME or source.startswith("rule:")


def sink_name(source):
    return (
        f"vice_capture_{os.getuid()}_"
        + hashlib.sha256(source.encode()).hexdigest()[:16]
    )


def graph_objects(graph, kind):
    return [
        item
        for item in graph
        if item.get("type", "").endswith(":" + kind)
        and isinstance(item.get("info"), dict)
    ]


def props(item):
    return item.get("info", {}).get("props") or {}


def port_pairs(graph, node_ids, destination, *, allow_monitor=False):
    """Match actual channel ports, duplicate mono, never link a desktop monitor."""
    ports = graph_objects(graph, "Port")
    inputs = {
        props(p).get("audio.channel"): p["id"]
        for p in ports
        if str(props(p).get("node.id")) == str(destination)
        and props(p).get("port.direction") == "in"
    }
    result = set()
    for node in node_ids:
        outputs = {
            props(p).get("audio.channel"): p["id"]
            for p in ports
            if str(props(p).get("node.id")) == str(node)
            and props(p).get("port.direction") == "out"
            and (allow_monitor or not props(p).get("port.monitor"))
        }
        for channel in ("FL", "FR"):
            output = outputs.get(channel, outputs.get("MONO"))
            if output is not None and channel in inputs:
                result.add((output, inputs[channel]))
    return result


def game_nodes(streams, target):
    if not target:
        return []
    # Executable matching reconnects an unchanged game after process restart.
    # A shared middleware name (FMOD, SDL, Wine) is never an identity.
    executable = target.get("executable", "").casefold()
    generic = {
        "wine",
        "wine64",
        "wine-preloader",
        "wine64-preloader",
        "fmod audio",
        "sdl application",
    }
    browsers = {"zen", "firefox", "chrome", "chromium", "discord", "steamwebhelper"}
    path = target.get("executable_path", "")
    return [
        stream
        for stream in streams
        if stream.executable.casefold() not in browsers
        and (
            (stream.pid and stream.pid in target.get("pids", []))
            or (
                executable
                and executable not in generic
                and stream.executable.casefold() == executable
                and (not path or stream.executable_path == path)
            )
        )
    ]


def capture_pairs(graph, node):
    """Only explicitly targeted, fail-closed consumers may read a private sink."""
    identity = props(node)
    targets = {
        str(node["id"]),
        str(identity.get("object.serial")),
        identity.get("node.name"),
    }
    result = set()
    for consumer in graph_objects(graph, "Node"):
        cp = props(consumer)
        if (
            cp.get("media.class") != "Stream/Input/Audio"
            or str(cp.get("target.object")) not in targets
        ):
            continue
        if cp.get("node.dont-fallback") not in (True, "true"):
            continue
        result |= port_pairs(graph, [node["id"]], consumer["id"], allow_monitor=True)
    return result


def capture_environment():
    """Libpulse streams wait for their named device; never record the default mic."""
    environment = os.environ.copy()
    environment["PULSE_PROP"] = (
        environment.get("PULSE_PROP", "") + " node.dont-fallback=true node.linger=true"
    )
    return environment
