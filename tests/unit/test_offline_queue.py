import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from floorterminal.app import FloorTerminalApp
from floorterminal.integration import IntegrationDefinition
from floorterminal.integration.runtime import TransportResponse
from floorterminal.services import ExternalIntegration

ROOT = Path(__file__).resolve().parents[2]


class Logger:
    def __init__(self):
        self.events = []

    def log(self, *args, **kwargs):
        self.events.append((args, kwargs))


class OfflineProvider:
    connected = False
    INFO = SimpleNamespace(supports_response_records=False, supports_team_directory=False)


class OnlineProvider:
    connected = True
    INFO = SimpleNamespace(
        supports_response_records=True,
        supports_team_directory=False,
        supports_asset_status=False,
    )

    def __init__(self):
        self.created = []

    def create_response_record(
        self, title, description, team_id, priority, idempotency_key=None
    ):
        self.created.append((title, description, team_id, priority, idempotency_key))
        return {"id": "record_id-42", "reference": 42}


class OfflineQueueTests(unittest.TestCase):
    def app(self, provider):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.provider = provider
        app.config = {
            "line_name": "Test Line",
            "engineering_team_name": "",
            "response_record_priority": "HIGH",
            "asset_status_tracking": False,
            "downtime_title_template": "DOWN {line} {zones} {time}",
            "downtime_description_template": "Stopped {line} at {timestamp}",
            "engineering_chat_name": "",
            "common_activity_chat_name": "",
        }
        app.state = {
            "status": "RUNNING",
            "events": [],
            "issue_zones": ["Station 1"],
            "failure_selections": {},
        }
        app.logger = Logger()
        app.has_zone_selection = lambda: True
        app.zone_summary = lambda empty="": "Station 1"
        app.selected_zones = lambda: ["Station 1"]
        app.failure_summary = lambda empty="None specified": empty
        app.log_event = lambda *args, **kwargs: None
        app.save_state = lambda: None
        app.sync_asset_status = lambda *args, **kwargs: None
        app.send_activity_chats = lambda *args, **kwargs: None
        return app

    def test_network_outage_records_down_state_before_returning(self):
        app = self.app(OfflineProvider())
        result = app.report_downtime()
        self.assertEqual(app.state["status"], "DOWN")
        self.assertIsNone(app.state["response_record_id"])
        self.assertIsNotNone(app.state["pending_response_record"])
        self.assertIn("recorded locally", result)

    def test_pending_downtime_sync_clears_queue_after_one_create(self):
        provider = OnlineProvider()
        app = self.app(provider)
        app.report_downtime()
        self.assertIsNone(app.state["pending_response_record"])
        self.assertEqual(app.state["response_record_id"], "record_id-42")
        self.assertEqual(len(provider.created), 1)
        self.assertTrue(provider.created[0][4])

    def test_real_connector_contract_drives_app_downtime_model_offline(self):
        """Exercise the application boundary using Connector v1, never the network."""

        class Transport:
            def __init__(self):
                self.requests = []

            def send(self, prepared, timeout):
                self.requests.append(prepared)
                return TransportResponse(
                    201, {}, b'{"id":"RECORD-CONNECTOR-1","reference":81}'
                )

        data = json.loads((ROOT / "connector.example.json").read_text())
        data["enabled"] = True
        data["connection"].update(
            base_url="https://connector.example.test/v1",
            allowed_hosts=["connector.example.test"],
        )
        data["credentials"]["access_token"] = "in-memory-test-token"
        data["capabilities"].update(
            response_record_status=False,
            response_record_comments=False,
            response_record_assignments=False,
            asset_status=False,
            messaging=False,
            team_directory=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            connector_path = Path(directory) / "connector.json"
            connector_path.write_text(json.dumps(data))
            transport = Transport()
            provider = ExternalIntegration(
                {
                    "response_record_type": "REACTIVE",
                    "location_id": "",
                    "asset_id": "",
                },
                transport=transport,
                definition=IntegrationDefinition(connector_path),
            )
            app = self.app(provider)
            result = app.report_downtime()

        self.assertEqual(app.state["response_record_id"], "RECORD-CONNECTOR-1")
        self.assertIsNone(app.state["pending_response_record"])
        self.assertIn("#81", result)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0].method, "POST")
        self.assertTrue(transport.requests[0].headers.get("Idempotency-Key"))

    def test_ambiguous_timeout_retry_reuses_exact_idempotency_key(self):
        class AmbiguousProvider(OnlineProvider):
            def create_response_record(self, *args, **kwargs):
                self.created.append(kwargs["idempotency_key"])
                if len(self.created) == 1:
                    raise TimeoutError("response lost after remote commit")
                return {"id": "record_id-existing", "reference": 42}

        provider = AmbiguousProvider()
        app = self.app(provider)
        app.report_downtime()
        queued = app.state["pending_response_record"]
        self.assertIsNotNone(queued)
        report_id = queued["report_id"]
        app.sync_pending_downtime()
        self.assertEqual(provider.created, [report_id, report_id])
        self.assertIsNone(app.state["pending_response_record"])
        self.assertTrue(
            any(
                args and args[0] == "downtime_sync_retry_after_previous_attempt"
                for args, _kwargs in app.logger.events
            )
        )

    def test_asset_timeout_retry_reuses_exact_idempotency_key(self):
        class AssetProvider:
            INFO = SimpleNamespace(
                supports_asset_status=True, display_name="Test integration"
            )
            connected = True

            def __init__(self):
                self.keys = []
                self.started_at = []

            def set_asset_status(self, *args, **kwargs):
                self.keys.append(kwargs["idempotency_key"])
                self.started_at.append(args[3])
                if len(self.keys) == 1:
                    raise TimeoutError("response lost after remote commit")
                return {"id": "asset-status-existing"}

        provider = AssetProvider()
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.provider = provider
        app.config = {"asset_status_tracking": True, "asset_id": "asset-1"}
        app.state = {
            "asset_status": "ONLINE",
            "asset_status_sync_pending": False,
            "asset_status_sync_target": None,
            "asset_status_sync_key": None,
            "asset_status_sync_attempts": 0,
            "response_record_id": "record_id-1",
        }
        app.logger = Logger()
        app.save_state = lambda: None
        with self.assertRaises(RuntimeError):
            app.sync_asset_status("OFFLINE", "UNPLANNED", "Stopped")
        first_key = app.state["asset_status_sync_key"]
        app.sync_asset_status("OFFLINE", "UNPLANNED", "Stopped")
        self.assertEqual(provider.keys, [first_key, first_key])
        self.assertEqual(provider.started_at[0], provider.started_at[1])
        self.assertFalse(app.state["asset_status_sync_pending"])


class PlannedWorkOnlineProvider:
    connected = True
    INFO = SimpleNamespace(
        supports_response_records=True,
        supports_team_directory=False,
        supports_asset_status=False,
    )

    def __init__(self):
        self.created = []

    def create_response_record(
        self,
        title,
        description,
        team_id,
        priority,
        work_type,
        participant_ids,
        idempotency_key=None,
    ):
        self.created.append(idempotency_key)
        return {"id": "record_id-planned-1", "reference": 7}

    def set_response_record_status(self, *args, **kwargs):
        pass


class PlannedWorkOfflineQueueTests(unittest.TestCase):
    def app(self, provider):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.provider = provider
        app.config = {
            "line_name": "Test Line",
            "planned_work_priority": "MEDIUM",
            "asset_status_tracking": False,
            "planned_work_title_template": "PLANNED {work_label} {line} {zones} {time}",
            "planned_work_description_template": "{work_label} on {line} at {timestamp}",
            "engineering_chat_name": "",
            "common_activity_chat_name": "",
        }
        app.state = {
            "status": "RUNNING",
            "events": [],
            "issue_zones": ["Station 1"],
            "failure_selections": {},
        }
        app.logger = Logger()
        app.has_zone_selection = lambda: True
        app.zone_summary = lambda empty="": "Station 1"
        app.selected_zones = lambda: ["Station 1"]
        app.failure_summary = lambda empty="None specified": empty
        app.log_event = lambda *args, **kwargs: None
        app.save_state = lambda: None
        app.sync_asset_status = lambda *args, **kwargs: None
        app.send_activity_chats = lambda *args, **kwargs: None
        return app

    def members(self):
        return [{"id": "u1", "displayName": "Alex Engineer"}]

    def test_planned_work_sync_clears_queue_after_one_create(self):
        provider = PlannedWorkOnlineProvider()
        app = self.app(provider)
        result = app.start_planned_work(
            "Preventive Maintenance", "PREVENTIVE", "team-1", self.members()
        )
        self.assertIsNone(app.state["pending_planned_work"])
        self.assertEqual(app.state["status"], "ENGINEERING")
        self.assertEqual(app.state["response_record_id"], "record_id-planned-1")
        self.assertEqual(len(provider.created), 1)
        self.assertTrue(provider.created[0])
        self.assertIn("started", result)

    def test_offline_planned_work_is_persisted_without_network_access(self):
        provider = OfflineProvider()
        app = self.app(provider)
        result = app.start_planned_work(
            "Preventive Maintenance", "PREVENTIVE", "team-1", self.members()
        )
        self.assertEqual(app.state["status"], "RUNNING")
        self.assertIsNotNone(app.state["pending_planned_work"])
        self.assertIn("recorded locally", result)

    def test_pending_planned_work_uses_captured_station_context(self):
        provider = PlannedWorkOnlineProvider()
        provider.connected = False
        app = self.app(provider)
        app.failure_summary = lambda empty="None specified": "Station 1: Sensor"
        app.start_planned_work(
            "Modification / Change", "OTHER", "team-1", self.members()
        )
        provider.connected = True
        asset_descriptions = []
        messages = []
        app.sync_asset_status = lambda _status, _kind, description: (
            asset_descriptions.append(description)
        )
        app.send_activity_chats = lambda _targets, message: messages.append(message)
        app.zone_summary = lambda empty="": "Station 99"
        app.failure_summary = lambda empty="None specified": "Station 99: Other"
        app.sync_pending_planned_work()
        self.assertIn("Station 1", asset_descriptions[0])
        self.assertIn("Station 1: Sensor", messages[0])
        self.assertNotIn("Station 99", messages[0])

    def test_ambiguous_timeout_retry_reuses_exact_idempotency_key(self):
        class AmbiguousProvider(PlannedWorkOnlineProvider):
            def create_response_record(self, *args, **kwargs):
                self.created.append(kwargs["idempotency_key"])
                if len(self.created) == 1:
                    raise TimeoutError("response lost after remote commit")
                return {"id": "record_id-planned-existing", "reference": 7}

        provider = AmbiguousProvider()
        app = self.app(provider)
        with self.assertRaises(TimeoutError):
            app.start_planned_work(
                "Modification / Change", "OTHER", "team-1", self.members()
            )
        queued = app.state["pending_planned_work"]
        self.assertIsNotNone(queued)
        report_id = queued["report_id"]
        self.assertEqual(app.state["status"], "RUNNING")
        app.sync_pending_planned_work()
        self.assertEqual(provider.created, [report_id, report_id])
        self.assertIsNone(app.state["pending_planned_work"])
        self.assertEqual(app.state["status"], "ENGINEERING")
        self.assertTrue(
            any(
                args and args[0] == "planned_work_sync_retry_after_previous_attempt"
                for args, _kwargs in app.logger.events
            )
        )


if __name__ == "__main__":
    unittest.main()
