"""A blocked external write must not own the real kiosk event loop."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from .test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "no Tk display server is available")
class DeliveryGuiTests(unittest.TestCase):
    def test_routine_touch_budgets_without_wizard_pages(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("touch_budget_driver.py"))],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        report = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(report["callback_faults"], [])
        self.assertEqual(report["live_connections"], 0)
        self.assertEqual(len(report["paths"]), 65)
        self.assertTrue(report["large_roster_batch_verified"])
        self.assertTrue(all(p["taps"] <= p["limit"] for p in report["paths"]))

    def test_independent_group_touch_flow_and_resizing(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("group_ui_driver.py"))],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        report = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(report["callback_faults"], [])
        self.assertEqual(report["live_connections"], 0)
        self.assertEqual(report["incidents"], 2)

    def test_operator_touch_workflow_and_handover(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("operator_ui_driver.py"))],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        report = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(report["callback_faults"], [])
        self.assertEqual(report["incidents"], 2)

    def test_blocked_write_allows_touches_and_local_completion(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("delivery_ui_driver.py"))],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        reports = [line for line in result.stdout.splitlines() if line.startswith("{")]
        self.assertTrue(reports, result.stdout[-2000:])
        report = json.loads(reports[-1])
        self.assertEqual(report["callback_faults"], [])
        self.assertEqual(report["duplicate_records"], 0)
        self.assertEqual(report["heartbeat_count"], 100)
        self.assertLess(report["slow_storage_maximum_gap_ms"], 500)
        self.assertGreaterEqual(report["slow_storage_writes"], 4)
