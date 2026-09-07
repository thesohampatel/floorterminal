import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tests" / "unit" / "ui_smoke_driver.py"


def display_available():
    """Tk needs a display server; report whether one can actually be opened."""
    probe = subprocess.run(
        [sys.executable, "-c", "import tkinter; tkinter.Tk().destroy()"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return probe.returncode == 0


HAS_DISPLAY = display_available()


@unittest.skipUnless(HAS_DISPLAY, "no Tk display server is available")
class TouchscreenSmokeTests(unittest.TestCase):
    """Render every screen and press every control, in a real Tk session.

    The controller draws in immediate mode and rebuilds its touch targets on every
    frame, so a fault in one workflow state is invisible from any other. This
    sweep is the regression barrier for that whole class of defect, including the
    Settings reconciliation path that writes configuration and reapplies it to
    live operator state.
    """

    @classmethod
    def setUpClass(cls):
        completed = subprocess.run(
            [sys.executable, str(DRIVER)],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
            env={**os.environ, "PYTHONWARNINGS": "ignore"},
        )
        cls.completed = completed
        payload = ""
        for line in completed.stdout.splitlines():
            if line.startswith("{"):
                payload = line
        cls.result = json.loads(payload) if payload else {}

    def test_the_driver_reported_a_result(self):
        self.assertTrue(
            self.result,
            f"driver produced no report\nstdout:\n{self.completed.stdout}\n"
            f"stderr:\n{self.completed.stderr}",
        )

    def test_every_screen_and_control_is_fault_free(self):
        faults = self.result.get("faults", [])
        detail = "\n\n".join(f"{item['where']}\n{item['error']}" for item in faults)
        self.assertEqual(faults, [], f"{len(faults)} UI faults:\n{detail}")

    def test_the_sweep_covered_the_expected_breadth(self):
        # Four workflow states across thirteen dialogs, and every touch target in
        # each. A sharp drop means a dialog stopped registering its controls.
        self.assertGreaterEqual(self.result.get("rendered", 0), 52)
        self.assertGreaterEqual(self.result.get("pressed", 0), 900)

    def test_no_text_collides_or_leaves_the_canvas_at_any_panel_size(self):
        """Layout is checked at 7-inch, 10.1-inch and desktop independently.

        The design is one logical canvas scaled uniformly, but font sizes round
        per scale, so a label can outgrow its container at one size only.
        """
        collisions = self.result.get("collisions", [])
        detail = "\n".join(
            f"{item['where']}: {item['kind']} — {item['detail']} at {item['box']}"
            for item in collisions[:25]
        )
        self.assertEqual(collisions, [], f"{len(collisions)} layout collisions:\n{detail}")

    def test_saving_settings_with_failure_selections_succeeds(self):
        """Regression: reconciling saved failure selections must not raise."""
        self.assertTrue(
            self.result.get("settings_saved"),
            "the Settings window could not save with failure selections present",
        )

    def test_every_settings_tab_is_reachable_and_within_the_screen(self):
        self.assertEqual(
            self.result.get("settings_tabs_checked"),
            6,
            "one or more Settings tabs was hidden, unreachable, or outside the screen",
        )

    def test_password_change_masks_input_and_returns_to_settings(self):
        self.assertTrue(self.result.get("password_changed"))


if __name__ == "__main__":
    unittest.main()
