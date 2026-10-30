"""Owned, pausable FFmpeg execution shared by trims and editor exports."""
from __future__ import annotations
import asyncio
import math
import os
import signal
import sys
import time
from typing import Callable, Optional


def signal_group(proc, signum: int) -> bool:
    """Only use with children spawned in their own session by MediaProcess."""
    try:
        os.killpg(proc.pid, signum)
        return True
    except (ProcessLookupError, TypeError):
        if signum == signal.SIGKILL:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        return False


class MediaProcess:
    def __init__(self):
        self.proc = None
        self.paused = False
        self.on_state: Optional[Callable[[], None]] = None

    def pause(self) -> bool:
        if self.proc is None or self.proc.returncode is not None or self.paused:
            return False
        if not signal_group(self.proc, signal.SIGSTOP):
            return False
        self.paused = True
        return True

    def resume(self) -> bool:
        if self.proc is None or self.proc.returncode is not None or not self.paused:
            return False
        if not signal_group(self.proc, signal.SIGCONT):
            return False
        self.paused = False
        return True

    async def run(self, cmd: list[str], total: float = 0, progress=None,
                  timeout: float | None = None, on_spawn=None) -> tuple[int, str]:
        from .editor import parse_progress
        # Leave non-FFmpeg test commands untouched. FFmpeg reads progress on
        # stdout; bounded stderr is drained concurrently throughout suspension.
        cmd = list(cmd)
        if cmd and os.path.basename(cmd[0]) == 'ffmpeg':
            if '-progress' not in cmd:
                cmd[1:1] = ['-progress', 'pipe:1', '-nostats']
            cmd[1:1] = ['-threads', '2', '-filter_threads', '2', '-filter_complex_threads', '2']
            cmd[-1:-1] = ['-threads', '2']
            if 'libx265' in cmd and '-x265-params' not in cmd:
                cmd[-1:-1] = ['-x265-params', 'pools=2:frame-threads=2']
        if sys.platform.startswith('linux'):
            cmd = [sys.executable, '-m', 'vice.processing', '--parent', str(os.getpid()), '--', *cmd]
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True))
        proc = None
        drain = None
        stderr = bytearray()
        try:
            proc = await asyncio.shield(spawn)
            self.proc = proc
            try:
                os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
            except (OSError, TypeError):
                pass
            if on_spawn:
                on_spawn(proc)
            if self.on_state:
                self.on_state()
            async def read_errors():
                while True:
                    chunk = await proc.stderr.read(4096)
                    if not chunk:
                        break
                    stderr.extend(chunk)
                    del stderr[:-4096]
            drain = asyncio.create_task(read_errors())
            async def read_progress():
                last = 0.0
                speed = None
                while True:
                    raw = await proc.stdout.readline()
                    if not raw:
                        break
                    line = raw.decode(errors='replace').strip()
                    if line.startswith('speed='):
                        try:
                            speed = float(line.split('=', 1)[1].rstrip('x'))
                            if not math.isfinite(speed) or speed <= 0:
                                speed = None
                        except ValueError:
                            speed = None
                    fraction = parse_progress(line, total)
                    now = time.monotonic()
                    if fraction is not None and progress and (now - last >= .25 or fraction >= 1):
                        last = now
                        await progress(fraction, speed)
                await proc.wait()
                await drain
            if timeout:
                await asyncio.wait_for(read_progress(), timeout)
            else:
                await read_progress()
            return proc.returncode, bytes(stderr).decode(errors='replace').strip()[-4096:]
        finally:
            if proc is None:
                try:
                    proc = await spawn
                except OSError:
                    pass
            if proc is not None and proc.returncode is None:
                if self.paused:
                    signal_group(proc, signal.SIGCONT)
                signal_group(proc, signal.SIGKILL)
            if drain:
                drain.cancel()
                await asyncio.gather(drain, return_exceptions=True)
            if proc is not None:
                await proc.communicate()
            self.proc = None
            self.paused = False
            if self.on_state:
                self.on_state()


def _exec_owned_child():
    # A separate tiny exec wrapper avoids preexec_fn in the threaded daemon.
    # It also protects direct (non-systemd) launches from orphan encoders after
    # SIGKILL. systemd's control-group cleanup remains an additional safeguard.
    import ctypes
    parent = int(sys.argv[sys.argv.index('--parent') + 1])
    command = sys.argv[sys.argv.index('--') + 1:]
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot configure child ownership')
    if os.getppid() != parent:
        raise SystemExit(1)
    os.execvp(command[0], command)


if __name__ == '__main__':
    _exec_owned_child()
