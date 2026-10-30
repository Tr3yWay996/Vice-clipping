import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is not installed')
class LocalizationEnforcementTests(unittest.TestCase):
    def check(self, en, fr, source=''):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);locales=folder/'locales';ui=folder/'ui'
            locales.mkdir();ui.mkdir()
            (locales/'en.json').write_text(json.dumps(en))
            (locales/'fr.json').write_text(json.dumps(fr))
            (ui/'Screen.tsx').write_text(source)
            return subprocess.run(['node',str(ROOT/'tools/check-locales.mjs'),'--locales-dir',str(locales),'--ui-dir',str(ui)],capture_output=True,text=True,timeout=15)

    def test_new_missing_keys_and_changed_placeholders_fail(self):
        self.assertNotEqual(self.check({'hello':'Hello'},{}).returncode,0)
        result=self.check({'hello':'Hello {name}'},{'hello':'Bonjour {user}'})
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Placeholder mismatch',result.stdout)

    def test_unknown_keys_and_hardcoded_ui_prose_fail(self):
        for source in ["t('missing.key')", '<p>Untranslated interface words</p>', '<p>\nUntranslated interface words spread\nover several lines.\n</p>']:
            self.assertNotEqual(self.check({'hello':'Hello'},{'hello':'Bonjour'},source).returncode,0)

    def test_valid_translations_interpolation_and_plurals_pass(self):
        result=self.check({'hello':'Hello {name}','jobs':{'one':'{count} job','other':'{count} jobs'}},
                          {'hello':'Bonjour {name}','jobs':{'one':'{count} tâche','other':'{count} tâches'}},"t('hello', {name: value})")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_new_workflow_and_keyframe_keys_exist_in_every_shipped_locale(self):
        en=json.loads((ROOT/'ui-src/locales/en.json').read_text())
        for file in (ROOT/'ui-src/locales').glob('*.json'):
            data=json.loads(file.read_text())
            for key in ['showKeyframes','snapKeyframes','keyframeInformation','keyframeHelp','timelineHint']:
                self.assertIn(key,data['trim'],f'{file.name}: trim.{key}')
            self.assertEqual(set(data['queue']),set(en['queue']),file.name)
