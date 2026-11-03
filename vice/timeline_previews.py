"""Bounded, asynchronous editor analysis. Cache identity includes content changes."""

import array
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path


class TimelinePreviews:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = asyncio.Semaphore(2)
        self.jobs = {}

    def key(self, path, kind, *args):
        st = path.stat()
        return hashlib.sha256(
            repr(
                (
                    str(path),
                    st.st_dev,
                    st.st_ino,
                    st.st_size,
                    st.st_mtime_ns,
                    st.st_ctime_ns,
                    kind,
                    args,
                )
            ).encode()
        ).hexdigest()

    async def get(self, path, kind, offset, duration=0, stream=0):
        key = self.key(path, kind, offset, duration, stream)
        dest = self.root / (key + (".json" if kind == "wave" else ".jpg"))
        if dest.is_file():
            return dest
        if key not in self.jobs and len(self.jobs) >= 64:
            raise RuntimeError("Analysis queue full")
        if key not in self.jobs:
            self.jobs[key] = asyncio.create_task(
                self.generate(path, dest, kind, offset, duration, stream)
            )
        try:
            return await asyncio.shield(self.jobs[key])
        finally:
            if self.jobs.get(key) and self.jobs[key].done():
                self.jobs.pop(key, None)

    async def generate(self, path, dest, kind, offset, duration, stream):
        async with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp" + dest.suffix)
            cmd = ["ffmpeg", "-v", "error", "-ss", str(offset), "-i", str(path)]
            if kind == "wave":
                cmd += [
                    "-t",
                    str(duration),
                    "-map",
                    f"0:a:{stream}",
                    "-vn",
                    "-ac",
                    "2",
                    "-ar",
                    "8000",
                    "-f",
                    "f32le",
                    "pipe:1",
                ]
            else:
                cmd += [
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=160:-2",
                    "-threads",
                    "1",
                    "-y",
                    str(tmp),
                ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            try:

                async def analyze():
                    peaks = [0.0] * 1024
                    frame = 0
                    pending = b""
                    while True:
                        data = await proc.stdout.read(65536)
                        if not data:
                            break
                        data = pending + data
                        size = len(data) // 8 * 8
                        pending = data[size:]
                        values = array.array("f")
                        values.frombytes(data[:size])
                        import sys

                        if sys.byteorder != "little":
                            values.byteswap()
                        for i in range(0, len(values), 2):
                            bucket = min(1023, int(frame / (duration * 8000) * 1024))
                            frame += 1
                            level = max(abs(values[i]), abs(values[i + 1]))
                            if math.isfinite(level):
                                peaks[bucket] = max(peaks[bucket], min(1, level))
                        await asyncio.sleep(0)
                    await proc.wait()
                    if proc.returncode:
                        raise RuntimeError("Audio analysis failed")
                    tmp.write_text(
                        json.dumps(
                            {
                                "peaks": peaks,
                                "offset": offset,
                                "duration": duration,
                                "stream": stream,
                            }
                        )
                    )

                if kind == "wave":
                    await asyncio.wait_for(analyze(), 120)
                else:
                    await asyncio.wait_for(proc.communicate(), 30)
                    if proc.returncode or not tmp.is_file():
                        raise RuntimeError("Thumbnail extraction failed")
                tmp.replace(dest)
                # Bound retained analysis files; no scan or decoding during pointer moves.
                files = sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime)
                for old in files[:-512]:
                    if old != dest and ".tmp" not in old.name:
                        old.unlink(missing_ok=True)
                return dest
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()
                tmp.unlink(missing_ok=True)

    async def close(self):
        for task in self.jobs.values():
            task.cancel()
        await asyncio.gather(*self.jobs.values(), return_exceptions=True)
        self.jobs.clear()
