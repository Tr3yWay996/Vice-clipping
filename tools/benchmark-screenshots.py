"""Controlled scheduling benchmark: no GPU, recorder, clipboard or user media.

Run with the project's test dependencies. Optionally compare a pre-change ref:
  .venv/bin/python tools/benchmark-screenshots.py --baseline-ref 36d1173
"""
import asyncio, time, tempfile, statistics, sys, argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests import _sandbox
from vice.main import ViceDaemon
from vice.config import Config
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline-ref')
args=parser.parse_args()
if args.baseline_ref:
    import subprocess, textwrap
    source = subprocess.check_output(['git','show',args.baseline_ref+':vice/main.py'],text=True)
    method = source[source.index('    async def _take_screenshot('):source.index('    def _screenshot_task_done')]
    import vice.main as module
    namespace = {}
    exec(textwrap.dedent(method), module.__dict__, namespace)
    ViceDaemon._take_screenshot = namespace['_take_screenshot']
async def run():
    rows=[]
    with tempfile.TemporaryDirectory() as tmp:
        for _ in range(5):
            start=time.perf_counter(); stages={}
            daemon=ViceDaemon.__new__(ViceDaemon);daemon.cfg=Config();daemon._display_override=None
            daemon._last_clip_game=None;daemon._last_clip_game_id=None
            def detect():
                time.sleep(.2)
                return None
            async def capture(out,*args):
                stages['capture_started']=time.perf_counter()-start
                await asyncio.sleep(.03);out.write_bytes(b'fixture-image');stages['image_written']=time.perf_counter()-start
            async def clipboard(out):
                await asyncio.sleep(.15);stages['clipboard']=time.perf_counter()-start;return True,''
            def register(*args,**kwargs):stages['registered']=time.perf_counter()-start
            daemon._clip_game_tag=detect
            daemon._detect_recording_game=lambda: (detect(),None)
            daemon.share=SimpleNamespace(next_image_path=lambda tag:Path(tmp)/'shot.png',add_image=register,broadcast=AsyncMock())
            with patch('vice.main.capture_screenshot',capture),patch('vice.main.copy_image_to_clipboard',clipboard),patch('vice.main.audio.play_screenshot'):
                await daemon._take_screenshot()
                pending=getattr(daemon,'_screenshot_background',set())
                if pending: await asyncio.gather(*list(pending))
            rows.append(stages)
    print({key:round(statistics.median(row[key] for row in rows)*1000,2) for key in rows[0]})
asyncio.run(run())
