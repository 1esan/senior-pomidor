import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import adapter_config


class AdapterConfigurationTests(unittest.TestCase):
    def test_uses_explicit_local_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            adapter = root / 'adapter'
            (adapter / '.state').mkdir(parents=True)
            (adapter / '.state' / 'adapter-key').write_text('test-key')
            (root / 'personal_launcher.json').write_text(json.dumps({'adapter_dir': str(adapter)}))
            with patch.object(adapter_config, 'BASE', root), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(adapter_config.adapter_dir(), adapter)
                self.assertEqual(adapter_config.adapter_key(), 'test-key')

    def test_missing_configuration_is_explicit_and_never_uses_another_account(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(adapter_config, 'BASE', Path(folder)), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(adapter_config.AdapterConfigurationError):
                adapter_config.adapter_key()

    def test_rejects_relative_adapter_path(self):
        with patch.dict(os.environ, {'SENIOR_POMIDOR_ADAPTER_DIR': 'relative/path'}):
            with self.assertRaises(adapter_config.AdapterConfigurationError):
                adapter_config.adapter_dir()


if __name__ == '__main__':
    unittest.main()
