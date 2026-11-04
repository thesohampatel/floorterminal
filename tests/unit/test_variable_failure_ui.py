import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from .test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "no Tk display server is available")
class VariableFailureUITests(unittest.TestCase):
    def test_real_touch_pages_and_bounded_editor(self):
        run = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("variable_failure_ui_driver.py")),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={**os.environ, "FLOORTERMINAL_DISABLE_NETWORK": "1"},
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        report = json.loads(
            next(line for line in run.stdout.splitlines() if line.startswith("{"))
        )
        self.assertEqual(report["cases"], 30)
        self.assertTrue(report["editor_preserved"])
        self.assertTrue(report["active_edit_blocked"])
        self.assertEqual(report["faults"], [])
