"""Compact PipeWire identities and explicit application matching.

Playback identity is not an audio-level measurement or proof of capture.
"""

from __future__ import annotations
import json
import shutil
import subprocess
from dataclasses import dataclass

MATCH_FIELDS = ("name", "application_id", "executable", "executable_path", "node_name")


@dataclass(frozen=True)
class ApplicationStream:
    node_id: int
    serial: str
    name: str
    application_id: str
    executable: str
    executable_path: str
    pid: int
    node_name: str
    destination: str
    active: bool
    muted: bool = False

    def matches(self, rule: dict) -> bool:
        mode = rule.get("mode", "exact")
        field = rule.get("field", "name")
        value = rule.get("value")
        if field not in MATCH_FIELDS or mode not in {"exact", "contains", "regex"}:
            raise ValueError("Invalid audio match field or mode")
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError("Audio match must contain 1 to 256 characters")
        text = getattr(self, field)
        if mode == "exact":
            return text.casefold() == value.casefold()
        if mode == "contains":
            return value.casefold() in text.casefold()
        # Arbitrary regex execution is deliberately not performed here. It must
        # run in an isolated, time-bounded matcher before being exposed to UI.
        raise ValueError("Regex matching requires an isolated execution worker")


def parse_streams(graph) -> list[ApplicationStream]:
    if not isinstance(graph, list):
        raise ValueError("Invalid PipeWire graph")
    result = []
    for node in graph:
        if not isinstance(node, dict):
            continue
        info = node.get("info") or {}
        if not isinstance(info, dict):
            continue
        props = info.get("props") or {}
        if (
            not isinstance(props, dict)
            or props.get("media.class") != "Stream/Output/Audio"
        ):
            continue
        try:
            nid = int(node["id"])
            pid = int(props.get("application.process.id") or 0)
            if nid < 0 or pid < 0:
                continue
        except (ValueError, TypeError, KeyError):
            continue

        def text(key):
            value = props.get(key, "")
            return str(value)[:4096] if isinstance(value, (str, int)) else ""

        result.append(
            ApplicationStream(
                nid,
                text("object.serial"),
                text("application.name"),
                text("application.id"),
                text("application.process.binary"),
                text("application.process.path"),
                pid,
                text("node.name"),
                text("target.object"),
                info.get("state") == "running",
                any(
                    p.get("mute") is True
                    for p in (info.get("params", {}).get("Props", []) or [])
                    if isinstance(p, dict)
                ),
            )
        )
    return result


def inspect_streams() -> dict:
    """Read a finite graph snapshot, never return formats/params or media titles."""
    executable = shutil.which("pw-dump")
    if not executable:
        return {
            "applications": [],
            "application_warning": "PipeWire inspection requires pw-dump.",
        }
    try:
        process = subprocess.run(
            [executable], capture_output=True, text=True, timeout=3, check=True
        )
        streams = parse_streams(json.loads(process.stdout))
        from dataclasses import asdict

        return {
            "applications": [asdict(stream) for stream in streams],
            "application_warning": None,
        }
    except (OSError, subprocess.SubprocessError, ValueError):
        return {
            "applications": [],
            "application_warning": "PipeWire application inspection is unavailable.",
        }


def matching_nodes(
    streams: list[ApplicationStream], rules: list[dict]
) -> list[ApplicationStream]:
    """Multiple explicit rules form a union; all matching instances are retained."""
    # Validate every rule even when an earlier rule matches every stream.
    probe = ApplicationStream(0, "", "", "", "", "", 0, "", "", False)
    for rule in rules:
        probe.matches(rule)
    return [stream for stream in streams if any(stream.matches(rule) for rule in rules)]


def enrich_streams(streams, cache):
    """Resolve Wine executables/paths, invalidating cached process data on PID reuse."""
    from dataclasses import replace
    import psutil
    from .active_window import process_identity

    result = []
    live = set()
    for stream in streams:
        live.add(stream.pid)
        try:
            created = psutil.Process(stream.pid).create_time()
            known = cache.get(stream.pid)
            if not known or known[0] != created:
                known = (created, process_identity(stream.pid))
                cache[stream.pid] = known
            identity = known[1]
            native = identity.get("executable", "")
            executable = stream.executable
            if executable.casefold() in {
                "wine",
                "wine64",
                "wine-preloader",
                "wine64-preloader",
            } and native.casefold().endswith(".exe"):
                executable = native
            path = (
                identity.get("executable_path", "")
                if native.casefold() == executable.casefold()
                else stream.executable_path
            )
            stream = replace(stream, executable=executable, executable_path=path)
        except (psutil.Error, OSError):
            pass
        result.append(stream)
    for pid in list(cache):
        if pid not in live:
            cache.pop(pid, None)
    return result
