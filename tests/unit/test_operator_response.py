"""Operator-led stops use the same durable incident, including offline handover."""

from types import SimpleNamespace
from unittest import mock

from floorterminal.storage.state import (
    StateIntegrityError,
    StateSaveError,
    StateStore,
    validate_state,
)

from .test_completion_workflow import MEMBERS, WorkflowHarness
from .test_delivery_journal import DurableDeliveryHarness


class OperatorWorkflowTests(WorkflowHarness):
    def begin(self, name="Operator A"):
        app = self.app(common_activity_chat_name="Activity")
        app.state["issue_zones"] = ["Station 1", "Station 3"]
        app.report_downtime(operator_name=name)
        return app

    def test_self_fix_is_in_progress_without_engineering_assignment_or_call(self):
        app = self.begin()
        self.assertEqual(app.state["status"], "REPAIRING")
        self.assertEqual(app.state["started_at"], app.state["repair_at"])
        self.assertTrue(app.operator_resolving())
        self.assertEqual(self.provider.calls_to("assign"), [])
        self.assertNotIn(
            "Engineering", [c[0] for c in self.provider.calls_to("message")]
        )
        self.assertEqual(self.provider.calls_to("status")[-1][1], "IN_PROGRESS")

    def test_self_fix_completes_and_clears_state_without_a_crew(self):
        app = self.begin()
        original = app.state["started_at"]
        result = app.finish_work(confirmed_at=original + 42)
        self.assertIn("by operator", result)
        self.assertEqual(StateStore(self.path).data["status"], "RUNNING")
        self.assertIsNone(StateStore(self.path).data["operator_response"])
        comment = self.provider.calls_to("comment")[-1][1]
        self.assertIn("Operator A", comment)
        self.assertIn("Operator self-fix", comment)
        self.assertNotIn("Participation history", comment)
        self.assertEqual(
            app.logger.named("downtime_classified")[-1]["total_seconds"], 42
        )
        self.assertEqual(self.provider.calls_to("status")[-1][1], "DONE")
        self.assertEqual(self.provider.calls_to("asset")[-1][0], "ONLINE")

    def test_self_fix_may_be_longer_than_the_micro_stop_threshold(self):
        app = self.begin("")
        app.finish_work(confirmed_at=app.state["started_at"] + 600)
        event = app.logger.named("downtime_classified")[-1]
        self.assertEqual(event["response_category"], "operator_self_fix")
        self.assertEqual(event["classification"], "DOWNTIME EVENT")
        self.assertIn("Name not recorded", self.provider.calls_to("comment")[-1][1])

    def test_handover_reuses_record_and_original_time_through_restart(self):
        app = self.begin()
        record, started = app.state["response_record_id"], app.state["started_at"]
        app.request_engineering_handover()
        self.assertEqual(app.state["status"], "DOWN")
        app = self.app()
        self.assertTrue(app.operator_resolving())
        app.start_repair("team-1", MEMBERS)
        self.assertFalse(app.operator_resolving())
        self.assertEqual(app.state["response_record_id"], record)
        self.assertEqual(app.state["started_at"], started)
        app.finish_work(confirmed_at=started + 180)
        self.assertEqual(len(self.provider.calls_to("create")), 1)
        comment = self.provider.calls_to("comment")[-1][1]
        self.assertIn("Operator then Engineering", comment)
        self.assertIn("Alex Engineer", comment)
        self.assertIn("Operator A", comment)

    def test_repeated_help_request_does_not_send_duplicate_messages(self):
        app = self.begin()
        app.request_engineering_handover()
        count = len(self.provider.calls)
        app.request_engineering_handover()
        self.assertEqual(len(self.provider.calls), count)

    def test_escalation_counts_from_help_request_not_self_fix_start(self):
        app = self.begin()
        app.root = SimpleNamespace(after=mock.Mock())
        app.perform = mock.Mock()
        app.deadline_due = mock.Mock(return_value=False)
        app.escalation_tick()
        app.deadline_due.assert_not_called()
        app.request_engineering_handover()
        requested = app.state["operator_response"]["requested_at"]
        app.escalation_tick()
        app.deadline_due.assert_called_once_with("downtime-escalation", requested, 900)
        app.perform.assert_not_called()

    def test_operator_can_finish_before_requested_engineering_arrives(self):
        app = self.begin()
        app.request_engineering_handover()
        app.finish_work()
        messages = [
            text
            for target, text in self.provider.calls_to("message")
            if target == "Engineering"
        ]
        self.assertIn("no longer needed", messages[-1])
        self.assertIn("no Engineering repair", messages[-1])

    def test_engineer_can_arrive_without_a_prior_help_request(self):
        app = self.begin()
        app.change_status("IN_PROGRESS", "REPAIRING")
        self.assertFalse(app.operator_resolving())
        self.assertIsNotNone(app.state["operator_response"]["handed_over_at"])
        self.assertEqual(len(self.provider.calls_to("create")), 1)

    def test_visible_downtime_timer_continues_across_handover(self):
        app = self.begin()
        app.start_repair("team-1", MEMBERS)
        app.state.update(started_at=100, repair_at=200)
        with mock.patch("floorterminal.app.time.time", return_value=300):
            self.assertEqual(app.elapsed_seconds(), 200)

    def test_station_and_active_incident_guards(self):
        app = self.app()
        with self.assertRaisesRegex(RuntimeError, "Select"):
            app.report_downtime(operator_name="")
        app = self.begin()
        for name in (None, "Someone"):
            with self.assertRaisesRegex(RuntimeError, "already active"):
                app.report_downtime(operator_name=name)
        self.assertEqual(len(self.provider.calls_to("create")), 1)

    def test_corrupt_operator_metadata_is_rejected(self):
        from copy import deepcopy

        app = self.begin()
        for field, value in (
            ("name", 10),
            ("name", "x\n"),
            ("name", "x" * 121),
            ("started_at", float("nan")),
            ("requested_at", True),
            ("handed_over_at", -1),
            ("started_at", 1),
            ("extra", "x"),
        ):
            with self.subTest(field=field, value=value):
                data = deepcopy(app.state)
                data["operator_response"][field] = value
                with self.assertRaises(StateIntegrityError):
                    validate_state(data)


class OperatorDurabilityTests(DurableDeliveryHarness):
    def begin(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime, "Operator A")
        return app

    def test_offline_start_handover_release_restart_and_delivery(self):
        app = self.begin()
        self.action(app, app.request_engineering_handover)
        app = self.local_app()
        self.action(app, app.start_repair, "t1", MEMBERS)
        self.action(app, app.finish_work)
        self.assertEqual(self.transport.requests, [])
        app = self.local_app()
        self.assertEqual(self.drain(app), [])
        self.assertEqual(len(self.transport.ids), 1)
        self.assertEqual(app.state["status"], "RUNNING")

    def test_offline_self_fix_complete_then_restart(self):
        app = self.begin()
        self.action(app, app.finish_work)
        app = self.local_app()
        self.assertEqual(self.drain(app), [])
        self.assertEqual(len(self.transport.ids), 1)

    def test_handover_save_failure_rolls_back_response_and_queue(self):
        app = self.begin()
        before = self.path.read_bytes()
        with (
            mock.patch(
                "floorterminal.storage.state.write_json",
                side_effect=OSError("Disk full"),
            ),
            self.assertRaises(StateSaveError),
        ):
            self.action(app, app.request_engineering_handover)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(app.state["status"], "REPAIRING")
        self.assertIsNone(app.state["operator_response"]["requested_at"])
        self.assertEqual(self.transport.requests, [])
