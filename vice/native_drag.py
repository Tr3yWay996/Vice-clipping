"""Small Qt native file-drag bridge. Paths come only from the local clip index."""
from __future__ import annotations
import json
import re
import threading
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import urlopen


def resolve_drag_file(server_url: str, slug: str, prepared=False) -> dict:
    parsed = urlsplit(server_url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('A local Vice connection is required')
    origin = f'{parsed.scheme}://{parsed.netloc}'
    endpoint = f'{origin}/api/clips/{quote(str(slug), safe="")}/file'
    if prepared:
        endpoint += '?prepared=1'
    with urlopen(endpoint, timeout=3) as response:
        data = json.load(response)
    path = Path(data['path'])
    if not path.is_absolute() or not path.is_file():
        raise ValueError('The indexed video is unavailable')
    return {**data, 'path': str(path), 'uri': path.as_uri(), 'slug': str(slug)}


def file_mime(data):
    """QUrl handles spaces, Unicode and URI encoding; always copy the source."""
    from qtpy import QtCore
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(data['path'])])
    mime.setText(data['uri'])
    mime.setData('application/x-vice-clip', data['slug'].encode('utf-8'))
    return mime


def drag_file(data: dict) -> dict:
    try:
        from qtpy import QtCore, QtGui, QtWidgets
    except ImportError:
        return {'ok': False, 'reason': 'unsupported'}
    app = QtWidgets.QApplication.instance()
    if app is None:
        return {'ok': False, 'reason': 'unsupported'}
    completed = threading.Event()
    result = {'ok': False, 'reason': 'cancelled'}

    class Drag(QtCore.QObject):
        requested = QtCore.Signal()
        escaped = False

        def eventFilter(self, watched, event):
            if event.type() == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Escape:
                self.escaped = True
            if event.type() == QtCore.QEvent.Type.Drop and event.mimeData().hasFormat('application/x-vice-clip'):
                # Chromium sanitizes native file drops to Files, discarding
                # custom MIME identifiers. Route our own internal drops back
                # through the shared playlist hook before Chromium handles the
                # file (or navigates to it). External applications still receive
                # the ordinary native MIME data without interception.
                view = watched if isinstance(watched, QtWidgets.QWidget) else None
                while view is not None and not callable(getattr(view, 'page', None)):
                    view = view.parentWidget()
                if view is not None:
                    position = view.mapFromGlobal(QtGui.QCursor.pos())
                    zoom = view.zoomFactor() or 1
                    detail = json.dumps({'slug': data['slug']})
                    view.page().runJavaScript(
                        f'document.elementFromPoint({position.x() / zoom}, {position.y() / zoom})'
                        f'?.dispatchEvent(new CustomEvent("vice-native-clip-drop", {{bubbles:true, detail:{detail}}}));')
                    event.setDropAction(QtCore.Qt.DropAction.CopyAction)
                    event.accept()
                    return True
            return False

        @QtCore.Slot()
        def run(self):
            try:
                parent = app.activeWindow()
                if parent is None:
                    result['reason'] = 'unsupported'
                    return
                drag = QtGui.QDrag(parent)
                drag.setMimeData(file_mime(data))
                # Preserve Vice's compact rounded thumbnail/name preview in the
                # native compositor drag, rather than a screenshot of the card.
                pixmap = QtGui.QPixmap(280, 44)
                pixmap.fill(QtCore.Qt.GlobalColor.transparent)
                painter = QtGui.QPainter(pixmap)
                painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                def color(value, fallback):
                    channels = re.findall(r'[\d.]+', str(value))
                    if str(value).startswith('rgb') and len(channels) >= 3:
                        return QtGui.QColor(*[max(0, min(255, int(float(n)))) for n in channels[:3]])
                    parsed = QtGui.QColor(str(value))
                    return parsed if parsed.isValid() else QtGui.QColor(fallback)
                appearance = data.get('appearance', {})
                painter.setBrush(color(appearance.get('background'), '#303238'))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawRoundedRect(0, 0, 280, 44, 22, 22)
                thumb = QtGui.QPixmap(data.get('thumbnail', ''))
                if not thumb.isNull():
                    painter.drawPixmap(10, 9, 44, 26, thumb)
                painter.setPen(color(appearance.get('foreground'), '#eeeeee'))
                label = painter.fontMetrics().elidedText(data['filename'], QtCore.Qt.TextElideMode.ElideRight, 205)
                painter.drawText(64, 27, label)
                painter.end()
                drag.setPixmap(pixmap)
                drag.setHotSpot(QtCore.QPoint(24, 20))
                app.installEventFilter(self)
                action = drag.exec(QtCore.Qt.DropAction.CopyAction)
                result.update(ok=action == QtCore.Qt.DropAction.CopyAction,
                              reason=None if action == QtCore.Qt.DropAction.CopyAction else ('cancelled' if self.escaped else 'rejected'))
            except Exception:
                result['reason'] = 'unsupported'
            finally:
                app.removeEventFilter(self)
                completed.set()

    dispatcher = Drag()
    dispatcher.moveToThread(app.thread())
    dispatcher.requested.connect(dispatcher.run, QtCore.Qt.ConnectionType.QueuedConnection)
    dispatcher.requested.emit()
    completed.wait()
    dispatcher.deleteLater()
    return result
