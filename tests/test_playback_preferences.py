import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
try:
    import _sandbox  # noqa: F401
except ModuleNotFoundError:
    from tests import _sandbox  # noqa: F401
from vice import config
from vice.share import ShareServer


class PlaybackPreferencesTests(unittest.TestCase):
    def test_old_configs_default_to_playback_and_both_modes_survive_reloading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(config, 'CONFIG_PATH', root/'config.toml'), mock.patch.object(config, 'CONFIG_DIR', root):
                (root/'config.toml').write_text('[ui]\nhardware_video_decode = false\n')
                self.assertEqual(config.load().ui.arrow_key_behavior, 'playback')
                for mode in ['clips', 'playback']:
                    cfg = config.load()
                    cfg.ui.arrow_key_behavior = mode
                    config.save(cfg)
                    self.assertEqual(config.load().ui.arrow_key_behavior, mode)
                self.assertEqual(config.UIConfig(arrow_key_behavior='unknown').arrow_key_behavior, 'playback')


class PlaybackPreferenceApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_setting_changes_live_without_changing_recording_or_restarting_daemon(self):
        cfg = config.Config()
        server = ShareServer(cfg)
        original_recording = cfg.recording
        request = mock.Mock()
        request.json = mock.AsyncMock(return_value={'ui':{'arrow_key_behavior':'clips'}})
        with mock.patch.object(config, 'load', return_value=cfg), mock.patch.object(config, 'save') as save:
            response = json.loads((await server._api_set_config(request)).text)
        self.assertTrue(response['ok'])
        self.assertFalse(response['restart_required'])
        self.assertEqual(save.call_args.args[0].ui.arrow_key_behavior, 'clips')
        self.assertEqual(server.cfg.recording, original_recording)
        self.assertEqual(server.cfg.ui.arrow_key_behavior, 'clips')
        await server._jobs.stop()
