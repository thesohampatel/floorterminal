"""Adversarial recovery and low-budget cases found during the v1.2 audit."""

import json
import os
import queue
from copy import deepcopy
from unittest import mock

from floorterminal.app import FloorTerminalApp
from floorterminal.core.json_file import read_bounded_json
from floorterminal.integration import IntegrationDefinition
from floorterminal.integration.directory import read_directory
from floorterminal.integration.runtime import IntegrationError
from floorterminal.services.history import HistoryCoordinator
from floorterminal.storage.state import StateIntegrityError, StateStore

from .test_station_groups import GroupHarness


class AuditRegressions(GroupHarness):
    def next_window(self, app):
        app._api_request_window.timestamps.clear()
        app._api_request_window.cooldown_until = 0
        app.state["delivery_pause_until"] = 0
        for item in app.state["delivery_outbox"]:
            item["next_at"] = 0
        app.delivery.deadlines.clear()
        app.delivery.next_poll = app.delivery.roster_retry_at = 0
        if app.state.get("roster_refresh"):
            app.state["roster_refresh"]["retry_at"] = 0

    def test_one_request_budget_eventually_delivers_full_workflow(self):
        app = self.group_app()
        self.report(app, "Station 1")
        self.action(app, app.start_repair, "t1", [])
        self.action(app, app.finish_work)
        app._api_request_window.set_budget(1)
        for _ in range(40):
            before = len(self.transport.requests)
            self.next_window(app)
            self.drain(app, 25)
            self.assertLessEqual(len(self.transport.requests) - before, 1)
            if not app.state["delivery_outbox"]:
                break
        self.assertEqual(app.state["delivery_outbox"], [])
        self.assertEqual(len(self.transport.ids), 1)
        self.assertEqual(
            sum(r.operation_id == "team.list" for r in self.transport.requests), 1
        )

    def test_roster_auto_retries_after_low_budget_without_repeating_team_lookup(self):
        app = self.group_app()
        app._api_request_window.set_budget(1)
        app.load_engineers({"kind": "repair"})
        self.drain(app)
        self.assertTrue(app.delivery.roster_requested)
        self.next_window(app)
        self.drain(app)
        self.assertEqual(len(app.state["roster_cache"]["members"]), 1)
        self.assertEqual(
            app.state["roster_cache"]["members"][0]["displayName"], "Alex Engineer"
        )
        self.assertEqual(
            sum(r.operation_id == "team.list" for r in self.transport.requests), 1
        )

    def test_paginated_lookup_resumes_after_interruption_and_omits_private_fields(self):
        app = self.group_app()
        remote = app.provider.remote
        calls = []

        def response(operation, **kwargs):
            calls.append(kwargs["query"].get("cursor"))
            if len(calls) == 1:
                return {
                    "teams": [{"id": "1", "name": "First", "secret": "omit"}],
                    "nextCursor": "page2",
                }
            if len(calls) == 2:
                raise IntegrationError("Try later", "RATE_LIMITED", 429, 60)
            return {"teams": [{"id": "2", "name": "Second"}]}

        remote._execute = response
        with self.assertRaises(IntegrationError):
            read_directory(remote, "teams", "list_teams")
        result = read_directory(remote, "teams", "list_teams")
        self.assertEqual(calls, [None, "page2", "page2"])
        self.assertEqual(len(result), 2)
        self.assertNotIn("secret", json.dumps(remote.directory_progress))

    def test_dispatch_cannot_reach_network_before_state_is_saved(self):
        app = self.group_app()
        self.report(app, "Station 1")
        with mock.patch(
            "floorterminal.storage.state.write_json", side_effect=OSError("full")
        ):
            app.delivery.poll()
        self.assertEqual(self.transport.requests, [])
        self.assertIsNone(app.delivery.active)
        self.assertEqual(app.state["delivery_outbox"][0]["phase"], "queued")

    def test_history_recovers_when_outer_transaction_commit_fails(self):
        app = self.group_app()
        self.report(app, "Station 1", "")
        service = HistoryCoordinator(app)
        record = deepcopy(app.state["history_pending"][0])
        service.active = True
        service.results.put(([record], {}, {}, None))
        with mock.patch(
            "floorterminal.storage.state.write_json", side_effect=OSError("full")
        ):
            service.poll()
        self.assertFalse(service.results.empty())
        self.assertEqual(app.state["history_pending"], [record])
        service.ack_retry_at = 0
        service.poll()
        self.assertEqual(app.state["history_pending"], [])
        self.assertFalse(service.active)

    def test_real_operation_worker_delivers_outer_commit_error_callback(self):
        app = self.group_app()
        self.report(app, "Station 1", "")
        app.events = queue.Queue()
        app.request_render = lambda: None
        callback = mock.Mock()

        def action():
            app.state["history_pending"] = []

        with mock.patch(
            "floorterminal.storage.state.write_json", side_effect=OSError("full")
        ):
            FloorTerminalApp.perform(app, "Ack", action, quiet=True, on_error=callback)
            outcome = app.events.get(timeout=3)
        self.assertFalse(outcome[0])
        self.assertIs(outcome[2], callback)
        self.assertTrue(app.state["history_pending"])

    def test_assignment_without_a_team_never_sends_a_null_team_identifier(self):
        app = self.group_app()
        app.provider.remote.assign_participants("R1", None, ["u1"])
        body = json.loads(self.transport.requests[-1].body)
        self.assertEqual(body["assignees"], [{"type": "USER", "id": "u1"}])

    def test_oversized_remote_record_identifier_is_not_written_to_recovery(self):
        app = self.group_app()
        self.report(app, "Station 1")
        item = app.state["delivery_outbox"][0]
        app.delivery._apply(item["id"], {"id": "x" * 201}, None, True)
        self.assertTrue(app.state["response_record_id"].startswith("local:"))
        self.assertTrue(app.state["delivery_outbox"])

    def test_runtime_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for text in (
            '{"status":"DOWN","status":"RUNNING"}',
            '{"value":NaN}',
            '{"value":1e999}',
            '{"schema_version":true}',
            "[]",
            "null",
            "false",
            "0",
            "[" * 2000 + "0" + "]" * 2000,
        ):
            self.path.write_text(text)
            with self.assertRaises((ValueError, StateIntegrityError)):
                StateStore(self.path)

    def test_bounded_runtime_json_rejects_oversize_before_decoding(self):
        self.path.write_bytes(b" " * 2048)
        with self.assertRaisesRegex(ValueError, "safety limit"):
            read_bounded_json(self.path, max_bytes=1024)

    def test_runtime_json_rejects_links_without_changing_the_target(self):
        target = self.path.parent / "target"
        target.write_text('{"private":"preserve"}')
        target.chmod(0o644)
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            read_bounded_json(self.path, max_bytes=1024, private=True)
        self.path.unlink()
        os.link(target, self.path)
        with self.assertRaises(ValueError):
            read_bounded_json(self.path, max_bytes=1024, private=True)
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_connector_rejects_duplicate_keys_and_oversized_json(self):
        path = self.path.parent / "bad.connector.json"
        for payload in (
            '{"enabled":false,"enabled":true}',
            " " * (2 * 1024 * 1024 + 1),
        ):
            path.write_text(payload)
            with self.assertRaises(ValueError):
                IntegrationDefinition(path)

    def test_directory_duplicates_cannot_route_to_the_wrong_person_or_group(self):
        remote = self.group_app().provider.remote
        for resource in ("team", "conversation", "user"):
            records = [{"id": "1", "name": "Example"}, {"id": "2", "name": "EXAMPLE"}]
            collections = [None, None, None]
            collections[("team", "conversation", "user").index(resource)] = records
            remote._cache_directory(*collections)
            with self.assertRaisesRegex(RuntimeError, "Multiple configured"):
                if resource == "team":
                    remote.resolve_name(resource, "Example")
                else:
                    remote.send_message(
                        "Example", "Do not send to an arbitrary recipient"
                    )
            remote.name_cache = {"team": {}, "conversation": {}, "user": {}}
        self.assertEqual(self.transport.requests, [])

    def test_directory_cache_replaces_stale_entries_and_bounds_page_storage(self):
        from floorterminal.integration import directory

        remote = self.group_app().provider.remote
        remote._cache_directory([{"id": "1", "name": "Old"}], None, None)
        remote._cache_directory([{"id": "2", "name": "New"}], None, None)
        self.assertEqual(remote.name_cache["team"], {"new": "2"})
        remote._execute = lambda *_a, **_kw: {
            "teams": [{"id": "1", "name": "x" * 1000}]
        }
        with (
            mock.patch.object(directory, "MAX_BYTES", 100),
            self.assertRaisesRegex(IntegrationError, "safe lookup capacity"),
        ):
            read_directory(remote, "teams", "list_teams")
        self.assertEqual(remote.directory_progress, {})

    def test_unsafe_connector_selection_is_ignored_without_hanging(self):
        from floorterminal.integration.discovery import discover_connectors

        marker = self.path.parent / ".active_connector"
        for payload in (b"x" * 4097, b"\xff"):
            marker.write_bytes(payload)
            discover_connectors(self.path.parent)
        marker.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(marker)
            try:
                discover_connectors(self.path.parent)
            finally:
                marker.unlink()

    def test_busy_local_commit_cannot_be_mutated_by_modal_touch_or_keyboard(self):
        from types import SimpleNamespace

        app = self.group_app()
        app.busy = True
        app.error_panel = None
        app.canvas = SimpleNamespace(to_logical=lambda x, y: (x, y))
        app.pressed = "failure_done"
        app.hitboxes = {"failure_done": (0, 0, 100, 100)}
        app.modal = {"kind": "failures"}
        app.save_failure_selection = mock.Mock()
        app._handle_release(SimpleNamespace(x=50, y=50))
        app.save_failure_selection.assert_not_called()
        app.pressed = "ui_roster_skip"
        app.hitboxes = {"ui_roster_skip": (0, 0, 100, 100)}
        app.modal = {"kind": "offline_crew", "context": {"kind": "repair"}}
        app._handle_release(SimpleNamespace(x=50, y=50))
        self.assertEqual(app.modal["kind"], "offline_crew")
        app.modal = {"kind": "text_input", "value": "original"}
        app._handle_keypress(SimpleNamespace(keysym="Return"))
        self.assertEqual(app.modal["value"], "original")

    def test_failed_station_draft_commit_preserves_state_and_dialog(self):
        from floorterminal.storage.state import StateSaveError

        app = self.group_app()
        app.modal = None
        before = deepcopy(app.state)
        with (
            mock.patch(
                "floorterminal.storage.state.write_json", side_effect=OSError("full")
            ),
            self.assertRaises(StateSaveError),
        ):
            app.select_issue_zone("0")
        self.assertEqual(app.state, before)
        self.assertIsNone(app.modal)

    def test_history_worker_start_failure_remains_retryable(self):
        app = self.group_app()
        self.report(app, "Station 1", "")
        service = HistoryCoordinator(app)
        with mock.patch(
            "floorterminal.services.history.threading.Thread.start",
            side_effect=RuntimeError("No worker available"),
        ):
            service.poll()
        service.poll()
        self.assertFalse(service.active)
        self.assertTrue(app.state["history_pending"])
        self.assertIn("No worker available", service.health["error"])
        service.close()
