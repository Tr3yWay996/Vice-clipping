# Screenshot capture latency

The previous path awaited compositor/game detection before it started GSR, then
awaited clipboard copying before accepting another screenshot. The first image
WebSocket event also waited for FFmpeg thumbnail generation and dimension probing.
An explicitly selected monitor could trigger another GSR monitor-enumeration
process even though recording had already validated that target.

The new path starts the capture task first. It can reuse the existing game
observer's recognized snapshot (up to six seconds old); otherwise it resolves
identity concurrently and attaches the stable game ID after registration.
It does not mutate the replay clip's pending game identity. Async follow-ups
check the media content revision so a replaced/trashed source is not mis-tagged.
A recently observed game can still be slightly out of date after a rapid switch;
manual reassignment is available in Detected Games.

The daemon registers an image only after GSR successfully writes a nonempty
file. A lightweight image event arrives immediately; the existing thumbnail and
metadata worker enriches that same card afterward. Clipboard work and failure
notifications run independently. Transfers retain hotkey order, and a burst of
screenshots shares an in-flight compositor lookup rather than launching duplicate
window scans. PNG output, resolution, quality and replay-buffer
recording arguments are unchanged. Timeout/cancellation kills and reaps the
one-shot GSR process and removes its partial image.

Screenshots reuse a monitor target already validated by the recorder. Cold
resolution runs in a worker; source/selected-target changes use a different cache
key, and failures invalidate that target. This avoids an unnecessary monitor
probe on the hot path. GSR's existing one-shot image operation is retained:
there is no established persistent screenshot command protocol in this backend,
and adding a second persistent GPU capture session would risk replay recording.

## Measured scheduling comparison

Run from the checkout with its test dependencies:

```sh
.venv/bin/python tools/benchmark-screenshots.py --baseline-ref 36d1173
.venv/bin/python tools/benchmark-screenshots.py
```

The benchmark uses real asyncio/thread scheduling with controlled delays:
200 ms compositor detection, 30 ms capture/write, 150 ms clipboard copying.
It uses temporary fixture bytes, not the desktop, recorder or system clipboard.
Five-run medians from this implementation session:

| Time since request | Before | After |
| --- | ---: | ---: |
| Capture started | 201.1 ms | 0.6 ms |
| Image written | 231.4 ms | 30.9 ms |
| Registered in library | 231.8 ms | 31.1 ms |
| Clipboard completed | 382.2 ms | 181.6 ms |

These measurements demonstrate removed blocking dependencies. They are **not
NVIDIA/KDE hardware latency measurements**. This environment cannot capture a
real CachyOS/Plasma/NVIDIA desktop; GPU initialization, encoding and disk latency
still need measurement there. The implementation makes no hardware speed claim.

## Diagnostics on the actual machine

The existing Vice log now records:

- Hotkey received and accepted (monotonic clock).
- Capture start and elapsed time since the request.
- Target resolution and GSR subprocess startup duration.
- Combined GSR capture/encoding/write duration and exit status.
- Verified image write and library registration.
- Thumbnail and metadata processing times.
- Clipboard completion and whether copying succeeded.

GSR exposes capture/encoding/write as one image-producing operation, so its
internal GPU acquisition, encoding and disk stages cannot be separated reliably
from the daemon alone. Compare these logged stages over several screenshots;
monitor detection and clipboard stalls are now distinguishable from GSR time.
If a focused-app hotkey blocklist is configured, its focus check remains required
and its time is included between hotkey receipt and capture start.
