import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from .test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "no Tk display server is available")
class DailyRosterUITests(unittest.TestCase):
    def test_settings_refresh_is_bounded_nonblocking_and_picker_stays_stable(self):
        run = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("roster_ui_driver.py"))],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
            env={**os.environ, "FLOORTERMINAL_DISABLE_NETWORK": "1"},
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        report = json.loads(run.stdout.splitlines()[-1])
        self.assertEqual(report["faults"], [])
        self.assertEqual(report["live_connections"], 0)
        self.assertEqual(report["requests"], 2)
        self.assertEqual(report["cached_opens"], 30)
        self.assertEqual(report["viewports"], 3)
        self.assertTrue(report["config_connector_unchanged"])
        self.assertTrue(report["stable_open_picker"])
        self.assertLess(report["max_heartbeat_ms"], 500)
