import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import personal_launcher


class UniversalLauncherTests(unittest.TestCase):
    def test_panel_available_without_an_adapter(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual([service[0] for service in personal_launcher.configured_services({})], ['panel'])

    def test_adapter_requires_an_absolute_configured_path(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(personal_launcher.LaunchError):
                personal_launcher.configured_services({'adapter_dir': 'relative/path'})

    def test_local_service_keys_are_not_forwarded_to_redirects(self):
        handler = personal_launcher.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, 'Found', {}, 'https://example.invalid/'))


if __name__ == '__main__':
    unittest.main()
