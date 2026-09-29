"""Operator-facing failure reporting: specific, persistent, and truthful."""

import queue
import unittest
from types import SimpleNamespace

from floorterminal.app import FloorTerminalApp, describe_control
from floorterminal.storage.state import INITIAL_STATE, StateSaveError


class Logger:
    def __init__(self):
        self.events = []

    def log(self, event, level="INFO", **details):
        self.events.append((event, level, details))


class Root:
    def __init__(self):
        self.scheduled = []

    def after(self, delay, callback):
        self.scheduled.append((delay, callback))


class Canvas:
    scale_factor = 1.0

    def to_logical(self, x, y):
        return x, y


def app():
    instance = FloorTerminalApp.__new__(FloorTerminalApp)
    instance.state = {**INITIAL_STATE, "status": "REPAIRING", "issue_zones": []}
    instance.config = {"zones": ["Station 1"], "animation_interval_ms": 80}
    instance.logger = Logger()
    instance.root = Root()
    instance.canvas = Canvas()
    instance.events = queue.Queue()
    instance.hitboxes = {}
    instance.pressed = None
    instance.modal = None
    instance.busy = False
    instance.error_panel = None
    instance.render_blocked = False
    instance.ui_context = ""
    instance.toast_text, instance.toast_kind, instance.toast_until = "", "info", 0
    instance.provider = SimpleNamespace(limit=None, remaining=None)
    instance.renders = 0

    def render():
        instance.renders += 1

    instance.render = render
    return instance


def touch(instance, key):
    instance.hitboxes[key] = (0, 0, 10, 10)
    instance.pressed = key
    instance.on_release(SimpleNamespace(x=5, y=5))


class ErrorPanelTests(unittest.TestCase):
    def test_a_failed_touch_names_the_operation_instead_of_a_generic_render_error(self):
        instance = app()

        def failing_save():
            raise StateSaveError(
                "Line state could not be saved (Persisted state contains unsupported "
                "fields: work_label); the last saved state was restored"
            )

        instance.save_state = failing_save
        instance.open_failure_selection = lambda station: None
        touch(instance, "zone_0")
        panel = instance.error_panel
        self.assertEqual(panel["title"], "Line state could not be saved")
        self.assertEqual(panel["operation"], "Selecting a station")
        self.assertIn("work_label", panel["message"])
        self.assertTrue(panel["state_failure"])
        self.assertTrue(
            any(event == "ui_action_failed" for event, _level, _d in instance.logger.events)
        )

    def test_the_panel_survives_every_redraw_until_it_is_acknowledged(self):
        instance = app()
        instance.show_error_panel("Completing repair", RuntimeError("Connector refused"))
        for _frame in range(5):
            instance.animate()
        self.assertEqual(instance.renders, 5)
        self.assertIsNotNone(instance.error_panel)
        # Touches elsewhere cannot act underneath an unread error.
        instance.primary_action = lambda: self.fail("acted beneath the error panel")
        touch(instance, "primary")
        self.assertIsNotNone(instance.error_panel)
        touch(instance, "error_dismiss")
        self.assertIsNone(instance.error_panel)

    def test_operator_failures_open_the_panel_and_background_failures_do_not(self):
        instance = app()
        instance.events.put(
            (False, RuntimeError("Response record update rejected"), None, "Completing repair", False)
        )
        instance.poll_events()
        self.assertEqual(instance.error_panel["title"], "Completing repair did not finish")
        instance.dismiss_error_panel()
        instance.events.put(
            (False, RuntimeError("Network unavailable"), None, "Synchronizing queued updates…", True)
        )
        instance.poll_events()
        self.assertIsNone(instance.error_panel)
        self.assertIn("Network unavailable", instance.toast_text)

    def test_a_tk_callback_error_is_explained_and_rendering_continues(self):
        instance = app()
        instance.ui_context = "Loading Engineering team"
        instance.callback_error(ValueError, ValueError("bad roster entry"), None)
        self.assertEqual(instance.error_panel["title"], "Unexpected interface error")
        self.assertEqual(instance.error_panel["operation"], "Loading Engineering team")
        self.assertFalse(instance.render_blocked)
        self.assertEqual(instance.renders, 1)

    def test_a_frame_that_cannot_render_is_held_on_a_static_screen(self):
        instance = app()

        def broken_render():
            raise RuntimeError("drawing failed")

        drawn = []
        instance.render = broken_render
        instance.draw_static_error = lambda exc: drawn.append(str(exc))
        instance.callback_error(RuntimeError, RuntimeError("first failure"), None)
        self.assertTrue(instance.render_blocked)
        self.assertEqual(drawn, ["drawing failed"])
        # The animation loop keeps running but no longer paints over it.
        instance.animate()
        self.assertEqual(instance.root.scheduled[-1][0], 80)
        # Any touch acknowledges the static screen and tries again.
        instance.on_release(SimpleNamespace(x=1, y=1))
        self.assertIsNone(instance.error_panel)

    def test_controls_have_operator_readable_descriptions(self):
        self.assertEqual(describe_control("start_engineers"), "Confirming the Engineering crew")
        self.assertEqual(describe_control("member_2"), "Selecting an engineer")
        self.assertEqual(describe_control("failure_3"), "Choosing a failure type")
        self.assertIn("mystery", describe_control("mystery"))



class ConfirmationTimestampTests(unittest.TestCase):
    def test_opening_confirmation_does_not_record_a_release_time(self):
        instance = app()
        instance.confirm_done()
        self.assertNotIn("requested_at", instance.modal)
        self.assertIsNone(instance.state["completion_confirmed_at"])

    def test_affirmative_touch_time_is_kept_even_if_worker_runs_later(self):
        from unittest.mock import patch

        instance = app()
        instance.confirm_done()
        queued, confirmed = [], []
        instance.perform = lambda _operation, function, **_kwargs: queued.append(function)
        instance.finish_work = lambda stamp: confirmed.append(stamp)
        with patch("floorterminal.app.time.time", return_value=200.0):
            touch(instance, "confirm")
        with patch("floorterminal.app.time.time", return_value=900.0):
            queued[0]()
        self.assertEqual(confirmed, [200.0])

if __name__ == "__main__":
    unittest.main()
