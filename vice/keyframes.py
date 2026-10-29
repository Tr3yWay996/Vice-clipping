"""Asynchronous, bounded keyframe analysis of the original video stream."""
from __future__ import annotations

import asyncio
import json
import math
from collections import OrderedDict
from fractions import Fraction
from pathlib import Path

from .media import communicate_with_timeout, media_revision


def _number(value) -> float | None:
    try:
        result = float(Fraction(str(value)))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def parse_keyframes(data: dict) -> dict:
    """Use presentation timestamps, relative to the player's container origin.

    nb_frames is exact when the container supplies it. Counting every decoded
    frame would defeat the keyframe-only probe, so otherwise label an estimate.
    Never infer keyframes or frame intervals from the nominal frame rate.
    """
    if not isinstance(data, dict) or not isinstance(data.get("streams"), list):
        raise ValueError("Invalid video metadata")
    stream = next((s for s in data["streams"] if isinstance(s, dict) and s.get("codec_type") == "video"), None)
    if stream is None:
        raise ValueError("No video stream was found")
    fmt = data.get("format") or {}
    if not isinstance(fmt, dict):
        raise ValueError("Invalid container metadata")
    origin = _number(fmt.get("start_time"))
    if origin is None:
        origin = _number(stream.get("start_time")) or 0
    duration = _number(stream.get("duration")) or _number(fmt.get("duration"))
    timestamps = set()
    frames = data.get("frames") or []
    if not isinstance(frames, list):
        raise ValueError("Invalid frame metadata")
    for frame in frames:
        if not isinstance(frame, dict) or frame.get("key_frame") != 1:
            continue
        timestamp = _number(frame.get("pts_time"))
        if timestamp is None:
            timestamp = _number(frame.get("best_effort_timestamp_time"))
        if timestamp is None:
            continue
        timestamp -= origin
        if timestamp >= -1e-6 and (duration is None or timestamp <= duration + 1e-6):
            timestamps.add(max(0, timestamp))
    times = sorted(timestamps)
    intervals = [b - a for a, b in zip(times, times[1:])]
    average = _number(stream.get("avg_frame_rate"))
    nominal = _number(stream.get("r_frame_rate"))
    count = _number(stream.get("nb_frames"))
    exact = count is not None and count > 0 and count.is_integer()
    count = int(count) if exact else round(duration * average) if duration and average and average > 0 else None
    return {
        "timestamps": times,
        "total_keyframes": len(times),
        "total_frames": count,
        "frames_estimated": not exact,
        "average_fps": average if average and average > 0 else None,
        "nominal_fps": nominal if nominal and nominal > 0 else None,
        "average_interval": sum(intervals) / len(intervals) if intervals else None,
        "min_interval": min(intervals) if intervals else None,
        "max_interval": max(intervals) if intervals else None,
    }


async def probe_keyframes(path: Path) -> dict:
    # Decode only keyframes, including HEVC/H.264 with reordered B frames.
    # Output grows with keyframes, not with all video packets or raw pixels.
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-skip_frame", "nokey", "-show_frames", "-show_streams", "-show_format",
        "-show_entries",
        "frame=key_frame,pts_time,best_effort_timestamp_time:"
        "stream=codec_type,start_time,duration,nb_frames,avg_frame_rate,r_frame_rate:"
        "format=start_time,duration", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    ))
    proc = None
    try:
        proc = await asyncio.shield(spawn)
        stdout, _ = await communicate_with_timeout(proc, timeout=120)
        if proc.returncode:
            raise ValueError("FFprobe could not analyze this recording")
        return await asyncio.to_thread(lambda: parse_keyframes(json.loads(stdout)))
    finally:
        # Keep ownership even when shutdown arrives during process creation.
        if proc is None:
            try:
                proc = await spawn
            except OSError:
                pass
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.communicate()


class KeyframeCache:
    """Reuse unchanged analyses; coalesce requests and bound retained results."""
    def __init__(self):
        self._results: OrderedDict[tuple, dict] = OrderedDict()
        self._pending: dict[tuple, asyncio.Task] = {}
        self._slots = asyncio.Semaphore(2)

    def invalidate(self, path: Path) -> None:
        for key in list(self._results):
            if key[0] == path:
                del self._results[key]
        # An older in-flight request can finish for its caller, but must never
        # publish an index for the newly replaced recording.

    async def get(self, path: Path) -> dict:
        key = (path, media_revision(path))
        if key in self._results:
            self._results.move_to_end(key)
            return self._results[key]
        if key not in self._pending:
            self._pending[key] = asyncio.create_task(self._analyze(key))
        return await asyncio.shield(self._pending[key])

    async def _analyze(self, key: tuple) -> dict:
        try:
            async with self._slots:
                result = await probe_keyframes(key[0])
            if media_revision(key[0]) != key[1]:
                raise ValueError("Recording changed during analysis; reopen the clip")
            self._results[key] = result
            while len(self._results) > 32 or sum(len(r["timestamps"]) for r in self._results.values()) > 500_000:
                self._results.popitem(last=False)
            return result
        finally:
            self._pending.pop(key, None)

    async def close(self) -> None:
        tasks = list(self._pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
