"""Opt-in X11 integration check: actual ClipCard -> QtWebEngine -> native receiver.

Requires npm ci, FFmpeg, xdotool, pywebview[qt], and an X11 display (or xvfb-run).
Runs outside unittest discovery because it controls the mouse on that display.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait_for(predicate, description, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise RuntimeError(description)
        time.sleep(.05)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def receiver(folder):
    from qtpy import QtWidgets
    app = QtWidgets.QApplication([])
    class Target(QtWidgets.QWidget):
        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
        def dragMoveEvent(self, event):
            event.acceptProposedAction()
        def dropEvent(self, event):
            path = Path(event.mimeData().urls()[0].toLocalFile())
            shutil.copy2(path, folder/'received.mp4')
            (folder/'drop.json').write_text(json.dumps({
                'path': str(path), 'clip': bytes(event.mimeData().data('application/x-vice-clip')).decode(),
                'action': event.proposedAction().name}))
            event.acceptProposedAction()
    target = Target()
    target.setAcceptDrops(True)
    target.setGeometry(600, 80, 300, 240)
    target.show()
    (folder/'receiver-ready').touch()
    app.exec()


def source(folder, vite_port, api_port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from vice.native_drag import drag_file, resolve_drag_file
    import webview
    original = folder/'Match été #1.mp4'
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/internal?slug=test-clip':
                (folder/'internal-drop').touch()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'path': str(original), 'uri': original.as_uri(),
                                         'filename': original.name, 'size': original.stat().st_size}).encode())
    threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', api_port), Handler).serve_forever, daemon=True).start()
    class API:
        def file_drag_capabilities(self):
            return True
        def drag_clip(self, slug, prepared=False, appearance=None):
            data = resolve_drag_file(f'http://127.0.0.1:{api_port}', slug, prepared)
            data['appearance'] = appearance or {}
            return drag_file(data)
    url = f'http://127.0.0.1:{vite_port}/{folder.relative_to(ROOT).as_posix()}/probe.html'
    window = webview.create_window('Vice drag check', url, js_api=API(), x=50, y=80, width=500, height=300)
    def ready():
        wait_for(lambda: window.evaluate_js('!!document.querySelector(".clip-card") && !!window.pywebview?.api?.drag_clip'),
                 'ClipCard or native bridge did not load')
        (folder/'source-ready').touch()
    window.events.loaded += ready
    webview.start(gui='qt', private_mode=False, storage_path=str(folder/'profile'))


def check():
    for executable in ['node', 'ffmpeg', 'xdotool']:
        if not shutil.which(executable):
            raise RuntimeError(f'{executable} is required')
    if not os.environ.get('DISPLAY'):
        raise RuntimeError('Use an isolated X11 display, for example xvfb-run -a')
    (ROOT/'work').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-smoke-', dir=ROOT/'work') as directory:
        folder = Path(directory)
        original = folder/'Match été #1.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=10:duration=1',
                        '-c:v', 'libx264', '-threads', '1', str(original)], check=True)
        vite_port, api_port = free_port(), free_port()
        origin = f'http://127.0.0.1:{api_port}'
        (folder/'probe.html').write_text('<div id="root"></div><script type="module" src="./probe.tsx"></script>')
        (folder/'probe.tsx').write_text('''
import React from 'react';
import {createRoot} from 'react-dom/client';
import {ClipCard} from '/ui-src/components/ClipCard';
import {usePlaylistDropTarget} from '/ui-src/lib/clipDrag';
import {api} from '/ui-src/lib/api';
const origin = ORIGIN;
api.originalFile = async()=>fetch(origin+'/file').then(r=>r.json());
api.addClipToPlaylist = async(id,slug)=>{await fetch(origin+'/internal?slug='+slug);return {ok:true};};
const clip={slug:'test-clip',name:'Match été #1.mp4',video_url:'/unused',duration:1};
function Probe(){const drop=usePlaylistDropTarget({id:'p',name:'Playlist',clip_slugs:[]} as any,()=>{});
return <><div style={{width:200}}><ClipCard clip={clip as any} draggable/></div>
<div {...drop.props} style={{position:'absolute',left:250,top:120,width:200,height:80}}>Playlist</div></>;}
createRoot(document.getElementById('root')!).render(<Probe/>);
'''.replace('ORIGIN', json.dumps(origin)))
        children, logs = [], []
        def launch(name, command):
            log = (folder/(name+'.log')).open('w'); logs.append(log)
            child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log)
            children.append(child)
            return child
        try:
            launch('vite', ['node', str(ROOT/'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', str(vite_port), '--strictPort'])
            def listening():
                try:
                    with socket.create_connection(('127.0.0.1', vite_port), timeout=.1): return True
                except OSError: return False
            wait_for(listening, 'Vite did not start')
            launch('receiver', [sys.executable, __file__, 'receiver', directory])
            launch('source', [sys.executable, __file__, 'source', directory, str(vite_port), str(api_port)])
            wait_for(lambda: (folder/'source-ready').exists() and (folder/'receiver-ready').exists(), 'Qt windows did not load')
            def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
            before = original.stat().st_mtime_ns, digest(original)
            def drag(x, y):
                subprocess.run(['xdotool', 'mousemove', '150', '130', 'sleep', '.3', 'mousedown', '1',
                                'mousemove', '190', '130', 'sleep', '.4', 'mousemove', str(x), str(y),
                                'sleep', '.5', 'mouseup', '1'], check=True, timeout=5)
            drag(700, 180)
            wait_for(lambda: (folder/'drop.json').exists(), 'External native file drop failed')
            result = json.loads((folder/'drop.json').read_text())
            assert result == {'path': str(original), 'clip': 'test-clip', 'action': 'CopyAction'}, result
            assert digest(folder/'received.mp4') == before[1]
            assert (original.stat().st_mtime_ns, digest(original)) == before
            time.sleep(.5)
            drag(430, 240)
            wait_for(lambda: (folder/'internal-drop').exists(), 'Native drop back onto playlist failed')
            print('PASS: actual ClipCard native external copy and internal playlist drop; original bytes and timestamp unchanged.')
        except Exception:
            for log in logs: log.flush()
            for log in folder.glob('*.log'):
                print(log.name, log.read_text()[-3000:], file=sys.stderr)
            raise
        finally:
            for child in children: child.terminate()
            for child in children:
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired: child.kill(); child.wait()
            for log in logs: log.close()


if __name__ == '__main__':
    if len(sys.argv) == 1: check()
    elif sys.argv[1] == 'source': source(Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    elif sys.argv[1] == 'receiver': receiver(Path(sys.argv[2]))
