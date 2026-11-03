"""Touch, worker ownership and single-timer regression checks."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from .test_error_reporting import app


class FeedbackTests(unittest.TestCase):
    def test_worker_start_failure_releases_busy_state_and_reports_the_operation(self):
        instance = app()
        action, failed = Mock(), Mock()
        with patch(
            "floorterminal.app.threading.Thread.start",
            side_effect=RuntimeError("No worker available"),
        ):
            instance.perform("Saving selection", action, on_error=failed)
        instance.poll_events()
        self.assertFalse(instance.busy)
        action.assert_not_called()
        failed.assert_called_once()
        self.assertEqual(instance.error_panel["operation"], "Saving selection")

    def test_identity_result_cannot_unlock_an_in_flight_operation(self):
        instance = app()
        instance.busy = True
        instance.busy_message = "Recording downtime"
        instance.events.put((True, "Account", Mock()))
        instance.poll_events()
        self.assertTrue(instance.busy)
        self.assertEqual(instance.busy_message, "Recording downtime")

    def test_operation_acknowledged_before_thread_starts_and_duplicate_is_blocked(self):
        instance = app()
        instance.canvas.configure = Mock()
        with patch("floorterminal.app.threading.Thread") as thread:
            self.assertTrue(instance.perform("Recording downtime", lambda: "saved"))
            self.assertTrue(instance.busy)
            self.assertEqual(instance.busy_message, "Recording downtime")
            self.assertGreater(instance.busy_started, 0)
            instance.canvas.configure.assert_called_with(cursor="watch")
            self.assertFalse(instance.perform("Duplicate", lambda: "must not run"))
            thread.assert_called_once()
        instance.events.put((True, "Saved locally", None, "Recording downtime", False))
        instance.poll_events()
        self.assertFalse(instance.busy)
        self.assertEqual(instance.busy_message, "")
        instance.canvas.configure.assert_called_with(cursor="")

    def test_fast_touch_is_acknowledged_even_after_release_clears_pressed(self):
        instance = app()
        instance.hitboxes = {"about": (0, 0, 100, 100)}
        instance.request_render = Mock()
        event = SimpleNamespace(x=50, y=50)
        instance.on_press(event)
        self.assertEqual(instance.pressed, "about")
        instance.on_release(event)
        self.assertIsNone(instance.pressed)
        self.assertEqual(instance.touch_feedback[:2], (50, 50))
        self.assertEqual(instance.modal, {"kind": "about"})
        self.assertEqual(instance.request_render.call_count, 2)

    def test_resize_and_touch_burst_schedule_one_idle_repaint(self):
        instance = app()
        instance.root.after_idle = Mock(return_value="repaint")
        for _ in range(1000):
            instance.request_render()
        instance.root.after_idle.assert_called_once()
        self.assertEqual(instance._render_after, "repaint")
        instance.root.after_idle.call_args.args[0]()
        self.assertIsNone(instance._render_after)

    def test_resize_cancels_a_press_before_controls_move(self):
        instance = app()
        instance.pressed = "primary"
        instance.touch_feedback = (50, 50, 0)
        instance.canvas.set_viewport = Mock()
        instance.request_render = Mock()
        instance.on_canvas_resize(SimpleNamespace(width=480, height=800))
        self.assertIsNone(instance.pressed)
        self.assertIsNone(instance.touch_feedback)
        instance.canvas.set_viewport.assert_called_once_with(480, 800)
        instance.request_render.assert_called_once()

    def test_restarting_animation_cancels_old_callback_instead_of_multiplying_loops(
        self,
    ):
        instance = app()
        instance.root.after = Mock(side_effect=("frame1", "frame2"))
        instance.root.after_cancel = Mock()
        instance.animate()
        instance.animate()
        instance.root.after_cancel.assert_called_once_with("frame1")
        self.assertEqual(instance._animation_after, "frame2")

    def test_hidden_window_skips_render_and_slows_timer(self):
        instance = app()
        instance.root.winfo_viewable = lambda: False
        instance.animate()
        self.assertEqual(instance.renders, 0)
        self.assertEqual(instance.root.scheduled[-1][0], 250)

    def test_slow_frame_does_not_schedule_catch_up_burst(self):
        instance = app()
        with patch("floorterminal.ui.view.time.monotonic", side_effect=(100, 100.2)):
            instance.animate()
        self.assertEqual(instance.root.scheduled[-1][0], 50)

    def test_closing_does_not_schedule_more_gui_work(self):
        instance = app()
        instance._closing = True
        instance.animate()
        instance.request_render()
        self.assertFalse(instance.root.scheduled)

    def test_storage_walk_runs_in_worker_and_does_not_own_the_operation_lock(self):
        instance = app()
        instance.logger.prune = Mock()
        instance.logger.storage_capacity = Mock(
            return_value={"enough": False, "free_mb": 10, "required_mb": 100}
        )
        instance.busy = True
        with patch("floorterminal.app.threading.Thread") as thread:
            instance.check_storage_capacity()
            instance.logger.prune.assert_not_called()
            thread.call_args.kwargs["target"]()
        instance.poll_events()
        self.assertTrue(instance.busy)
        self.assertTrue(instance.storage_warning_active)
        self.assertFalse(instance._storage_check_running)
        self.assertIn("LOW STORAGE", instance.toast_text)

    def test_retry_deadline_cache_remains_bounded_without_losing_recent_deadlines(self):
        instance = app()
        instance.retry_deadlines = {}
        with patch("floorterminal.controller.workflow.time.time", return_value=1000):
            for index in range(10000):
                instance.deadline_due(f"completed-{index}", 1000, 60)
        self.assertEqual(len(instance.retry_deadlines), 512)
        self.assertIn("completed-9999", instance.retry_deadlines)
        self.assertNotIn("completed-0", instance.retry_deadlines)

    def test_failed_health_check_is_visible_without_repeated_notifications(self):
        instance = app()
        instance.notify = Mock()
        report = {"check_error": "Storage checks unavailable"}
        instance._storage_capacity_checked(report)
        instance._storage_capacity_checked(report)
        instance.notify.assert_called_once()
        self.assertEqual(instance.health_snapshot, report)
        self.assertFalse(instance._storage_check_running)
