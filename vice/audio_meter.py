"""Native Pulse peak streams, including on pipewire-pulse. No PCM in React.

Each source is explicitly named; no default-device fallback is permitted.
The server downsamples peaks to 25 Hz. All libpulse calls stay on one thread.
"""

from __future__ import annotations
import ctypes as C
import ctypes.util
import math
import threading
import time


class SampleSpec(C.Structure):
    _fields_ = [("format", C.c_int), ("rate", C.c_uint32), ("channels", C.c_uint8)]


class PeakMonitor:
    def __init__(self):
        self.targets = set()
        self.levels = {}
        self.error = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def set_targets(self, targets):
        with self._lock:
            self.targets = set(targets)
        if targets and (not self._thread or not self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="vice-audio-peaks"
            )
            self._thread.start()

    def read(self, source):
        with self._lock:
            value = self.levels.get(source)
        if not value or time.monotonic() - value[0] > 2:
            return None
        return value[1]

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self):
        loop = context = None
        streams = {}
        retry = {}
        p = None
        try:
            name = ctypes.util.find_library("pulse")
            # Nix may expose the library through LD_LIBRARY_PATH without an
            # ldconfig entry or compiler available to ctypes.find_library.
            p = C.CDLL(name or "libpulse.so.0")

            def bind(name, ret, args):
                fn = getattr(p, name)
                fn.restype = ret
                fn.argtypes = args
                return fn

            ptr = C.c_void_p
            I = C.c_int
            S = C.c_char_p
            bind("pa_mainloop_new", ptr, [])
            bind("pa_mainloop_get_api", ptr, [ptr])
            bind("pa_mainloop_iterate", I, [ptr, I, C.POINTER(I)])
            bind("pa_mainloop_free", None, [ptr])
            bind("pa_context_new", ptr, [ptr, S])
            bind("pa_context_connect", I, [ptr, S, I, ptr])
            bind("pa_context_get_state", I, [ptr])
            bind("pa_context_disconnect", None, [ptr])
            bind("pa_context_unref", None, [ptr])
            bind("pa_proplist_new", ptr, [])
            bind("pa_proplist_sets", I, [ptr, S, S])
            bind("pa_proplist_free", None, [ptr])
            bind(
                "pa_stream_new_with_proplist",
                ptr,
                [ptr, S, C.POINTER(SampleSpec), ptr, ptr],
            )
            bind("pa_stream_connect_record", I, [ptr, S, ptr, I])
            bind("pa_stream_disconnect", I, [ptr])
            bind("pa_stream_unref", None, [ptr])
            bind("pa_stream_get_state", I, [ptr])
            bind("pa_stream_peek", I, [ptr, C.POINTER(ptr), C.POINTER(C.c_size_t)])
            bind("pa_stream_drop", I, [ptr])
            callback = C.CFUNCTYPE(None, ptr, C.c_size_t, ptr)
            bind("pa_stream_set_read_callback", None, [ptr, callback, ptr])
            loop = p.pa_mainloop_new()
            context = p.pa_context_new(
                p.pa_mainloop_get_api(loop), b"Vice capture meters"
            )
            if p.pa_context_connect(context, None, 0, None) < 0:
                raise RuntimeError("Pulse connection failed")
            started = time.monotonic()
            while not self._stop.is_set():
                p.pa_mainloop_iterate(loop, 0, None)
                state = p.pa_context_get_state(context)
                if state in (5, 6) or (state != 4 and time.monotonic() - started > 5):
                    raise RuntimeError("Pulse audio server unavailable")
                if state == 4:
                    with self._lock:
                        targets = set(self.targets)
                    for source in list(streams):
                        stream, reader = streams[source]
                        if source not in targets or p.pa_stream_get_state(stream) in (
                            3,
                            4,
                        ):
                            p.pa_stream_disconnect(stream)
                            p.pa_stream_unref(stream)
                            del streams[source]
                            retry[source] = time.monotonic() + 1
                            with self._lock:
                                self.levels.pop(source, None)
                    for source in targets - streams.keys():
                        if retry.get(source, 0) > time.monotonic():
                            continue

                        def read(stream, nbytes, userdata, source=source):
                            data = ptr()
                            size = C.c_size_t()
                            if (
                                p.pa_stream_peek(stream, C.byref(data), C.byref(size))
                                < 0
                            ):
                                return
                            if size.value:
                                levels = [0.0, 0.0]
                                if data.value:
                                    count = size.value // 4
                                    values = C.cast(data, C.POINTER(C.c_float))
                                    for i in range(count):
                                        sample = float(values[i])
                                        channel = i % 2
                                        if math.isfinite(sample):
                                            levels[channel] = max(
                                                levels[channel], min(1.0, abs(sample))
                                            )
                                with self._lock:
                                    self.levels[source] = (time.monotonic(), levels)
                                p.pa_stream_drop(stream)

                        reader = callback(read)
                        spec = SampleSpec(5, 25, 2)  # PA_SAMPLE_FLOAT32LE
                        properties = p.pa_proplist_new()
                        p.pa_proplist_sets(properties, b"node.dont-fallback", b"true")
                        p.pa_proplist_sets(properties, b"node.linger", b"true")
                        stream = p.pa_stream_new_with_proplist(
                            context,
                            b"Vice capture path peaks",
                            C.byref(spec),
                            None,
                            properties,
                        )
                        p.pa_proplist_free(properties)
                        if not stream:
                            continue
                        p.pa_stream_set_read_callback(stream, reader, None)
                        # PEAK_DETECT | DONT_MOVE | ADJUST_LATENCY. Explicit source only.
                        if (
                            p.pa_stream_connect_record(
                                stream, source.encode(), None, 0x800 | 0x200 | 0x2000
                            )
                            < 0
                        ):
                            p.pa_stream_unref(stream)
                            retry[source] = time.monotonic() + 1
                            continue
                        streams[source] = (stream, reader)
                    self.error = None
                self._stop.wait(0.01)
        except Exception as exc:
            self.error = str(exc)
        finally:
            if p:
                for stream, reader in streams.values():
                    p.pa_stream_disconnect(stream)
                    p.pa_stream_unref(stream)
                if context:
                    p.pa_context_disconnect(context)
                    p.pa_context_unref(context)
                if loop:
                    p.pa_mainloop_free(loop)
