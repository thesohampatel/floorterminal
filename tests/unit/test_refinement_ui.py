"""Run the v1.2.1 touch regression on a real Tk display when available."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from .test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "no Tk display server is available")
class RefinementUITests(unittest.TestCase):
    def test_touch_keyboard_clock_failure_grid_and_information(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("refinement_ui_driver.py"))],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        report = json.loads(
            next(line for line in result.stdout.splitlines() if line.startswith("{"))
        )
        self.assertEqual(report["sizes"], 4)
        self.assertEqual(report["faults"], [])
        self.assertEqual(report["network_calls"], 0)
        self.assertTrue(report["support_settings_saved"])
