"""End-to-end workflow regressions against the real state store.

Earlier workflow tests replaced ``save_state`` with a no-op, so a transition that
the state validator rejected could never fail in a test. These tests persist
every step to a real ``response_state.json`` in a temporary directory, restart
from that file, and drive a fake connector that never touches the network.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from floorterminal.app import FloorTerminalApp
from floorterminal.controller import workflow as workflow_module
from floorterminal.core.config import DEFAULT_CONFIG
from floorterminal.integration.runtime import IntegrationError
from floorterminal.services.provider import ProviderInfo
from floorterminal.storage import state as state_module
from floorterminal.storage.state import (
    INITIAL_STATE,
    MAX_QUEUED_MESSAGES,
    SPARSE_DEFAULTS,
    StateSaveError,
    StateStore,
)

#: The fields a 1.0.0 terminal accepts; an idle 1.1.0 file must stay within them.
RELEASE_1_0_FIELDS = set(INITIAL_STATE) - set(SPARSE_DEFAULTS)


class Logger:
    def __init__(self):
        self.events = []

    def log(self, event, level="INFO", **details):
        self.events.append((event, level, details))

    def named(self, event):
        return [details for name, _level, details in self.events if name == event]


def unavailable():
    return IntegrationError("Network unavailable: timed out", "UNAVAILABLE")


def rate_limited(retry_after=42):
    return IntegrationError(
        "Application API limit reached (10/10); retry in 42 seconds",
        "RATE_LIMITED",
        429,
        retry_after,
    )


class FakeConnector:
    """Every Connector v1 capability, recorded in memory, with scripted failures."""

    connected = True
    INFO = ProviderInfo("fake", "Fake maintenance system")

    def __init__(self):
        self.calls = []
        self.failures = {}
        self.next_record = 1

    def fail(self, operation, *errors):
        self.failures[operation] = list(errors)

    def _record(self, operation, *arguments):
        self.calls.append((operation, arguments))
        queued = self.failures.get(operation)
        if queued:
            error = queued.pop(0) if len(queued) > 1 else queued[0]
            if error is not None:
                raise error

    def calls_to(self, operation):
        return [arguments for name, arguments in self.calls if name == operation]

    def resolve_name(self, resource, name):
        return "team-1"

    def team_members(self, team_id):
        return [{"id": "u1", "displayName": "Alex Engineer"}]

    def create_response_record(
        self,
        title,
        description,
        team_id,
        priority="HIGH",
        work_type=None,
        participant_ids=None,
        idempotency_key=None,
    ):
        self._record("create", title, idempotency_key)
        record = f"REC-{self.next_record}"
        self.next_record += 1
        return {"id": record, "reference": record}

    def set_response_record_status(self, record_id, status):
        self._record("status", record_id, status)
        return {}

    def assign_participants(self, record_id, team_id, user_ids):
        self._record("assign", record_id, team_id, tuple(user_ids))
        return {}

    def add_response_record_comment(self, record_id, content):
        self._record("comment", record_id, content)
        return {}

    def send_message(self, target, content):
        self._record("message", target, content)
        return {}

    def set_asset_status(
        self, status, downtime_type=None, description=None, started_at=None,
        idempotency_key=None,
    ):
        self._record("asset", status, idempotency_key, downtime_type, description)
        return {"id": f"asset-status-{status}"}


MEMBERS = [{"id": "u1", "displayName": "Alex Engineer"}]


class WorkflowHarness(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "response_state.json"
        self.provider = FakeConnector()

    def tearDown(self):
        self.directory.cleanup()

    def app(self, provider=None, **config):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.state_store = StateStore(self.path)
        app.state = app.state_store.data
        app.logger = Logger()
        app.provider = provider or self.provider
        app.config = {
            **DEFAULT_CONFIG,
            "line_name": "Line 1",
            "engineering_team_name": "Maintenance",
            "engineering_chat_name": "Engineering",
            "production_chat_name": "Production",
            "common_activity_chat_name": "",
            "escalation_chat_name": "",
            "asset_status_tracking": True,
            "asset_id": "asset-1",
            **config,
        }
        app.retry_deadlines = {}
        app.busy = False
        app.modal = None
        app.project_profile = SimpleNamespace(product_name="FloorTerminal")
        app.RED, app.GREEN, app.BLUE = "#E84855", "#16A36A", "#246BFD"
        app.ORANGE, app.PURPLE = "#F09A3E", "#7956D8"
        app.toast_text, app.toast_kind, app.toast_until = "", "info", 0
        return app

    def saved(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def start_repair(self, app, stations=("Station 1",)):
        app.state["issue_zones"] = list(stations)
        app.save_state()
        app.report_downtime()
        app.start_repair("team-1", MEMBERS)
        return app.state["response_record_id"]


class CompletionPersistenceTests(WorkflowHarness):
    def test_repair_completion_is_saved_and_survives_restart(self):
        app = self.app()
        record = self.start_repair(app)
        result = app.finish_work()

        self.assertEqual(app.state["status"], "RUNNING")
        self.assertIn("Production resumed", result)
        self.assertNotIn("queued", result)
        restored = StateStore(self.path).data
        self.assertEqual(restored["status"], "RUNNING")
        self.assertIsNone(restored["response_record_id"])
        self.assertEqual(restored["pending_record_updates"], [])
        self.assertEqual(restored["pending_messages"], [])
        self.assertIn((record, "DONE"), self.provider.calls_to("status"))
        self.assertEqual(self.provider.calls_to("asset")[-1][0], "ONLINE")
        self.assertTrue(
            any("WORK COMPLETED" in args[1] for args in self.provider.calls_to("comment"))
        )
        chats = [args[0] for args in self.provider.calls_to("message")]
        self.assertIn("Production", chats)

    def test_idle_state_file_remains_readable_by_the_previous_release(self):
        app = self.app()
        self.start_repair(app)
        app.finish_work()
        self.assertLessEqual(set(self.saved()), RELEASE_1_0_FIELDS)

    def test_planned_work_label_is_persisted_and_released(self):
        app = self.app()
        app.state["issue_zones"] = ["Station 2"]
        app.start_planned_work("Preventive Maintenance", "PREVENTIVE", "team-1", MEMBERS)
        restored = StateStore(self.path).data
        self.assertEqual(restored["status"], "ENGINEERING")
        self.assertEqual(restored["work_label"], "Preventive Maintenance")
        self.assertEqual(restored["work_type"], "PREVENTIVE")

        app = self.app()
        app.finish_work()
        restored = StateStore(self.path).data
        self.assertEqual(restored["status"], "RUNNING")
        self.assertIsNone(restored["work_label"])
        self.assertNotIn("work_label", self.saved())
        release = [
            args[1] for args in self.provider.calls_to("message") if "RELEASED" in args[1]
        ]
        self.assertIn("Work: Preventive Maintenance", release[0])

    def test_rejected_save_restores_memory_and_later_saves_still_work(self):
        app = self.app()
        self.start_repair(app)
        app.state["status"] = "RUNNING"
        app.state["unsupported_field"] = "value"
        with self.assertRaises(StateSaveError):
            app.save_state()
        self.assertEqual(app.state["status"], "REPAIRING")
        self.assertNotIn("unsupported_field", app.state)
        self.assertEqual(self.saved()["status"], "REPAIRING")
        self.assertTrue(app.logger.named("state_save_failed"))
        # One bad value no longer poisons every later action.
        app.state["issue_zones"] = ["Station 1", "Station 4"]
        app.save_state()
        self.assertEqual(self.saved()["issue_zones"], ["Station 1", "Station 4"])

    def test_interrupted_release_keeps_the_first_confirmation_time(self):
        app = self.app()
        self.start_repair(app)
        started = time.time() - 120
        app.state.update(started_at=started, repair_at=started + 30)
        app.save_state()
        first_release = started + 120
        real_write = state_module.write_json
        writes = []

        def fail_the_transition(path, value):
            writes.append(value.get("status"))
            if value.get("status") == "RUNNING":
                raise OSError("No space left on device")
            return real_write(path, value)

        with (
            mock.patch.object(state_module, "write_json", fail_the_transition),
            self.assertRaises(StateSaveError),
        ):
            app.finish_work(first_release)
        self.assertEqual(app.state["status"], "REPAIRING")
        self.assertEqual(StateStore(self.path).data["status"], "REPAIRING")
        self.assertEqual(self.saved()["completion_confirmed_at"], first_release)

        # After a restart the operator confirms again, several minutes later.
        app = self.app()
        app.confirm_done()
        self.assertIn("was not saved", app.modal["note"])
        app.finish_work(first_release + 278)
        classified = app.logger.named("downtime_classified")[-1]
        self.assertEqual(classified["total_seconds"], 120)
        self.assertEqual(classified["classification"], "MICRO-STOP")
        self.assertTrue(app.logger.named("completion_uses_first_confirmation"))
        self.assertEqual(StateStore(self.path).data["status"], "RUNNING")


class AssetStatusNoteTests(WorkflowHarness):
    """The asset status note says where and why, in the operator's terms."""

    TIME = r"\b\d{1,2}:\d{2}(:\d{2})?\b|\d{4}-\d{2}-\d{2}"

    def test_offline_note_lists_stations_reasons_and_operator_note(self):
        app = self.app()
        app.state.update(
            issue_zones=["Station 1", "Station 3"],
            failure_selections={
                "Station 1": ["Mechanical", "Others"],
                "Station 3": ["Electrical"],
            },
            failure_notes={"Station 1": "Guard door sensor loose"},
        )
        app.save_state()
        app.report_downtime()
        status, _key, downtime_type, note = self.provider.calls_to("asset")[0]
        self.assertEqual((status, downtime_type), ("OFFLINE", "UNPLANNED"))
        self.assertIn("Affected stations: Station 1, Station 3", note)
        self.assertIn("Reason: Station 1: Mechanical, Others; Station 3: Electrical", note)
        self.assertIn("Operator note: Station 1: Guard door sensor loose", note)
        self.assertIn("Response record: #REC-1", note)
        self.assertNotRegex(note, self.TIME)

    def test_planned_and_restored_notes_state_the_work_and_stations(self):
        app = self.app()
        app.state["issue_zones"] = ["Station 2"]
        app.start_planned_work("Preventive Maintenance", "PREVENTIVE", "team-1", MEMBERS)
        _status, _key, downtime_type, note = self.provider.calls_to("asset")[0]
        self.assertEqual(downtime_type, "PLANNED")
        self.assertIn("Planned Preventive Maintenance", note)
        self.assertIn("Affected stations: Station 2", note)
        self.assertIn("Reason: Preventive Maintenance", note)
        self.assertIn("Engineering crew: Alex Engineer", note)
        self.assertNotRegex(note, self.TIME)
        app.finish_work()
        status, _key, _type, note = self.provider.calls_to("asset")[-1]
        self.assertEqual(status, "ONLINE")
        self.assertIn("Affected stations: Station 2", note)
        self.assertIn("Total line time:", note)

    def test_the_note_is_sent_through_the_connector_field_mapping(self):
        """No provider name is involved: connector.json maps the note field."""
        mapping = json.loads(
            (Path(__file__).resolve().parents[2] / "connector.example.json").read_text()
        )["workflow"]["fields"]
        self.assertEqual(mapping["status_description"], "description")


class CompletionSynchronizationTests(WorkflowHarness):
    def test_failed_completion_updates_are_queued_and_retried_after_restart(self):
        app = self.app()
        record = self.start_repair(app)
        for operation in ("status", "comment", "asset", "message"):
            self.provider.fail(operation, unavailable())
        result = app.finish_work()

        self.assertEqual(app.state["status"], "RUNNING")
        self.assertIn("external sync queued", result)
        restored = StateStore(self.path).data
        self.assertEqual(restored["status"], "RUNNING")
        queued = {
            (item["action"], item.get("status"))
            for item in restored["pending_record_updates"]
        }
        self.assertIn(("status", "DONE"), queued)
        self.assertIn(("comment", None), queued)
        self.assertTrue(restored["asset_status_sync_pending"])
        self.assertEqual(restored["asset_status_sync_target"], "ONLINE")
        self.assertEqual(len(restored["pending_messages"]), 2)

        healthy = FakeConnector()
        app = self.app(healthy)
        summary = app.synchronize_due_work(force=True)
        self.assertEqual(summary, "No external updates remain queued • check activity for delivery details")
        self.assertIn((record, "DONE"), healthy.calls_to("status"))
        self.assertEqual(healthy.calls_to("asset")[0][0], "ONLINE")
        released = [args[1] for args in healthy.calls_to("message")]
        self.assertTrue(all("Response record: DONE • Asset: ONLINE" in text for text in released))
        self.assertFalse(app.has_queued_sync())

    def test_empty_queue_after_expiry_does_not_claim_delivery(self):
        app = self.app()
        app.queue_message("Engineering", "Help needed", kind="support")
        for entry in app.state["pending_messages"]:
            entry["expires_at"] = time.time() - 1
        app.save_state()
        summary = app.synchronize_due_work(force=True)
        self.assertFalse(app.has_queued_sync())
        self.assertNotIn("synchronized", summary)
        self.assertIn("check activity", summary)

    def test_completion_message_does_not_claim_an_unsynchronized_close(self):
        app = self.app()
        self.start_repair(app)
        self.provider.fail("status", unavailable())
        app.finish_work()
        released = [
            args[1] for args in self.provider.calls_to("message") if "RELEASED" in args[1]
        ]
        self.assertTrue(released)
        for text in released:
            self.assertIn("Response record: DONE update queued", text)
            self.assertIn("Asset: ONLINE", text)
            self.assertNotIn("Response record: DONE •", text)

    def test_done_for_the_previous_record_survives_the_next_incident(self):
        app = self.app()
        first = self.start_repair(app)
        self.provider.fail("status", unavailable())
        app.finish_work()
        second = self.start_repair(app)
        self.assertNotEqual(first, second)
        queued = [
            (item["record_id"], item.get("status"))
            for item in app.state["pending_record_updates"]
            if item["action"] == "status"
        ]
        self.assertIn((first, "DONE"), queued)

    def test_rate_limited_notifications_are_kept_and_sent_later(self):
        app = self.app()
        self.start_repair(app)
        self.provider.fail("message", rate_limited(), rate_limited())
        app.finish_work()
        queue = app.state["pending_messages"]
        self.assertTrue(queue)
        self.assertEqual(queue[0]["retry_after_seconds"], 43)
        self.assertIn("limit", queue[0]["last_error"])
        self.assertTrue(app.logger.named("lifecycle_chat_failed"))

        self.provider.failures.clear()
        with mock.patch.object(workflow_module.time, "monotonic", return_value=time.monotonic() + 3600):
            self.assertTrue(app.sync_work_due())
        app.flush_messages(force=True)
        self.assertEqual(app.state["pending_messages"], [])
        self.assertTrue(app.logger.named("lifecycle_chat_sent"))

    def test_a_rejected_notification_is_abandoned_after_limited_attempts(self):
        app = self.app()
        self.start_repair(app)
        self.provider.fail(
            "message", RuntimeError('No configured conversation or user named "Production"')
        )
        app.finish_work()
        for _attempt in range(workflow_module.PERMANENT_FAILURE_ATTEMPTS):
            app.flush_messages(force=True)
        self.assertEqual(app.state["pending_messages"], [])
        self.assertTrue(app.logger.named("lifecycle_chat_abandoned"))

    def test_expired_notifications_are_dropped_with_an_audit_entry(self):
        app = self.app()
        app.queue_message("Engineering", "Old news")
        app.state["pending_messages"][0]["expires_at"] = time.time() - 1
        app.save_state()
        outcomes = app.flush_messages()
        self.assertEqual(list(outcomes.values()), ["expired"])
        self.assertEqual(app.state["pending_messages"], [])
        self.assertTrue(app.logger.named("lifecycle_chat_expired"))

    def test_queues_are_bounded(self):
        app = self.app()
        for index in range(MAX_QUEUED_MESSAGES + 5):
            app.queue_message("Engineering", f"Message {index}")
        app.save_state()
        self.assertEqual(len(app.state["pending_messages"]), MAX_QUEUED_MESSAGES)
        self.assertEqual(app.state["pending_messages"][-1]["content"], f"Message {MAX_QUEUED_MESSAGES + 4}")


class SupportCallTests(WorkflowHarness):
    def run_call(self, app, department="Engineering"):
        results = []
        app.perform = lambda working, function, on_success=None, **_options: results.append(
            function()
        )
        app.call_team(department)
        return results[0]

    def test_support_call_is_sent_immediately(self):
        app = self.app()
        self.assertEqual(self.run_call(app), "Message sent to Engineering chat")
        self.assertEqual(app.state["pending_messages"], [])

    def test_rate_limited_support_call_is_queued_not_lost(self):
        app = self.app()
        self.provider.fail("message", rate_limited())
        result = self.run_call(app)
        self.assertIn("Engineering call queued", result)
        self.assertEqual(app.state["pending_messages"][0]["kind"], "support")

    def test_unknown_chat_is_reported_to_the_operator(self):
        app = self.app()
        self.provider.fail("message", RuntimeError('No configured conversation named "X"'))
        with self.assertRaisesRegex(RuntimeError, "Engineering was not notified"):
            self.run_call(app)
        self.assertEqual(app.state["pending_messages"], [])

    def test_missing_chat_setting_is_explained(self):
        app = self.app(quality_chat_name="")
        with self.assertRaisesRegex(RuntimeError, "No Quality chat is configured"):
            self.run_call(app, "Quality")

    def test_every_documented_placeholder_formats_in_every_template(self):
        placeholders = "{line} {zones} {timestamp} {time} {department} {condition} {work_label}"
        app = self.app(
            downtime_title_template=placeholders,
            downtime_description_template=placeholders,
            help_message_template=placeholders,
            planned_work_title_template=placeholders,
            planned_work_description_template=placeholders,
        )
        app.state["issue_zones"] = ["Station 1"]
        app.report_downtime()
        self.assertIn("Line 1", self.provider.calls_to("create")[0][0])
        self.run_call(app)
        self.assertIn("Station 1", self.provider.calls_to("message")[-1][1])
        app.finish_work()
        app.state["issue_zones"] = ["Station 2"]
        app.start_planned_work("Modification / Change", "OTHER", "team-1", MEMBERS)
        self.assertIn("Modification / Change", self.provider.calls_to("create")[-1][0])


class FailureClassificationTests(unittest.TestCase):
    def test_connector_failures_are_classified_for_retry(self):
        kind = workflow_module.failure_kind
        self.assertEqual(kind(rate_limited()), "rate_limited")
        self.assertEqual(kind(unavailable()), "transient")
        self.assertEqual(kind(IntegrationError("x", "SERVER", 500)), "transient")
        self.assertEqual(kind(IntegrationError("x", "NOT_FOUND", 404)), "permanent")
        self.assertEqual(kind(IntegrationError("x", "AUTHENTICATION", 401)), "permanent")
        self.assertEqual(kind(TimeoutError("read timed out")), "transient")
        self.assertEqual(kind(RuntimeError("No configured conversation")), "permanent")



class CompletionEvidenceTests(WorkflowHarness):
    def pending_completion(self, status_error):
        app = self.app()
        self.start_repair(app)
        if status_error:
            self.provider.fail("status", status_error)
        self.provider.fail("message", rate_limited())
        app.finish_work()
        return app

    def assert_unconfirmed_after_restart(self):
        healthy = FakeConnector()
        restored = self.app(healthy)
        restored.flush_messages(force=True)
        messages = healthy.calls_to("message")
        self.assertTrue(messages)
        self.assertTrue(all("DONE not confirmed" in text for _chat, text in messages))
        self.assertFalse(any("Response record: DONE •" in text for _chat, text in messages))

    def test_abandoned_done_is_not_reported_as_success(self):
        app = self.pending_completion(IntegrationError("Forbidden", "PERMISSION", 403))
        for _attempt in range(workflow_module.PERMANENT_FAILURE_ATTEMPTS):
            app.flush_record_updates(force=True)
        self.assertFalse(app.state["pending_record_updates"])
        self.assertTrue(app.logger.named("record_update_abandoned"))
        self.assert_unconfirmed_after_restart()

    def test_expired_done_is_not_reported_as_success(self):
        app = self.pending_completion(unavailable())
        for entry in app.state["pending_record_updates"]:
            entry["expires_at"] = time.time() - 1
        app.save_state()
        app.flush_record_updates(force=True)
        self.assertTrue(app.logger.named("record_update_expired"))
        self.assert_unconfirmed_after_restart()

    def test_evicted_done_is_not_reported_as_success(self):
        app = self.pending_completion(unavailable())
        app._trim_queue(app.state["pending_record_updates"], 0, "record_update_dropped")
        app.save_state()
        self.assert_unconfirmed_after_restart()

    def test_confirmed_done_evidence_survives_delayed_message_and_restart(self):
        app = self.pending_completion(None)
        self.assertFalse(app.state["pending_record_updates"])
        self.assertTrue(all(
            entry["record_status_outcome"] == "confirmed"
            for entry in StateStore(self.path).data["pending_messages"]
        ))
        healthy = FakeConnector()
        self.app(healthy).flush_messages(force=True)
        self.assertTrue(all(
            "Response record: DONE • Asset: ONLINE" in text
            for _chat, text in healthy.calls_to("message")
        ))

    def test_legacy_message_without_delivery_evidence_is_not_assumed_done(self):
        app = self.app()
        entry = app.queue_message("Engineering", "Production released", status_record_id="old-record")
        entry.pop("record_status_outcome")
        app.save_state()
        self.assert_unconfirmed_after_restart()

    def test_invalid_completion_evidence_cannot_be_saved(self):
        app = self.app()
        entry = app.queue_message("Engineering", "Production released", status_record_id="record")
        entry["record_status_outcome"] = "untrusted"
        with self.assertRaises(StateSaveError):
            app.save_state()

if __name__ == "__main__":
    unittest.main()
