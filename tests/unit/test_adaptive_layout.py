"""Pure geometry and real-Tk kiosk layout regression barriers."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from floorterminal.ui.layout import Viewport, split_row, station_capacity

from .test_ui_smoke import HAS_DISPLAY


class LayoutPolicyTests(unittest.TestCase):
    def test_content_follows_available_viewport_not_a_fixed_aspect_ratio(self):
        for width in range(320, 3201, 113):
            for height in range(400, 2201, 97):
                view = Viewport.from_pixels(width, height)
                self.assertAlmostEqual(view.width * view.scale, width)
                self.assertAlmostEqual(view.height * view.scale, height)
                self.assertGreaterEqual(view.scale, 1)
                self.assertGreaterEqual(view.width, 320)
                self.assertGreaterEqual(view.height, 400)

    def test_portrait_and_short_viewports_reflow(self):
        self.assertTrue(Viewport.from_pixels(480, 800).stacked)
        self.assertTrue(Viewport.from_pixels(1080, 1920).stacked)
        self.assertTrue(Viewport.from_pixels(640, 400).paged)
        self.assertFalse(Viewport.from_pixels(800, 480).paged)

    def test_undersized_screen_is_explicit_not_silently_shrunk(self):
        self.assertFalse(Viewport.from_pixels(280, 240).usable)
        self.assertTrue(Viewport.from_pixels(320, 400).usable)

    def test_more_available_width_adds_station_capacity_not_smaller_targets(self):
        capacities = [station_capacity(w) for w in range(296, 1441)]
        self.assertEqual(capacities, sorted(capacities))
        for width in range(296, 1441):
            count = station_capacity(width)
            boxes = split_row((62, 0, width - 62, 90), count)
            self.assertTrue(all(box[2] - box[0] >= 44 for box in boxes))


@unittest.skipUnless(HAS_DISPLAY, "no Tk display server is available")
class AdaptiveKioskTests(unittest.TestCase):
    def test_targets_navigation_and_unsaved_edits_across_viewports(self):
        driver = Path(__file__).with_name("adaptive_ui_driver.py")
        result = subprocess.run(
            [sys.executable, str(driver)],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        reports = [line for line in result.stdout.splitlines() if line.startswith("{")]
        self.assertTrue(reports, result.stderr[-4000:])
        report = json.loads(reports[-1])
        self.assertEqual(report["faults"], [], "\n".join(report["faults"][:30]))
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertGreaterEqual(report["snapshots"], 3744)
