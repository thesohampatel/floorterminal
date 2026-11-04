"""Application request policy: offline tests, never a live HTTP request."""

import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from floorterminal.app import FloorTerminalApp
from floorterminal.core.config import (
    DEFAULT_CONFIG,
    ConfigurationError,
    validate_config,
)
from floorterminal.core.rate_policy import request_budget
from floorterminal.integration import DefinitionError, IntegrationDefinition
from floorterminal.integration.discovery import ConnectorCandidate, test_connector
from floorterminal.integration.runtime import IntegrationClient, IntegrationError

ROOT = Path(__file__).resolve().parents[2]


class BudgetTests(unittest.TestCase):
    def client(self, connector_budget=10, override=None):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["connection"]["requests_per_minute"] = connector_budget
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "connector.json"
        path.write_text(json.dumps(data))
        return IntegrationClient(
            IntegrationDefinition(path), {"api_requests_per_minute": override}
        )

    def test_positive_budgets_have_no_arbitrary_ceiling(self):
        for value in (1, 10, 37, 100, 100000):
            client = self.client(value)
            self.assertEqual(client._budget(), value)
            config = copy.deepcopy(DEFAULT_CONFIG)
            config["api_requests_per_minute"] = value
            validate_config(config)

    def test_local_setting_overrides_connector_and_blank_inherits(self):
        self.assertEqual(self.client(4, 25)._budget(), 25)
        self.assertEqual(self.client(25, 4)._budget(), 4)
        self.assertEqual(self.client(7)._budget(), 7)
        self.assertEqual(request_budget({}, {}), 10)

    def test_invalid_values_fail_closed(self):
        for invalid in (True, False, 0, -1, 2.5, "20", float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(DefinitionError):
                    self.client(invalid)
                config = copy.deepcopy(DEFAULT_CONFIG)
                config["api_requests_per_minute"] = invalid
                with self.assertRaises(ConfigurationError):
                    validate_config(config)
                with self.assertRaises(ValueError):
                    self.client(10, invalid)._budget()

    def test_rolling_window_expires_only_at_sixty_seconds(self):
        client = self.client(2)
        with patch(
            "floorterminal.integration.runtime.time.monotonic", return_value=100
        ):
            client._budget()
            client._budget()
            with self.assertRaises(IntegrationError) as raised:
                client._budget()
            self.assertEqual(raised.exception.code, "RATE_LIMITED")
        with (
            patch(
                "floorterminal.integration.runtime.time.monotonic", return_value=159.99
            ),
            self.assertRaises(IntegrationError),
        ):
            client._budget()
        with patch(
            "floorterminal.integration.runtime.time.monotonic", return_value=160
        ):
            self.assertEqual(client._budget(), 2)
            self.assertEqual(client.app_window_used, 1)

    def test_lowering_budget_preserves_consumed_requests(self):
        client = self.client(20)
        for _ in range(12):
            client._budget()
        client.config["api_requests_per_minute"] = 5
        with self.assertRaises(IntegrationError):
            client._budget()
        self.assertEqual(client.app_window_used, 12)
        client.config["api_requests_per_minute"] = 30
        self.assertEqual(client._budget(), 30)

    def test_concurrent_requests_cannot_exceed_budget(self):
        client = self.client(37)

        def attempt(_):
            try:
                client._budget()
                return True
            except IntegrationError:
                return False

        with ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(attempt, range(200))), 37)
        self.assertEqual(client.app_window_used, 37)

    def test_reloading_or_disabling_connector_cannot_reset_the_terminal_window(self):
        instance = FloorTerminalApp.__new__(FloorTerminalApp)
        instance.config = dict(DEFAULT_CONFIG)
        first, second = self.client(20), self.client(20)
        inventory = SimpleNamespace(
            active=SimpleNamespace(ready=True, definition=first.definition)
        )
        with (
            patch("floorterminal.app.discover_connectors", return_value=inventory),
            patch(
                "floorterminal.app.ExternalIntegration",
                side_effect=(
                    SimpleNamespace(client=first),
                    SimpleNamespace(client=second),
                ),
            ),
        ):
            instance.reload_connector()
            for _ in range(11):
                first._budget()
            inventory.active.ready = False
            instance.reload_connector()
            inventory.active.ready = True
            instance.reload_connector()
        self.assertIs(first.lock, second.lock)
        self.assertIs(first.local_request_times, second.local_request_times)
        self.assertEqual(second.app_window_used, 11)
        # Even a retry from the old client must obey the newly saved policy.
        instance._api_request_window.set_budget(3)
        with self.assertRaises(IntegrationError):
            first._budget()
        with self.assertRaises(IntegrationError):
            second._budget()

    def test_diagnostic_is_blocked_by_an_already_consumed_shared_budget(self):
        client = self.client(1)
        client.definition.data["enabled"] = True
        client.definition.data["connection"]["base_url"] = (
            "https://service.example.test"
        )
        for key in client.definition.data["authentication"]["required_credentials"]:
            client.definition.data["credentials"][key] = "offline-only"
        client._budget()
        client.request_window.set_budget(1)
        client.definition.data["connection"]["requests_per_minute"] = 100
        candidate = ConnectorCandidate(Path("connector.json"), client.definition)
        self.assertTrue(candidate.ready)
        with patch("floorterminal.integration.runtime.UrllibTransport.send") as send:
            result = test_connector(candidate, request_window=client.request_window)
            self.assertFalse(result.success)
            self.assertIn("Application API limit reached", result.message)
            send.assert_not_called()
