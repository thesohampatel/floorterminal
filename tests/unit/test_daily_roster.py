"""Daily, durable team directory behavior; socket guard inherited by fixtures."""

import json
import os
import threading
import time
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from unittest import mock

from floorterminal.core.roster import daily_due, next_midnight, validate_refresh
from floorterminal.integration.runtime import IntegrationError, TransportResponse
from floorterminal.storage.delivery import binding
from floorterminal.storage.state import StateSaveError, StateStore

from . import test_audit_regressions
from .test_station_groups import GroupHarness


class CalendarRosterTests(unittest.TestCase):
    def test_same_day_yesterday_and_bad_future_clock(self):
        noon = (
            datetime.now(UTC)
            .astimezone()
            .replace(hour=12, minute=30, second=0)
            .timestamp()
        )
        self.assertFalse(daily_due(noon - 60, noon))
        self.assertTrue(daily_due(noon - 86400, noon))
        self.assertTrue(daily_due(noon + 86400, noon))
        self.assertTrue(daily_due(1e308, noon))

    @unittest.skipUnless(hasattr(time, "tzset"), "host does not expose tzset")
    def test_calendar_midnight_across_dst_uses_23_and_25_hour_days(self):
        try:
            with mock.patch.dict(os.environ, {"TZ": "America/Toronto"}):
                time.tzset()
                for start, hours in (
                    (datetime(2026, 3, 8, 5, tzinfo=UTC).timestamp(), 23),
                    (datetime(2026, 11, 1, 4, tzinfo=UTC).timestamp(), 25),
                ):
                    midnight = next_midnight(start)
                    self.assertEqual(midnight - start, hours * 3600)
                    self.assertFalse(daily_due(start, midnight - 1))
                    self.assertTrue(daily_due(start, midnight))
        finally:
            time.tzset()


class DailyRosterTests(GroupHarness):
    def seed(self, app, *, age=0, members=None):
        app.state["roster_cache"] = {
            "binding": binding(app.provider.remote),
            "team_name": app.config["engineering_team_name"],
            "team_id": "t1",
            "members": [{"id": "u1", "displayName": "Saved Engineer"}]
            if members is None
            else members,
            "saved_at": time.time() - age,
        }
        app.save_state()

    def idle(self, app):
        app.modal = None
        app.last_operator_activity = time.monotonic() - 65
        app.delivery.next_poll = 0

    def advance_retry(self, app):
        test_audit_regressions.AuditRegressions.next_window(self, app)

    def test_repeated_picker_opens_and_restart_use_saved_list_without_requests(self):
        app = self.group_app()
        self.seed(app, age=3700)
        before = self.path.read_bytes()
        for target in (app, self.group_app()):
            for _ in range(25):
                target.load_engineers({"kind": "repair"})
                self.assertEqual(target.modal["kind"], "engineers")
                target.delivery.next_poll = 0
                target.delivery.poll()
                self.assertFalse(target.delivery.roster_requested)
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(self.path.read_bytes(), before)

    def test_yesterday_refreshes_once_when_idle_and_not_again_today(self):
        app = self.group_app()
        self.seed(app, age=86400)
        self.idle(app)
        self.drain(app)
        self.assertFalse(daily_due(app.state["roster_cache"]["saved_at"], time.time()))
        self.assertEqual(len(self.transport.requests), 2)
        self.assertFalse(app.state["roster_refresh"]["pending"])
        for _ in range(30):
            app.delivery.next_poll = 0
            app.delivery.poll()
        self.assertEqual(len(self.transport.requests), 2)
        restarted = self.group_app()
        self.idle(restarted)
        self.drain(restarted)
        self.assertEqual(len(self.transport.requests), 2)

    def test_daily_refresh_defers_during_operator_use_or_active_response(self):
        app = self.group_app()
        self.seed(app, age=86400)
        for key, value in (
            ("modal", {"kind": "about"}),
            ("settings_visible", True),
            ("error_panel", {"message": "review"}),
            ("last_operator_activity", time.monotonic()),
        ):
            self.idle(app)
            setattr(app, key, value)
            app.delivery.poll()
            self.assertEqual(self.transport.requests, [])
            setattr(app, key, None if key != "last_operator_activity" else 0)
        self.idle(app)
        app.state["issue_zones"] = ["Station 1"]
        app.delivery.poll()
        self.assertEqual(self.transport.requests, [])
        app.state.update(issue_zones=[], status="DOWN", started_at=time.time())
        self.drain(app)
        self.assertEqual(self.transport.requests, [])

    def test_explicit_refresh_reloads_today_coalesces_and_survives_restart(self):
        app = self.group_app()
        self.seed(app)
        for _ in range(20):
            app.delivery.request_roster()
        self.assertEqual(self.transport.requests, [])
        self.assertTrue(StateStore(self.path).data["roster_refresh"]["pending"])
        restarted = self.group_app()
        self.drain(restarted)
        self.assertEqual(len(self.transport.requests), 2)
        restarted.delivery.request_roster()
        self.drain(restarted)
        self.assertEqual(
            len(self.transport.requests), 4
        )  # real fresh read, not 5-minute memory cache

    def test_empty_directory_is_verified_and_does_not_refetch_on_every_click(self):
        app = self.group_app()
        original = self.transport.send

        def empty_members(request, timeout):
            if request.operation_id == "team.members":
                self.transport.requests.append(request)
                return TransportResponse(200, {}, b'{"members":[]}')
            return original(request, timeout)

        self.transport.send = empty_members
        app.delivery.request_roster()
        self.drain(app)
        self.assertEqual(app.state["roster_cache"]["members"], [])
        requests = len(self.transport.requests)
        for _ in range(20):
            app.load_engineers({"kind": "repair"})
            self.drain(app)
            self.assertEqual(app.modal["kind"], "offline_crew")
        self.assertEqual(len(self.transport.requests), requests)

    def test_rate_limit_retains_old_list_and_retry_survives_restart(self):
        app = self.group_app()
        self.seed(app)
        before = deepcopy(app.state["roster_cache"])
        self.transport.failure = IntegrationError("Quota", "RATE_LIMITED", 429, 300)
        app.delivery.request_roster()
        self.drain(app)
        self.assertEqual(app.state["roster_cache"], before)
        self.assertGreaterEqual(
            app.state["roster_refresh"]["retry_at"], time.time() + 295
        )
        calls = len(self.transport.requests)
        restarted = self.group_app()
        for _ in range(20):
            restarted.delivery.request_roster()
            self.drain(restarted)
        self.assertEqual(len(self.transport.requests), calls)
        self.transport.failure = None
        self.advance_retry(restarted)
        self.drain(restarted)
        self.assertFalse(restarted.state["roster_refresh"]["pending"])

    def test_offline_roster_remains_selectable_and_no_duplicate_retry_storm(self):
        app = self.group_app()
        self.seed(app, age=86400)
        self.transport.failure = IntegrationError("Offline", "UNAVAILABLE")
        self.idle(app)
        self.drain(app)
        self.assertEqual(len(self.transport.requests), 1)
        for _ in range(20):
            app.load_engineers({"kind": "repair"})
            self.assertEqual(app.modal["members"][0]["displayName"], "Saved Engineer")
            self.drain(app)
        self.assertEqual(len(self.transport.requests), 1)

    def test_server_retry_after_longer_than_a_day_is_not_shortened_on_restart(self):
        app = self.group_app()
        self.seed(app)
        self.transport.failure = IntegrationError("Quota", "RATE_LIMITED", 429, 172800)
        app.delivery.request_roster()
        self.drain(app)
        restarted = self.group_app()
        self.drain(restarted)
        self.assertGreater(
            restarted.delivery.roster_retry_at - time.monotonic(), 172790
        )
        calls = len(self.transport.requests)
        with mock.patch(
            "floorterminal.services.roster.time.monotonic",
            return_value=time.monotonic() + 86401,
        ):
            restarted.delivery.next_poll = 0
            restarted.delivery.poll()
        self.assertEqual(len(self.transport.requests), calls)

    def test_changed_binding_or_team_does_not_expose_or_apply_old_roster(self):
        app = self.group_app()
        self.seed(app)
        self.transport.wait = threading.Event()
        self.addCleanup(self.transport.wait.set)
        app.delivery.request_roster()
        app.delivery.poll()
        self.assertTrue(self.transport.entered.wait(1))
        app.config["engineering_team_name"] = "Another team"
        self.assertEqual(app.delivery.cached_roster(), {})
        self.transport.wait.set()
        self.drain(app)
        self.assertEqual(
            app.state["roster_cache"]["members"][0]["displayName"], "Saved Engineer"
        )
        self.assertEqual(app.delivery.cached_roster(), {})

    def test_empty_new_list_preserves_current_crew_for_removal(self):
        app = self.group_app()
        self.seed(app, members=[])
        app.state.update(engineer_ids=["retired"], engineer_names=["Current Engineer"])
        app.load_engineers({"kind": "edit"})
        self.assertEqual(
            app.modal["members"],
            [
                {
                    "id": "retired",
                    "displayName": "Current Engineer",
                    "teamRole": "CURRENT",
                }
            ],
        )
        self.assertEqual(app.modal["selected"], {"retired"})
        self.assertEqual(self.transport.requests, [])

    def test_malformed_duplicate_or_oversized_rosters_do_not_replace_good_cache(self):
        for members in (
            [{"id": "u", "displayName": "One"}] * 2,
            [{"id": "", "displayName": "Invalid"}],
            [{"id": f"u{i}", "displayName": "Person"} for i in range(1001)],
            [{"id": f"u{i}", "displayName": "x" * 200} for i in range(800)],
        ):
            app = self.group_app()
            self.seed(app)
            before = deepcopy(app.state["roster_cache"])
            with mock.patch(
                "floorterminal.services.integration.ExternalIntegration.team_members",
                return_value=members,
            ):
                app.delivery.request_roster()
                self.drain(app)
            self.assertEqual(app.state["roster_cache"], before)
            self.assertEqual(app.state["roster_refresh"]["error"], "configuration")
            app.state["roster_refresh"] = {}
            app.save_state()

    def test_worker_failure_is_retryable_and_leaves_cache_intact(self):
        app = self.group_app()
        self.seed(app)
        app.delivery.request_roster()
        with mock.patch(
            "floorterminal.services.roster.threading.Thread.start",
            side_effect=RuntimeError("busy"),
        ):
            self.drain(app)
        self.assertIsNone(app.delivery.active)
        self.assertTrue(app.state["roster_refresh"]["pending"])
        self.assertEqual(
            app.state["roster_cache"]["members"][0]["displayName"], "Saved Engineer"
        )
        self.assertEqual(self.transport.requests, [])

    def test_failed_local_save_does_not_call_directory(self):
        app = self.group_app()
        app.delivery.request_roster()
        before = self.path.read_bytes()
        with mock.patch(
            "floorterminal.storage.state.write_json", side_effect=OSError("full")
        ):
            self.drain(app)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.transport.requests, [])

    def test_successful_read_acknowledgement_retries_disk_only(self):
        app = self.group_app()
        app.delivery.request_roster()
        app.delivery.poll()
        for _ in range(500):
            if not app.delivery.results.empty():
                break
            time.sleep(0.002)
        self.assertFalse(app.delivery.results.empty())
        with mock.patch(
            "floorterminal.storage.state.write_json", side_effect=OSError("full")
        ):
            app.delivery.poll()
        count = len(self.transport.requests)
        app.delivery.ack_retry_at = 0
        self.drain(app)
        self.assertTrue(app.state["roster_cache"])
        self.assertEqual(len(self.transport.requests), count)

    def test_operational_writes_take_priority_over_daily_roster(self):
        app = self.group_app()
        self.seed(app, age=86400)
        self.report(app, "Station 1")
        self.idle(app)
        self.drain(app)
        self.assertNotIn(
            "team.members", [r.operation_id for r in self.transport.requests]
        )
        self.assertTrue(
            any(
                r.operation_id == "response_record.create"
                for r in self.transport.requests
            )
        )

    def test_private_bounded_retry_metadata_is_shared_and_not_in_incident_snapshots(
        self,
    ):
        from floorterminal.storage.incidents import snapshot

        app = self.group_app()
        app.delivery.request_roster()
        sync = app.state["roster_refresh"]
        validate_refresh(sync)
        self.assertNotIn("roster_refresh", snapshot(app.state))
        self.assertNotIn("offline-only-secret", json.dumps(sync))
        for key, value in (
            ("failures", 33),
            ("retry_at", float("inf")),
            ("pending", 1),
            ("error", "private response"),
            ("extra", True),
        ):
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                validate_refresh({**sync, key: value})
        app.state["roster_refresh"] = {**sync, "pending": 1}
        with self.assertRaises(StateSaveError):
            app.save_state()

    def test_interrupted_refresh_resumes_after_restart_with_existing_names(self):
        app = self.group_app()
        self.seed(app)
        app.delivery.request_roster()
        with mock.patch("floorterminal.services.roster.threading.Thread.start"):
            app.delivery.poll()  # prepare is durably committed; emulate power loss
        app.delivery.close()
        restarted = self.group_app()
        self.drain(restarted)
        self.assertEqual(self.transport.requests, [])
        restarted.load_engineers({"kind": "repair"})
        self.assertEqual(restarted.modal["members"][0]["displayName"], "Saved Engineer")
        self.advance_retry(restarted)
        self.drain(restarted)
        self.assertFalse(restarted.state["roster_refresh"]["pending"])

    def test_connector_identity_change_hides_cache_but_token_rotation_does_not(self):
        app = self.group_app()
        self.seed(app)
        definition = app.provider.remote.definition
        definition.data["credentials"]["access_token"] = "rotated-offline-fixture"
        self.assertTrue(app.delivery.cached_roster())
        definition.data["identity"]["id"] = "another-account"
        self.assertEqual(app.delivery.cached_roster(), {})

    def test_update_probation_and_no_directory_never_trigger_refresh(self):
        app = self.group_app()
        self.seed(app, age=86400)
        self.idle(app)
        with mock.patch.object(app, "version_trial_active", return_value=True):
            self.assertIn("verification", app.delivery.request_roster())
            self.drain(app)
        self.assertEqual(self.transport.requests, [])
        app = self.local_app(configured=False)
        self.assertIn("no available", app.delivery.request_roster())
        self.drain(app)
        self.assertEqual(self.transport.requests, [])
