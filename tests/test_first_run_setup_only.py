import json
import errno
import os
from pathlib import Path
import runpy
import socket
import io
from contextlib import redirect_stderr
import tempfile
import unittest
from unittest.mock import patch, Mock, MagicMock

import first_run
from first_run import blocks_setup_action, initialize_json_file, initialize_profile


class FirstRunSetupTests(unittest.TestCase):
    def test_creates_blank_private_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            template = root / "template.json"
            profile = root / "giga_profile.json"
            template.write_text('{"profile_confirmed": false, "name": ""}', encoding="utf-8")

            self.assertTrue(initialize_profile(profile, template))
            self.assertEqual(json.loads(profile.read_text(encoding="utf-8")), {"profile_confirmed": False, "name": ""})
            self.assertEqual(os.stat(profile).st_mode & 0o777, 0o600)

    def test_never_overwrites_existing_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            template = root / "template.json"
            profile = root / "giga_profile.json"
            template.write_text('{"name": ""}', encoding="utf-8")
            profile.write_text('{"name": "existing"}', encoding="utf-8")

            self.assertFalse(initialize_profile(profile, template))
            self.assertEqual(profile.read_text(encoding="utf-8"), '{"name": "existing"}')

    def test_creates_generic_settings_and_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            template = root / "settings.example.json"
            settings = root / "settings.json"
            template.write_text("{}\n", encoding="utf-8")

            self.assertTrue(initialize_json_file(settings, template))
            self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), {})
            settings.write_text('{"custom": true}', encoding="utf-8")
            self.assertFalse(initialize_json_file(settings, template))
            self.assertEqual(settings.read_text(encoding="utf-8"), '{"custom": true}')

    def test_first_run_denies_service_and_operation_mutations(self):
        for path in ("/api/connect/hh", "/api/reports/dashboard/refresh", "/api/operations/apply/start"):
            with self.subTest(path=path):
                self.assertTrue(blocks_setup_action("POST", path))
        self.assertFalse(blocks_setup_action("POST", "/api/profile"))
        self.assertFalse(blocks_setup_action("POST", "/api/resume/extract"))
        self.assertFalse(blocks_setup_action("GET", "/api/operations/apply/start"))
        self.assertFalse(blocks_setup_action("POST", "/api/operations/apply/start", setup_only=False))

    def test_panel_port_probe_does_not_connect_to_occupant(self):
        probe = MagicMock()
        probe.__enter__.return_value = probe
        probe.bind.side_effect = OSError(errno.EADDRINUSE, "occupied")
        with patch.object(first_run.socket, "socket", return_value=probe):
            self.assertFalse(first_run.panel_port_available(8768))
        probe.bind.assert_called_once_with(("127.0.0.1", 8768))
        probe.connect.assert_not_called()

    def test_first_run_exits_before_setup_when_panel_port_is_busy(self):
        error = io.StringIO()
        with patch.object(first_run, "panel_port_available", return_value=False), \
             patch.object(first_run, "prepare_environment", side_effect=AssertionError("must not install")), \
             patch.object(first_run, "initialize_profile", side_effect=AssertionError("must not create profile")), \
             redirect_stderr(error):
            result = first_run.main(["--skip-install"])
        self.assertEqual(result, 1)
        self.assertIn("Порт панели 8768 уже занят", error.getvalue())

    def test_compatibility_launcher_exits_before_profile_when_port_is_busy(self):
        error = io.StringIO()
        with patch.object(first_run, "panel_port_available", return_value=False), \
             patch.object(first_run, "initialize_profile", side_effect=AssertionError("must not create profile")), \
             redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
            runpy.run_path(str(Path(first_run.__file__).with_name("giga-setup.py")), run_name="__main__")
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("Порт панели 8768 уже занят", error.getvalue())


if __name__ == "__main__":
    unittest.main()
