"""Independent group lifecycles through real persistence and offline transport."""

import json
from copy import deepcopy
from unittest import mock

from floorterminal.core.config import (
    DEFAULT_CONFIG,
    ConfigurationError,
    validate_config,
)
from floorterminal.core.topology import scope_for
from floorterminal.storage.incidents import all_incidents
from floorterminal.storage.state import StateSaveError, StateStore, validate_state

from .test_completion_workflow import MEMBERS
from .test_delivery_journal import DurableDeliveryHarness

GROUPS = [
    {
        "id": "cell-a",
        "name": "Assembly",
        "stations": ["Station 1", "Station 2"],
        "stop_scope": "group",
    },
    {
        "id": "cell-b",
        "name": "Inspection",
        "stations": ["Station 3", "Station 4"],
        "stop_scope": "group",
    },
    {
        "id": "cell-c",
        "name": "Packing",
        "stations": ["Station 5", "Station 6"],
        "stop_scope": "group",
    },
]


class GroupHarness(DurableDeliveryHarness):
    def group_app(self, shared_asset=False, configured=True):
        app = self.local_app(configured=configured)
        app.config["station_groups"] = deepcopy(GROUPS)
        self.definition.data["workflow"]["group_targets"] = {
            group["id"]: {
                "asset_id": "shared" if shared_asset else group["id"],
                "location_id": "location-1",
            }
            for group in GROUPS
        }
        return app

    def report(self, app, station, operator=None):
        app.state["issue_zones"] = [station]
        self.action(app, app.report_downtime, operator)
        return app.state["incident_id"]


class StationGroupTests(GroupHarness):
    def test_active_topology_change_fails_closed_without_losing_incident(self):
        app = self.group_app()
        identifier = self.report(app, "Station 1")
        saved = self.path.read_bytes()
        app.validate_active_topology()
        app.config["station_groups"][0]["stop_scope"] = "line"
        with self.assertRaises(ConfigurationError):
            app.validate_active_topology()
        self.assertEqual(app.state["incident_id"], identifier)
        self.assertEqual(self.path.read_bytes(), saved)

    def test_empty_group_name_is_a_settings_validation_error(self):
        from types import SimpleNamespace

        from floorterminal.ui.group_settings import GroupSettingsMixin

        settings = SimpleNamespace(stations=[{"name": "Station 1", "group": ""}])
        with self.assertRaises(ConfigurationError):
            GroupSettingsMixin.configured_groups(settings)

    def test_optional_structured_fields_are_sent_only_when_mapped(self):
        app = self.group_app()
        self.definition.data["workflow"]["fields"].update(
            {
                "asset_ids": "relatedAssets",
                "group_ids": "productionCells",
                "affected_stations": "stoppedStations",
                "incident_id": "terminalEvent",
            }
        )
        app.state["issue_zones"] = ["Station 1", "Station 3"]
        self.action(app, app.report_downtime)
        identifier = app.state["incident_id"]
        self.drain(app)
        create = next(
            r
            for r in self.transport.requests
            if r.operation_id == "response_record.create"
        )
        body = json.loads(create.body)
        self.assertEqual(body["relatedAssets"], ["cell-a", "cell-b"])
        self.assertEqual(body["productionCells"], ["cell-a", "cell-b"])
        self.assertEqual(body["terminalEvent"], identifier)
        self.assertEqual(len(body["stoppedStations"]), 4)
        self.assertNotIn("group_names", body)

    def test_parked_escalation_keeps_focus_and_correct_group_context(self):
        app = self.group_app()
        first = self.report(app, "Station 1")
        self.action(app, app.focus_incident)
        second = self.report(app, "Station 3")
        self.action(app, app.escalate_group, first)
        self.assertEqual(app.state["incident_id"], second)
        notice = next(
            i
            for i in app.state["delivery_outbox"]
            if i["method"] == "send_message" and "RESPONSE OVERDUE" in i["args"][1]
        )
        self.assertEqual(notice["context"]["group_ids"], ["cell-a"])
        self.assertIn("Assembly", notice["args"][1])
        self.assertNotIn("Inspection", notice["args"][1])
        self.assertTrue(app.state["parked_incidents"][first]["escalated_at"])

    def test_one_held_asset_does_not_block_independent_asset_stream(self):
        app = self.group_app()
        self.report(app, "Station 1")
        self.action(app, app.focus_incident)
        self.report(app, "Station 3")
        self.drain(app)
        # Seed a held write for cell A before a new unrelated cell B write.
        from floorterminal.storage.delivery import enqueue

        remote = app.provider.remote
        first = enqueue(
            app.state,
            remote,
            "set_asset_status",
            ["OFFLINE", None, "A", None],
            {},
            context_override={"asset_id": "cell-a"},
        )
        first["phase"] = "attention"
        enqueue(
            app.state,
            remote,
            "set_asset_status",
            ["ONLINE", None, "B", None],
            {},
            context_override={"asset_id": "cell-b"},
        )
        app.save_state()
        before = len(self.transport.requests)
        self.drain(app)
        self.assertTrue(
            any(
                "/assets/cell-b/status" in r.url
                for r in self.transport.requests[before:]
            )
        )
        self.assertEqual(len(app.state["delivery_outbox"]), 1)

    def test_connector_identity_is_frozen_for_lifecycle_updates(self):
        app = self.group_app()
        self.report(app, "Station 1", "")
        original = app.state["incident_scope"]["connector_binding"]
        self.definition.data["identity"]["authenticated_subject_id"] = (
            "different-account"
        )
        self.action(app, app.finish_work)
        self.assertTrue(
            all(i["binding"] == original for i in app.state["delivery_outbox"])
        )
        self.drain(app)
        self.assertEqual(self.transport.requests, [])

    def test_group_stop_does_not_stop_unlinked_stations(self):
        app = self.group_app()
        self.report(app, "Station 1")
        self.assertEqual(
            app.station_statuses(), {"Station 1": "DOWN", "Station 2": "DOWN"}
        )
        self.assertEqual(app.state["issue_zones"], ["Station 1"])
        self.assertEqual(app.state["incident_scope"]["impact"], "group")

    def test_two_concurrent_incidents_restart_and_release_independently(self):
        app = self.group_app()
        a = self.report(app, "Station 1", "Operator")
        started = app.state["started_at"]
        self.action(app, app.focus_incident)
        b = self.report(app, "Station 4")
        self.action(app, app.start_repair, "t1", MEMBERS)
        app = self.group_app()
        self.assertEqual(app.state["incident_id"], b)
        self.assertEqual(len(list(all_incidents(app.state))), 2)
        self.action(app, app.focus_incident, a)
        self.assertEqual(app.state["started_at"], started)
        self.assertEqual(app.state["operator_response"]["name"], "Operator")
        self.action(app, app.finish_work)
        self.assertEqual(
            app.station_statuses(), {"Station 3": "REPAIRING", "Station 4": "REPAIRING"}
        )
        self.assertEqual(len(app.state["parked_incidents"]), 1)
        self.action(app, app.focus_incident, b)
        self.assertEqual(app.state["engineer_names"], ["Alex Engineer"])
        self.action(app, app.finish_work)
        self.assertEqual(list(all_incidents(app.state)), [])
        self.drain(app)
        self.assertEqual(len(self.transport.ids), 2)
        self.assertFalse(app.state["delivery_outbox"])

    def test_group_mapping_reaches_correct_asset_endpoints(self):
        app = self.group_app()
        self.report(app, "Station 3", "")
        self.action(app, app.finish_work)
        self.drain(app)
        urls = [
            r.url for r in self.transport.requests if r.operation_id == "asset.status"
        ]
        self.assertEqual(len(urls), 2)
        self.assertTrue(all("/assets/cell-b/status" in url for url in urls))
        create = next(
            r
            for r in self.transport.requests
            if r.operation_id == "response_record.create"
        )
        body = json.loads(create.body)
        self.assertEqual(body["assetId"], "cell-b")
        self.assertIn("Inspection", body["description"])

    def test_missing_mapping_never_targets_aggregate_asset(self):
        app = self.group_app()
        self.definition.data["workflow"]["group_targets"] = {}
        self.report(app, "Station 3", "")
        self.action(app, app.finish_work)
        self.drain(app)
        self.assertFalse(
            [r for r in self.transport.requests if r.operation_id == "asset.status"]
        )
        create = next(
            r
            for r in self.transport.requests
            if r.operation_id == "response_record.create"
        )
        self.assertNotIn("assetId", json.loads(create.body))

    def test_shared_asset_stays_offline_until_last_group_releases(self):
        app = self.group_app(shared_asset=True)
        a = self.report(app, "Station 1", "")
        self.action(app, app.focus_incident)
        self.report(app, "Station 3", "")
        self.action(app, app.focus_incident, a)
        self.action(app, app.finish_work)
        assets = [
            i for i in app.state["delivery_outbox"] if i["method"] == "set_asset_status"
        ]
        self.assertTrue(assets)
        self.assertEqual(len(assets), 1)
        self.assertTrue(all(i["args"][0] == "OFFLINE" for i in assets))
        b = next(iter(app.state["parked_incidents"]))
        self.action(app, app.focus_incident, b)
        self.action(app, app.finish_work)
        assets = [
            i for i in app.state["delivery_outbox"] if i["method"] == "set_asset_status"
        ]
        self.assertEqual(sum(i["args"][0] == "ONLINE" for i in assets), 1)

    def test_whole_line_and_group_stop_propagation(self):
        app = self.group_app()
        app.config["station_groups"][0]["stop_scope"] = "line"
        self.report(app, "Station 1")
        self.assertEqual(len(app.station_statuses()), 6)
        self.assertEqual(app.state["issue_zones"], ["Station 1"])
        self.assertEqual(len(app.state["incident_scope"]["routes"]), 4)

    def test_whole_line_cannot_overlap_existing_incident(self):
        app = self.group_app()
        first = self.report(app, "Station 1")
        self.action(app, app.focus_incident)
        app.state["issue_zones"] = ["ENTIRE LINE"]
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            self.action(app, app.report_downtime)
        self.assertIn(first, app.state["parked_incidents"])
        self.assertEqual(len(list(all_incidents(app.state))), 1)

    def test_multiple_selected_groups_one_incident_and_record(self):
        app = self.group_app()
        app.state["issue_zones"] = ["Station 1", "Station 4"]
        self.action(app, app.report_downtime, "")
        self.assertEqual(len(app.station_statuses()), 4)
        create = next(
            i
            for i in app.state["delivery_outbox"]
            if i["method"] == "create_response_record"
        )
        self.assertEqual(create["context"]["asset_ids"], ["cell-a", "cell-b"])
        self.assertEqual(create["context"]["asset_id"], "")
        self.action(app, app.finish_work)
        self.drain(app)
        self.assertEqual(len(self.transport.ids), 1)

    def test_immutable_targets_survive_configuration_edits(self):
        app = self.group_app()
        self.report(app, "Station 1", "")
        self.definition.data["workflow"]["group_targets"]["cell-a"]["asset_id"] = (
            "different"
        )
        app.config["asset_id"] = "different-line"
        self.action(app, app.finish_work)
        self.assertTrue(
            all(
                i["context"]["asset_id"] == "cell-a"
                for i in app.state["delivery_outbox"]
                if i["method"] == "set_asset_status"
            )
        )

    def test_focus_failure_rolls_back_both_incidents(self):
        app = self.group_app()
        first = self.report(app, "Station 1")
        self.action(app, app.focus_incident)
        second = self.report(app, "Station 3")
        with (
            mock.patch(
                "floorterminal.storage.state.write_json",
                side_effect=OSError("disk full"),
            ),
            self.assertRaises(StateSaveError),
        ):
            self.action(app, app.focus_incident, first)
        self.assertEqual(app.state["incident_id"], second)
        self.assertIn(first, app.state["parked_incidents"])

    def test_offline_planned_and_operator_handover_are_independent(self):
        app = self.group_app(configured=False)
        a = self.report(app, "Station 1", "")
        self.action(app, app.focus_incident)
        app.state["issue_zones"] = ["Station 5"]
        self.action(app, app.start_planned_work, "Preventive", "PREVENTIVE", None, [])
        self.assertEqual(app.state["status"], "ENGINEERING")
        self.action(app, app.focus_incident, a)
        self.action(app, app.request_engineering_handover)
        self.action(app, app.start_repair, None, [])
        self.assertEqual(app.state["status"], "REPAIRING")
        self.assertEqual(len(app.state["parked_incidents"]), 1)
        self.assertEqual(len(self.transport.requests), 0)

    def test_state_rejects_overlapping_parked_incident(self):
        app = self.group_app()
        a = self.report(app, "Station 1")
        self.action(app, app.focus_incident)
        self.report(app, "Station 3")
        state = deepcopy(app.state)
        state["parked_incidents"][a]["incident_scope"] = deepcopy(
            state["incident_scope"]
        )
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_state(state)

    def test_legacy_continuous_line_still_stops_all_stations(self):
        scope = scope_for(DEFAULT_CONFIG, ["Station 1"])
        self.assertEqual(scope["affected_stations"], DEFAULT_CONFIG["zones"])
        self.assertEqual(scope["impact"], "line")

    def test_config_rejects_missing_duplicate_and_unknown_stations(self):
        for change in (
            lambda g: g.pop(),
            lambda g: g[0]["stations"].append("Station 3"),
            lambda g: g[0]["stations"].append("Missing"),
        ):
            config = deepcopy(DEFAULT_CONFIG)
            config["station_groups"] = deepcopy(GROUPS)
            change(config["station_groups"])
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_parked_incident_survives_restart_without_focused_incident(self):
        app = self.group_app()
        first = self.report(app, "Station 1")
        self.action(app, app.focus_incident)
        restored = StateStore(self.path).data
        self.assertEqual(restored["status"], "RUNNING")
        self.assertEqual(restored["parked_incidents"][first]["status"], "DOWN")
