import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from floorterminal.integration.discovery import (
    discover_connectors,
    select_connector,
)
from floorterminal.integration.discovery import (
    test_connector as run_connector_test,
)
from floorterminal.integration.runtime import TransportResponse

ROOT = Path(__file__).resolve().parents[2]


class ConnectorDiscoveryTests(unittest.TestCase):
    class FakeTransport:
        def __init__(self):
            self.requests = []

        def send(self, request, timeout):
            self.requests.append((request, timeout))
            return TransportResponse(200, {}, b'{"users": []}')

    def connector(self, root, name, display_name):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["identity"]["display_name"] = display_name
        data["enabled"] = True
        data["connection"]["base_url"] = "https://service.example.test/v1"
        data["connection"]["allowed_hosts"] = ["service.example.test"]
        data["credentials"]["access_token"] = "offline-secret"
        path = root / name
        path.write_text(json.dumps(data))
        return path

    def test_one_ready_connector_is_automatically_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.connector(root, "plant_connector.json", "Plant System")
            inventory = discover_connectors(root)
            self.assertEqual(len(inventory.candidates), 1)
            self.assertEqual(inventory.active.path.name, "plant_connector.json")
            self.assertTrue(inventory.active.ready)

    def test_disabled_or_incomplete_connector_does_not_enable_kiosk_actions(self):
        from floorterminal.app import FloorTerminalApp
        from floorterminal.services.provider import NoIntegrationProvider

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for enabled, token in ((False, "offline-secret"), (True, "")):
                with self.subTest(enabled=enabled, credential_present=bool(token)):
                    path = self.connector(root, "connector.json", "Draft System")
                    data = json.loads(path.read_text())
                    data["enabled"] = enabled
                    data["credentials"]["access_token"] = token
                    path.write_text(json.dumps(data))
                    inventory = discover_connectors(root)
                    self.assertEqual(len(inventory.candidates), 1)
                    self.assertFalse(inventory.active.ready)
                    terminal = SimpleNamespace(config={}, logger=None)
                    with patch("floorterminal.app.discover_connectors", return_value=inventory):
                        provider = FloorTerminalApp.reload_connector(terminal)
                    self.assertIsInstance(provider, NoIntegrationProvider)
                    self.assertFalse(provider.INFO.supports_messaging)
                    self.assertFalse(provider.INFO.supports_response_records)
                    self.assertIs(terminal.connector_inventory, inventory)

    def test_multiple_connectors_can_be_selected_without_editing_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.connector(root, "a.connector.json", "System A")
            self.connector(root, "b_connector.json", "System B")
            selection = root / ".active_connector"
            inventory = select_connector("b_connector.json", root, selection)
            self.assertEqual(inventory.active.path.name, "b_connector.json")
            self.assertEqual(selection.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(root.glob("*.tmp")), [])
            self.assertEqual(
                discover_connectors(root, selection).active.path.name,
                "b_connector.json",
            )

    def test_invalid_file_is_reported_without_hiding_valid_connector(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.connector(root, "good.connector.json", "Good System")
            (root / "bad_connector.json").write_text("{broken")
            inventory = discover_connectors(root)
            self.assertEqual(len(inventory.candidates), 2)
            self.assertEqual(inventory.active.path.name, "good.connector.json")
            broken = next(item for item in inventory.candidates if item.error)
            self.assertEqual(broken.status, "ERROR")

    def test_explicit_diagnostic_uses_exactly_one_read_only_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.connector(root, "plant_connector.json", "Plant System")
            candidate = discover_connectors(root).active
            transport = self.FakeTransport()
            result = run_connector_test(candidate, transport=transport)
            self.assertTrue(result.success)
            self.assertEqual(result.operation_id, "user.list")
            self.assertEqual(len(transport.requests), 1)
            self.assertEqual(transport.requests[0][0].method, "GET")
            self.assertIn("limit=1", transport.requests[0][0].url)

    def test_diagnostic_without_safe_get_remains_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.connector(root, "plant_connector.json", "Plant System")
            data = json.loads(path.read_text())
            data.pop("diagnostics", None)
            data["workflow"]["operations"] = {
                key: value
                for key, value in data["workflow"]["operations"].items()
                if key not in {"list_users", "list_teams", "list_conversations"}
            }
            for name in ("team_directory", "messaging"):
                data["capabilities"][name] = False
            path.write_text(json.dumps(data))
            candidate = discover_connectors(root).active
            transport = self.FakeTransport()
            result = run_connector_test(candidate, transport=transport)
            self.assertTrue(result.success)
            self.assertIn("no safe GET", result.message)
            self.assertEqual(transport.requests, [])


if __name__ == "__main__":
    unittest.main()
