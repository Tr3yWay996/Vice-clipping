import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from vice.native_drag import resolve_drag_file


class NativeFileResolutionTests(unittest.TestCase):
    def test_only_local_daemon_is_used_and_unicode_identifiers_are_encoded(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Été #1.mp4';path.write_bytes(b'original')
            data={'path':str(path),'filename':path.name,'uri':path.as_uri()}
            response=mock.MagicMock()
            response.__enter__.return_value.read.return_value=json.dumps(data).encode()
            with mock.patch('vice.native_drag.urlopen',return_value=response) as fetch:
                result=resolve_drag_file('http://127.0.0.1:8765/?native=1','été #1',True)
            self.assertEqual(result['uri'],path.as_uri())
            self.assertEqual(fetch.call_args.args[0],'http://127.0.0.1:8765/api/clips/%C3%A9t%C3%A9%20%231/file?prepared=1')
            for url in ['https://trycloudflare.com','http://192.168.1.1','file:///tmp/test']:
                with self.assertRaises(ValueError):resolve_drag_file(url,'clip')

    def test_missing_or_relative_indexed_file_is_rejected_without_modifying_source(self):
        response=mock.MagicMock()
        for value in ['relative.mp4','/does/not/exist.mp4']:
            response.__enter__.return_value.read.return_value=json.dumps({'path':value}).encode()
            with mock.patch('vice.native_drag.urlopen',return_value=response):
                with self.assertRaises(ValueError):resolve_drag_file('http://127.0.0.1:8765','clip')

    def test_native_mime_contains_the_actual_file_and_internal_playlist_identifier(self):
        try:
            from qtpy import QtCore
        except ImportError:
            self.skipTest('Qt bindings are not installed')
        from vice.native_drag import file_mime
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Été #1.mp4';path.write_bytes(b'original')
            before=path.stat().st_mtime_ns
            mime=file_mime({'path':str(path),'uri':path.as_uri(),'slug':'clip'})
            self.assertTrue(mime.hasUrls())
            self.assertEqual(mime.urls()[0].toLocalFile(),str(path))
            self.assertEqual(bytes(mime.data('application/x-vice-clip')),b'clip')
            self.assertEqual(mime.text(),path.as_uri())
            self.assertEqual(path.read_bytes(),b'original')
            self.assertEqual(path.stat().st_mtime_ns,before)
