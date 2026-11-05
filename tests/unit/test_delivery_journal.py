"""Durable offline delivery; all transports and sockets are non-network doubles."""

import json
import socket
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

from floorterminal.core.rate_policy import RequestWindow
from floorterminal.integration import IntegrationDefinition
from floorterminal.integration.runtime import (
    IntegrationClient,
    IntegrationError,
    TransportResponse,
    retry_after_seconds,
)
from floorterminal.services.delivery import DeferredIntegration, DeliveryCoordinator
from floorterminal.services.integration import ExternalIntegration
from floorterminal.services.provider import NoIntegrationProvider
from floorterminal.storage.delivery import (
    MAX_DELIVERIES,
    binding,
    enqueue,
    validate_journal,
)
from floorterminal.storage.state import StateSaveError, StateStore

from .test_completion_workflow import MEMBERS, WorkflowHarness

ROOT = Path(__file__).resolve().parents[2]


class ScriptedTransport:
    def __init__(self):
        self.requests = []
        self.failure = None
        self.wait = None
        self.entered = threading.Event()
        self.ids = {}

    def send(self, request, timeout):
        self.requests.append(request)
        self.entered.set()
        if self.wait:
            self.wait.wait(5)
        if self.failure:
            raise self.failure
        if request.operation_id == "response_record.create":
            key = request.headers["Idempotency-Key"]
            return TransportResponse(
                201,
                {},
                json.dumps(
                    {"id": self.ids.setdefault(key, f"R{len(self.ids) + 1}")}
                ).encode(),
            )
        if request.operation_id == "team.list":
            return TransportResponse(
                200, {}, b'{"teams":[{"id":"t1","name":"Maintenance"}]}'
            )
        if request.operation_id == "team.members":
            return TransportResponse(
                200, {}, b'{"members":[{"id":"u1","name":"Alex Engineer"}]}'
            )
        if request.operation_id == "conversation.list":
            return TransportResponse(
                200,
                {},
                b'{"conversations":[{"id":"c1","name":"Engineering"},{"id":"c2","name":"Production"}]}',
            )
        if request.operation_id == "user.list":
            return TransportResponse(200, {}, b'{"users":[]}')
        return TransportResponse(200, {}, b"{}")


class DurableDeliveryHarness(WorkflowHarness):
    def setUp(self):
        super().setUp()
        self.socket_patch = mock.patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("Live networking forbidden"),
        )
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["enabled"] = True
        data["connection"]["base_url"] = "https://service.example.test/v1"
        data["credentials"]["access_token"] = "offline-only-secret"
        path = Path(self.directory.name) / "connector.json"
        path.write_text(json.dumps(data))
        self.definition = IntegrationDefinition(path)
        self.transport = ScriptedTransport()

    def local_app(self, *, configured=True):
        app = self.app(api_requests_per_minute=10000)

        # Deterministic local worker for persistence tests. Real asynchronous Tk
        # behavior, including slow disk, is exercised by delivery_ui_driver.
        def perform(
            _label,
            function,
            on_success=None,
            *,
            on_error=None,
            before_transaction=None,
            **_kwargs,
        ):
            if app.busy:
                return False
            app.busy = True
            try:
                if before_transaction:
                    before_transaction()
                with app.state_store.transaction():
                    result = function()
            except Exception as exc:
                app.busy = False
                if on_error:
                    on_error(exc)
                else:
                    raise
            else:
                app.busy = False
                if on_success:
                    on_success(result)
            return True

        app.perform = perform
        remote = (
            ExternalIntegration(app.config, app.logger, self.transport, self.definition)
            if configured
            else NoIntegrationProvider(app.config, app.logger)
        )
        app.provider = DeferredIntegration(app, remote)
        app._api_request_window = RequestWindow()
        app._api_request_window.set_budget(10000)
        app.delivery = DeliveryCoordinator(
            app,
            lambda config, logger, definition: ExternalIntegration(
                config, logger, self.transport, definition
            ),
        )
        return app

    def action(self, app, function, *args):
        with app.state_store.transaction():
            return function(*args)

    def drain(self, app, limit=200):
        for _ in range(limit):
            app.delivery.next_poll = 0
            app.delivery.poll()
            if not app.delivery.active and not any(
                item["phase"] == "queued" for item in app.state["delivery_outbox"]
            ):
                break
            time.sleep(0.002)
        return app.state["delivery_outbox"]


class DurableDeliveryTests(DurableDeliveryHarness):
    def test_delivery_review_waits_safely_during_update_health_trial(self):
        app = self.local_app()
        app.version_trial_active = lambda: True
        for key in ("ui_delivery_retry", "ui_delivery_dismiss"):
            app.modal = {"kind": "delivery", "selected_id": "held-entry"}
            app.handle_layout_control(key)
            self.assertIsNone(app.modal)
            self.assertIn("health check", app.toast_text)

    def test_standalone_mode_never_claims_an_external_help_call_was_queued(self):
        app = self.local_app()
        app.config["reporting_mode"] = "local"
        app.call_team("engineering")
        self.assertEqual(app.state["delivery_outbox"], [])
        self.assertEqual(self.transport.requests, [])
        self.assertIn("disabled", app.toast_text)

    def test_expired_help_is_reviewable_without_a_connection_or_during_quota_pause(
        self,
    ):
        for configured in (False, True):
            with self.subTest(configured=configured):
                app = self.local_app(configured=configured)
                entry = enqueue(
                    app.state,
                    app.provider.remote,
                    "send_message",
                    ["Support", "Stale help"],
                    {},
                    expires_at=time.time() - 1,
                )
                app.state["delivery_pause_until"] = time.time() + 600
                app.delivery.poll()
                self.assertEqual(entry["phase"], "attention")
                app.delivery.dismiss_reviewed_message(entry["id"], "Administrator")
                self.assertEqual(app.state["delivery_outbox"], [])
                self.assertEqual(self.transport.requests, [])

    def test_message_with_literal_local_prefix_is_not_stuck_as_a_dependency(self):
        app = self.local_app()
        app.call_team("engineering")
        item = app.state["delivery_outbox"][0]
        item["args"][1] += "\nOperator note: local: sensor reset attempted"
        self.assertEqual(self.drain(app), [])
        self.assertIn("delivered to the service", app.toast_text)
        self.assertEqual(
            len([r for r in self.transport.requests if r.method == "POST"]), 1
        )

    def test_new_support_call_uses_current_connection_not_old_incident_binding(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        old = app.state["incident_scope"]["connector_binding"]
        app.provider.remote.definition.data["identity"]["name"] = "Replacement service"
        app.call_team("engineering")
        message = app.state["delivery_outbox"][-1]
        self.assertEqual(message["method"], "send_message")
        self.assertEqual(message["binding"], binding(app.provider.remote))
        self.assertNotEqual(message["binding"], old)
        self.assertEqual(app.state["delivery_outbox"][0]["binding"], old)

    def test_success_code_mismatch_holds_message_instead_of_duplicating(self):
        app = self.local_app()
        app.provider.send_message("Engineering", "Request support")
        item = app.state["delivery_outbox"][0]
        item["safe_retry"] = False
        app.delivery._apply(
            item["id"],
            None,
            IntegrationError("Check success_codes", "INVALID_RESPONSE", 202),
            True,
        )
        self.assertEqual(item["phase"], "attention")
        self.assertIn("uncertain", item["error"])
        self.drain(app)
        self.assertEqual(self.transport.requests, [])

    def test_held_messages_can_be_dismissed_with_audit_and_survive_restart(self):
        app = self.local_app()
        app.provider.send_message("Engineering", "Old notification")
        item = app.state["delivery_outbox"][0]
        with self.assertRaises(RuntimeError):
            app.delivery.dismiss_reviewed_message(item["id"], "Administrator")
        item["phase"] = "attention"
        app.delivery.dismiss_reviewed_message(item["id"], "Administrator")
        self.assertEqual(self.local_app().state["delivery_outbox"], [])
        audit = app.logger.named("message_dismissed_after_review")[0]
        self.assertEqual(audit["outcome"], "dismissed_not_confirmed")
        self.assertEqual(audit["content"], "Old notification")
        self.assertEqual(self.transport.requests, [])

    def test_dismiss_never_discards_production_updates(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        item = app.state["delivery_outbox"][0]
        item["phase"] = "attention"
        with self.assertRaises(RuntimeError):
            app.delivery.dismiss_reviewed_message(item["id"], "Administrator")
        self.assertEqual(len(app.state["delivery_outbox"]), 1)

    def test_reviewed_message_retry_refreshes_corrected_directory(self):
        app = self.local_app()
        remote = app.provider.remote
        remote._paged_collection("conversations", "list_conversations")
        self.assertTrue(remote.directory_progress)
        app.provider.send_message("Engineering", "Try again after correction")
        item = app.state["delivery_outbox"][0]
        item["phase"] = "attention"
        app.delivery.retry_reviewed(item["id"], "Administrator")
        self.assertEqual(remote.directory_progress, {})
        self.assertEqual(item["phase"], "queued")

    def test_full_workflow_offline_restart_then_delivery_no_remote_state_regression(
        self,
    ):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        self.action(app, app.start_repair, "t1", MEMBERS)
        self.action(app, app.finish_work)
        self.assertEqual(app.state["status"], "RUNNING")
        self.assertTrue(app.state["delivery_outbox"])
        self.assertEqual(self.transport.requests, [])
        restarted = self.local_app()
        self.assertEqual(restarted.state["status"], "RUNNING")
        self.assertEqual(self.drain(restarted), [])
        self.assertEqual(len(self.transport.ids), 1)
        statuses = [
            json.loads(r.body)["status"]
            for r in self.transport.requests
            if r.operation_id == "response_record.status"
        ]
        self.assertEqual(statuses, ["IN_PROGRESS", "DONE"])
        assets = [
            json.loads(r.body)["status"]
            for r in self.transport.requests
            if r.operation_id == "asset.status"
        ]
        self.assertEqual(assets, ["OFFLINE", "ONLINE"])
        self.assertFalse(
            any(
                "local:" in str(r.body) or "local:" in r.url
                for r in self.transport.requests
            )
        )

    def test_multiple_incidents_without_connection_keep_distinct_creation_keys(self):
        app = self.local_app(configured=False)
        for _ in range(3):
            app.state["issue_zones"] = ["Station 1"]
            self.action(app, app.report_downtime)
            self.action(app, app.change_status, "IN_PROGRESS", "REPAIRING")
            self.action(app, app.finish_work)
        self.assertEqual(app.state["status"], "RUNNING")
        self.assertEqual(
            len(
                {
                    item["id"]
                    for item in app.state["delivery_outbox"]
                    if item["method"] == "create_response_record"
                }
            ),
            3,
        )
        self.assertEqual(self.transport.requests, [])
        restarted = self.local_app()
        self.assertEqual(self.drain(restarted), [])
        self.assertEqual(len(self.transport.ids), 3)

    def test_planned_work_starts_and_completes_offline(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(
            app, app.start_planned_work, "Inspection", "PREVENTIVE", "t1", MEMBERS
        )
        self.assertEqual(app.state["status"], "ENGINEERING")
        started = app.state["started_at"]
        restarted = self.local_app()
        self.assertEqual(restarted.state["started_at"], started)
        self.action(restarted, restarted.finish_work)
        self.assertEqual(restarted.state["status"], "RUNNING")
        self.assertEqual(self.drain(restarted), [])

    def test_slow_background_request_does_not_own_operator_busy_lock(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        self.transport.wait = threading.Event()
        app.delivery.poll()
        self.assertTrue(self.transport.entered.wait(2))
        try:
            self.assertFalse(app.busy)
            self.action(app, app.start_repair, "t1", MEMBERS)
            self.action(app, app.finish_work)
            self.assertEqual(app.state["status"], "RUNNING")
        finally:
            self.transport.wait.set()
        self.assertEqual(self.drain(app), [])

    def test_creation_acknowledgement_does_not_clear_newer_incident(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        first = deepcopy(app.state["delivery_outbox"][0])
        self.action(app, app.start_repair, "t1", MEMBERS)
        self.action(app, app.finish_work)
        app.state["issue_zones"] = ["Station 2"]
        self.action(app, app.report_downtime)
        current = app.state["response_record_id"]
        app.delivery._apply(first["id"], {"id": "R-OLD"}, None, True)
        self.assertEqual(app.state["response_record_id"], current)
        self.assertEqual(app.state["status"], "DOWN")

    def test_retry_after_pauses_entire_queue_and_survives_restart(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        app.provider.set_response_record_status("R2", "DONE")
        item = app.state["delivery_outbox"][0]
        app.delivery._apply(
            item["id"], None, IntegrationError("wait", "RATE_LIMITED", 429, 120), True
        )
        later = self.local_app()
        self.assertGreater(later.state["delivery_pause_until"], time.time() + 115)
        later.delivery.poll()
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(len(later.state["delivery_outbox"]), 2)

    def test_ambiguous_comment_is_held_not_replayed_after_restart(self):
        app = self.local_app()
        app.provider.add_response_record_comment("R1", "Repair complete")
        item = app.state["delivery_outbox"][0]
        app.delivery._apply(
            item["id"], None, IntegrationError("timeout", "UNAVAILABLE"), True
        )
        self.assertEqual(item["phase"], "attention")
        later = self.local_app()
        self.assertEqual(later.state["delivery_outbox"][0]["phase"], "attention")

    def test_native_creation_timeout_is_held_and_can_link_after_restart(self):
        raw = self.definition.data["operations"]["response_record.create"]
        raw.pop("idempotency")
        raw["delivery"] = {"ambiguous_result": "hold"}
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        item = next(
            i
            for i in app.state["delivery_outbox"]
            if i["method"] == "create_response_record"
        )
        app.delivery._apply(
            item["id"],
            None,
            IntegrationError("Request timed out", "UNKNOWN", 408),
            True,
        )
        self.assertEqual(item["phase"], "attention")
        later = self.local_app()
        later.delivery.poll()
        self.assertEqual(self.transport.requests, [])
        later.delivery.link_reviewed_record(item["id"], "verified-17", "Administrator")
        self.assertEqual(later.state["response_record_id"], "verified-17")

    def test_held_asset_event_blocks_later_state_for_the_same_asset(self):
        raw = self.definition.data["operations"]["asset.status"]
        raw.pop("idempotency")
        raw["delivery"] = {"ambiguous_result": "hold"}
        app = self.local_app()
        app.provider.set_asset_status("OFFLINE", "UNPLANNED", "Zone A")
        app.provider.set_asset_status("ONLINE", description="Resumed")
        first = app.state["delivery_outbox"][0]
        app.delivery._apply(
            first["id"], None, IntegrationError("Timeout", "UNAVAILABLE"), True
        )
        later = self.local_app()
        later.state["delivery_pause_until"] = 0
        later.delivery.poll()
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(
            [item["phase"] for item in later.state["delivery_outbox"]],
            ["attention", "queued"],
        )
        with self.assertRaises(ValueError):
            later.delivery.confirm_reviewed_asset(first["id"], "", "Administrator")
        later.delivery.confirm_reviewed_asset(
            first["id"], "external-event-18", "Administrator"
        )
        self.assertEqual(len(later.state["delivery_outbox"]), 1)
        self.assertEqual(later.state["delivery_outbox"][0]["args"][0], "ONLINE")
        restarted = self.local_app()
        self.assertEqual(len(restarted.state["delivery_outbox"]), 1)
        self.assertEqual(self.transport.requests, [])

    def test_asset_confirmation_rejects_wrong_connector_and_queued_events(self):
        app = self.local_app()
        app.provider.set_asset_status("OFFLINE", "UNPLANNED", "Zone A")
        item = app.state["delivery_outbox"][0]
        with self.assertRaises(RuntimeError):
            app.delivery.confirm_reviewed_asset(item["id"], "event-18", "Administrator")
        item["phase"] = "attention"
        original = self.definition.data["identity"]["display_name"]
        self.definition.data["identity"]["display_name"] = "Different connection"
        with self.assertRaises(RuntimeError):
            app.delivery.confirm_reviewed_asset(item["id"], "event-18", "Administrator")
        self.definition.data["identity"]["display_name"] = original
        self.assertEqual(len(app.state["delivery_outbox"]), 1)

    def test_conflict_is_not_retried_forever(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        item = app.state["delivery_outbox"][0]
        app.delivery._apply(
            item["id"], None, IntegrationError("Conflict", "CONFLICT", 409), True
        )
        self.assertEqual(item["phase"], "attention")

    def test_asset_history_uses_original_stop_and_confirmed_release_times(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        started = app.state["started_at"]
        offline = next(
            item
            for item in app.state["delivery_outbox"]
            if item["method"] == "set_asset_status"
        )
        self.assertAlmostEqual(
            datetime.fromisoformat(offline["args"][3]).timestamp(), started, places=2
        )
        self.action(app, app.start_repair, "t1", MEMBERS)
        released = time.time()
        app.state["completion_confirmed_at"] = released
        app.save_state()
        with mock.patch(
            "floorterminal.controller.workflow.time.time", return_value=released + 300
        ):
            self.action(app, app.finish_work)
        online = [
            item
            for item in app.state["delivery_outbox"]
            if item["method"] == "set_asset_status"
        ][-1]
        self.assertAlmostEqual(
            datetime.fromisoformat(online["args"][3]).timestamp(), released, places=2
        )

    def test_interrupted_safe_and_unsafe_sends_recover_differently(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        app.provider.add_response_record_comment("R1", "Complete")
        for index, item in enumerate(app.state["delivery_outbox"]):
            item.update(phase="sending", safe_retry=index == 0)
        app.save_state()
        restarted = self.local_app()
        self.assertEqual(
            [item["phase"] for item in restarted.state["delivery_outbox"]],
            ["queued", "attention"],
        )

    def test_failed_local_ack_is_retried_without_another_external_request(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        item = app.state["delivery_outbox"][0]
        item["phase"] = "sending"
        app.save_state()
        app.delivery.active = item["id"]
        app.delivery.results.put((item["id"], {}, None, True))
        with (
            mock.patch(
                "floorterminal.storage.state.write_json",
                side_effect=OSError("disk unavailable"),
            ),
        ):
            app.delivery.poll()
        self.assertFalse(app.delivery.results.empty())
        app.delivery.ack_retry_at = 0
        app.delivery.poll()
        self.assertEqual(app.state["delivery_outbox"], [])
        self.assertEqual(self.transport.requests, [])

    def test_transaction_does_not_commit_partial_transition_or_intents(self):
        app = self.local_app()
        app.save_state()
        original = self.path.read_bytes()
        with self.assertRaises(RuntimeError), app.state_store.transaction():
            app.state["status"] = "DOWN"
            app.provider.set_response_record_status("R1", "DONE")
            raise RuntimeError("interrupted local action")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(app.state["status"], "RUNNING")

    def test_journal_capacity_rejects_new_intent_without_evicting_old_work(self):
        app = self.local_app()
        for index in range(MAX_DELIVERIES):
            enqueue(
                app.state,
                app.provider.remote,
                "set_response_record_status",
                [str(index), "DONE"],
                {},
            )
        ids = [item["id"] for item in app.state["delivery_outbox"]]
        with self.assertRaises(ValueError):
            enqueue(
                app.state,
                app.provider.remote,
                "set_response_record_status",
                ["new", "DONE"],
                {},
            )
        self.assertEqual([item["id"] for item in app.state["delivery_outbox"]], ids)

    def test_delivery_binding_prevents_connector_switch_retargeting(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        app.provider.remote.definition.data["connection"]["base_url"] = (
            "https://another.example.test/v1"
        )
        app.delivery.poll()
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(len(app.state["delivery_outbox"]), 1)

    def test_queue_and_roster_never_contain_credentials(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        self.assertNotIn("offline-only-secret", self.path.read_text())
        self.assertNotIn("https://", self.path.read_text())

    def test_invalid_journal_is_rejected_at_startup(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        saved = self.saved()
        saved["delivery_outbox"][0]["method"] = "__getattribute__"
        self.path.write_text(json.dumps(saved))
        with self.assertRaises(ValueError):
            StateStore(self.path)

    def test_expired_support_is_retained_for_review(self):
        app = self.local_app()
        item = enqueue(
            app.state,
            app.provider.remote,
            "send_message",
            ["Engineering", "Help"],
            {},
            expires_at=time.time() - 1,
        )
        app.save_state()
        app.delivery.poll()
        self.assertEqual(item["phase"], "attention")
        self.assertEqual(self.transport.requests, [])

    def test_retry_counters_and_deadlines_remain_bounded_at_large_counts(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        item = app.state["delivery_outbox"][0]
        item["attempts"] = 10**10
        item["safe_retry"] = True
        app.delivery._apply(
            item["id"], None, IntegrationError("unavailable", "UNAVAILABLE"), True
        )
        self.assertLessEqual(item["next_at"] - time.time(), 901)
        for _ in range(10000):
            app.delivery._due(item)
        self.assertEqual(len(app.delivery.deadlines), 1)

    def test_retry_after_supports_seconds_dates_invalid_and_case_insensitive_fields(
        self,
    ):
        self.assertEqual(retry_after_seconds({"retry-after": "37"}), 37)
        future = format_datetime(
            datetime.now(UTC) + timedelta(seconds=125), usegmt=True
        )
        self.assertTrue(123 <= retry_after_seconds({"Retry-After": future}) <= 125)
        self.assertIsNone(retry_after_seconds({"Retry-After": "broken"}))
        self.assertEqual(retry_after_seconds({"Retry-After": "0"}), 0)

    def test_http429_honors_server_delay_without_inline_retries(self):
        transport = mock.Mock()
        transport.send.return_value = TransportResponse(
            429, {"Retry-After": "80"}, b"{}"
        )
        client = IntegrationClient(self.definition, transport=transport)
        with self.assertRaises(IntegrationError) as error:
            client.execute("user.list")
        self.assertEqual(error.exception.retry_after, 80)
        with self.assertRaises(IntegrationError):
            client.execute("user.list")
        self.assertEqual(transport.send.call_count, 1)

    def test_roster_refresh_is_nonblocking_and_persisted_for_offline_selection(self):
        app = self.local_app()
        app.load_engineers({"kind": "repair"})
        self.assertEqual(app.modal["kind"], "offline_crew")
        self.assertFalse(app.busy)
        self.drain(app)
        self.assertTrue(app.state["roster_cache"])
        restarted = self.local_app()
        restarted.load_engineers({"kind": "repair"})
        self.assertEqual(restarted.modal["kind"], "engineers")
        self.assertEqual(restarted.modal["members"][0]["id"], "u1")

    def test_binding_is_unchanged_when_only_credentials_rotate(self):
        app = self.local_app()
        before = binding(app.provider.remote)
        app.provider.remote.definition.data["credentials"]["access_token"] = (
            "replacement"
        )
        self.assertEqual(binding(app.provider.remote), before)
        validate_journal(app.state["delivery_outbox"])

    def test_swallowed_queue_failure_cannot_commit_a_partial_local_transition(self):
        app = self.local_app()
        app.save_state()
        before = self.path.read_bytes()
        with self.assertRaises(StateSaveError), app.state_store.transaction():
            app.state["status"] = "DOWN"
            with mock.patch(
                "floorterminal.services.delivery.enqueue",
                side_effect=ValueError("journal full"),
            ):
                try:
                    app.provider.set_response_record_status("R1", "DONE")
                except StateSaveError:
                    pass  # A legacy best-effort wrapper cannot hide this loss.
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(app.state["status"], "RUNNING")

    def test_release_timestamp_survives_failed_atomic_release_and_restart(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        self.action(app, app.start_repair, "t1", MEMBERS)
        confirmed = time.time()
        app.capture_release_confirmation(confirmed)
        with (
            mock.patch(
                "floorterminal.storage.state.write_json",
                side_effect=OSError("disk unavailable"),
            ),
            self.assertRaises(StateSaveError),
        ):
            self.action(app, app.finish_work, confirmed)
        restarted = self.local_app()
        self.assertEqual(restarted.state["completion_confirmed_at"], confirmed)
        self.action(restarted, restarted.finish_work, confirmed + 600)
        self.assertEqual(restarted.state["status"], "RUNNING")
        self.assertEqual(
            restarted.logger.named("completion_uses_first_confirmation")[-1][
                "confirmed_at"
            ],
            confirmed,
        )

    def test_idempotent_create_accepted_then_timeout_replays_same_key(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        original = self.transport.send
        first = True

        def uncertain(request, timeout):
            nonlocal first
            result = original(request, timeout)
            if first and request.operation_id == "response_record.create":
                first = False
                raise IntegrationError("Response lost after acceptance", "UNAVAILABLE")
            return result

        self.transport.send = uncertain
        self.drain(app)
        self.assertEqual(len(self.transport.ids), 1)
        self.assertEqual(app.state["delivery_outbox"][0]["phase"], "queued")
        app.state["delivery_pause_until"] = 0
        for item in app.state["delivery_outbox"]:
            item["next_at"] = 0
        app.save_state()
        restarted = self.local_app()
        self.assertEqual(self.drain(restarted), [])
        self.assertEqual(len(self.transport.ids), 1)
        keys = [
            r.headers["Idempotency-Key"]
            for r in self.transport.requests
            if r.operation_id == "response_record.create"
        ]
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])

    def test_only_expired_help_can_be_archived(self):
        app = self.local_app()
        item = enqueue(
            app.state,
            app.provider.remote,
            "send_message",
            ["Engineering", "Help"],
            {},
            expires_at=time.time() - 1,
        )
        app.save_state()
        app.delivery.poll()
        app.delivery.archive_expired_notice(item["id"], "Site administrator")
        self.assertEqual(app.state["delivery_outbox"], [])
        app.provider.set_response_record_status("R1", "DONE")
        item = app.state["delivery_outbox"][0]
        item["phase"] = "attention"
        with self.assertRaises(RuntimeError):
            app.delivery.archive_expired_notice(item["id"], "Site administrator")
        self.assertEqual(len(app.state["delivery_outbox"]), 1)

    def test_held_comment_does_not_block_done_or_unrelated_records(self):
        app = self.local_app()
        app.provider.add_response_record_comment("R1", "Needs review")
        app.state["delivery_outbox"][0]["phase"] = "attention"
        app.provider.set_response_record_status("R1", "DONE")
        app.provider.set_response_record_status("R2", "DONE")
        self.drain(app)
        self.assertEqual(len(app.state["delivery_outbox"]), 1)
        self.assertEqual(len(self.transport.requests), 2)

    def test_missing_capability_is_retained_and_explained(self):
        app = self.local_app(configured=False)
        app.provider.set_response_record_status("R1", "DONE")
        app.delivery.poll()
        self.assertIn(
            "connector", app.delivery.explanation(app.state["delivery_outbox"][0])
        )
        self.assertEqual(len(app.state["delivery_outbox"]), 1)

    def test_remote_cannot_return_reserved_local_record_identifier(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        item = app.state["delivery_outbox"][0]
        app.delivery._apply(item["id"], {"id": "local:wrong"}, None, True)
        self.assertEqual(item["phase"], "attention")

    def test_admin_links_existing_record_without_recreating_it(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        self.action(app, app.start_repair, "t1", MEMBERS)
        item = app.state["delivery_outbox"][0]
        item["phase"] = "attention"
        app.save_state()
        app.delivery.link_reviewed_record(
            item["id"], "R-verified", "Site administrator"
        )
        self.assertEqual(app.state["response_record_id"], "R-verified")
        self.assertEqual(self.drain(app), [])
        self.assertFalse(self.transport.ids)
        self.assertTrue(app.logger.named("delivery_record_link_authorized"))

    def test_linking_refuses_another_connection_or_an_active_create(self):
        app = self.local_app()
        app.state["issue_zones"] = ["Station 1"]
        self.action(app, app.report_downtime)
        item = app.state["delivery_outbox"][0]
        with self.assertRaises(RuntimeError):
            app.delivery.link_reviewed_record(item["id"], "R-verified", "Administrator")
        item["phase"] = "attention"
        app.provider.remote.definition.data["identity"]["name"] = "Different connection"
        with self.assertRaises(RuntimeError):
            app.delivery.link_reviewed_record(item["id"], "R-verified", "Administrator")

    def test_directory_cache_keeps_only_normalized_identity_fields(self):
        app = self.local_app()
        original = self.transport.send

        def roster(request, timeout):
            if request.operation_id == "team.members":
                return TransportResponse(
                    200,
                    {},
                    b'{"members":[{"id":"u2","firstName":"Taylor","lastName":"Engineer","email":"private@example.test","metadata":{"sensitive":"omit"}}]}',
                )
            return original(request, timeout)

        self.transport.send = roster
        app.load_engineers({"kind": "repair"})
        self.drain(app)
        member = app.state["roster_cache"]["members"][0]
        self.assertEqual(set(member), {"id", "displayName"})
        self.assertNotIn("private@example.test", self.path.read_text())
        self.assertNotIn("sensitive", self.path.read_text())

    def test_current_crew_remains_editable_when_missing_from_cached_directory(self):
        app = self.local_app()
        app.load_engineers({"kind": "repair"})
        self.drain(app)
        app.state.update(
            engineer_ids=["u-former"], engineer_names=["Current Responder"]
        )
        app.load_engineers({"kind": "edit"})
        self.assertIn("u-former", {member["id"] for member in app.modal["members"]})

    def test_dispatch_failure_becomes_review_state_without_escaping_event_loop(self):
        app = self.local_app()
        app.provider.set_response_record_status("R1", "DONE")
        app.delivery.provider_factory = mock.Mock(
            side_effect=ValueError("Invalid target configuration")
        )
        app.delivery.poll()
        app.delivery.poll()  # Persistence outcome arrives on the next event tick.
        self.assertEqual(app.state["delivery_outbox"][0]["phase"], "attention")
        self.assertIsNone(app.delivery.active)
