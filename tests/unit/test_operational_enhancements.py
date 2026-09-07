import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from floorterminal.app import FloorTerminalApp
from floorterminal.core.config import (
    COLORBLIND_SAFE_COLORS,
    DEFAULT_CONFIG,
    validate_config,
)
from floorterminal.i18n import load_translator
from floorterminal.integration import (
    IntegrationDefinition,
    basic_diagnostic_connector,
    write_connector,
)
from floorterminal.storage.state import (
    INITIAL_STATE,
    StateIntegrityError,
    validate_state,
)
from floorterminal.ui.settings import SettingsWindow


class Logger:
    def __init__(self):
        self.events = []

    def log(self, event, *args, **details):
        self.events.append((event, details))


class OperationalEnhancementTests(unittest.TestCase):
    def test_retry_deadline_uses_monotonic_time_after_wall_clock_rollback(self):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.retry_deadlines = {}
        pending = {"report_id": "report-1", "last_attempt_at": 950.0}
        with (
            mock.patch("floorterminal.app.time.time", return_value=1_000.0),
            mock.patch("floorterminal.app.time.monotonic", return_value=10.0),
        ):
            self.assertFalse(app.pending_retry_due(pending))
        with (
            mock.patch("floorterminal.app.time.time", return_value=100.0),
            mock.patch("floorterminal.app.time.monotonic", return_value=20.0),
        ):
            self.assertTrue(app.pending_retry_due(pending))

    def app(self):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.state = {
            **INITIAL_STATE,
            "issue_zones": ["Station 1"],
            "failure_selections": {},
            "failure_notes": {},
        }
        app.config = {
            "line_name": "Line 1",
            "escalation_chat_name": "Supervisors",
            "micro_stop_threshold_minutes": 5,
        }
        app.logger = Logger()
        app.modal = None
        app.RED, app.BLUE, app.GREEN, app.ORANGE = "red", "blue", "green", "orange"
        app.save_state = lambda: None
        app.notify = lambda *args, **kwargs: None
        app.selected_zones = lambda: ["Station 1"]
        app.zone_summary = lambda empty="Not specified": "Station 1"
        app.failure_summary = FloorTerminalApp.failure_summary.__get__(app)
        app.log_event = lambda *args, **kwargs: None
        return app

    def test_reporting_requires_deliberate_confirmation(self):
        app = self.app()
        app.state["status"] = "RUNNING"
        app.primary_action()
        self.assertEqual(app.modal["kind"], "confirm_downtime")
        self.assertIn("LINE DOWNTIME", app.modal["title"])

    def test_other_failure_note_is_optional_and_in_summary(self):
        app = self.app()
        app.modal = {
            "kind": "failures",
            "station": "Station 1",
            "options": ["Mechanical", "Others"],
            "selected": {"Others"},
        }
        app.save_failure_selection()
        self.assertEqual(app.modal["kind"], "text_input")
        app.modal["value"] = "Intermittent unusual vibration"
        app.submit_text_input()
        self.assertIn("Others — Intermittent unusual vibration", app.failure_summary())

    def test_escalation_is_persisted_and_audited(self):
        app = self.app()
        app.state.update(status="DOWN", started_at=1.0, escalated_at=None)
        app.provider = SimpleNamespace(INFO=SimpleNamespace(supports_messaging=True))
        sent = []
        app.send_activity_chats = lambda keys, message: sent.append((keys, message))
        app.escalate_downtime()
        self.assertTrue(app.state["escalated_at"])
        self.assertEqual(sent[0][0], ["escalation_chat_name"])
        self.assertTrue(
            any(event == "downtime_escalated" for event, _ in app.logger.events)
        )

    def test_micro_stop_classification_uses_configured_threshold(self):
        app = self.app()
        self.assertEqual(app.classify_downtime(300), "MICRO-STOP")
        self.assertEqual(app.classify_downtime(301), "DOWNTIME EVENT")

    def test_engineer_filter_preserves_full_roster_and_selection(self):
        app = self.app()
        roster = [
            {"id": "1", "displayName": "Alex Morgan"},
            {"id": "2", "displayName": "Priya Shah"},
        ]
        previous = {
            "kind": "engineers",
            "members": roster,
            "full_members": roster,
            "selected": {"2"},
        }
        app.open_text_input(
            "engineer_search", "Search", "Name", "priya", return_modal=previous
        )
        app.submit_text_input()
        self.assertEqual([item["id"] for item in app.modal["members"]], ["2"])
        self.assertEqual(app.modal["selected"], {"2"})

    def test_engineer_departure_closes_history_for_opaque_string_id(self):
        app = self.app()
        app.state.update(
            status="REPAIRING",
            response_record_id="record_id-1",
            engineer_ids=["user-alpha", "user-beta"],
            engineer_names=["Alex", "Blair"],
            engineer_history=[
                {
                    "id": "user-alpha",
                    "name": "Alex",
                    "joined_at": "2026-01-01T00:00:00+00:00",
                    "left_at": None,
                },
                {
                    "id": "user-beta",
                    "name": "Blair",
                    "joined_at": "2026-01-01T00:00:00+00:00",
                    "left_at": None,
                },
            ],
        )
        app.provider = SimpleNamespace(
            assign_participants=lambda *args: None,
            add_response_record_comment=lambda *args: None,
        )
        app.project_profile = SimpleNamespace(product_name="Test Terminal")
        app.config.update(engineering_chat_name="", common_activity_chat_name="")
        app.send_activity_chats = lambda *args: None
        app.update_active_crew("team-1", [{"id": "user-beta", "displayName": "Blair"}])
        departed = app.state["engineer_history"][0]
        self.assertIsNotNone(departed["left_at"])
        self.assertIsNone(app.state["engineer_history"][1]["left_at"])

    def test_repair_timer_starts_locally_when_external_status_update_fails(self):
        app = self.app()
        app.state.update(status="DOWN", response_record_id="record-1")

        def unavailable(*_args):
            raise RuntimeError("temporary outage")

        app.provider = SimpleNamespace(
            connected=True,
            INFO=SimpleNamespace(supports_response_record_status=True),
            set_response_record_status=unavailable,
        )
        app.play_sound = lambda *_args: None
        result = app.change_status("IN_PROGRESS", "REPAIRING")
        self.assertEqual(app.state["status"], "REPAIRING")
        self.assertIsNotNone(app.state["repair_at"])
        self.assertEqual(app.state["pending_response_status"]["record_id"], "record-1")
        self.assertIn("external status pending", result)

    def test_locale_has_english_fallback(self):
        translate = load_translator("missing-locale")
        self.assertEqual(translate("report_problem"), "REPORT A PROBLEM")
        self.assertEqual(translate("unknown_key"), "unknown_key")

    def test_settings_language_uses_the_stable_configuration_key(self):
        settings = SettingsWindow.__new__(SettingsWindow)
        logger = Logger()
        app = SimpleNamespace(
            config={"zones": []},
            sound=SimpleNamespace(update=mock.Mock()),
            update_service=None,
            reload_connector=mock.Mock(),
            root=SimpleNamespace(configure=mock.Mock()),
            canvas=SimpleNamespace(configure=mock.Mock()),
            selected_zones=list,
            state={"failure_selections": {}, "failure_notes": {}},
            save_state=mock.Mock(),
            provider=SimpleNamespace(
                logger=None,
                INFO=SimpleNamespace(display_name="Offline integration"),
                connected=False,
            ),
            authorized_admin_identity="Test administrator",
        )
        settings.app = app
        candidate = {
            "ui_language": "future-locale",
            "zones": [],
            "ui_colors": dict(DEFAULT_CONFIG["ui_colors"]),
        }
        translator = mock.Mock()
        with (
            mock.patch(
                "floorterminal.ui.settings.load_translator",
                return_value=translator,
            ) as load,
            mock.patch(
                "floorterminal.ui.settings.ActivityLogger",
                return_value=logger,
            ),
        ):
            settings._apply(candidate)
        load.assert_called_once_with("future-locale")
        self.assertIs(app.t, translator)

    def test_basic_connector_wizard_template_is_valid_and_diagnostic_only(self):
        data = basic_diagnostic_connector(
            "Plant System",
            "https://service.example.test/api",
            "offline-secret",
            "/health",
            "Bearer token",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plant.connector.json"
            write_connector(data, path)
            definition = IntegrationDefinition(path)
            self.assertTrue(definition.enabled)
            self.assertFalse(any(definition.capabilities.values()))
            self.assertEqual(
                definition.data["diagnostics"]["test_operation"], "diagnostic.get"
            )

    def test_new_config_and_state_fields_are_validated(self):
        config = {
            **DEFAULT_CONFIG,
            "ui_colors": dict(COLORBLIND_SAFE_COLORS),
            "ui_color_preset": "colorblind_safe",
        }
        validate_config(config)
        invalid = {**INITIAL_STATE, "failure_notes": {"Station 1": "x" * 241}}
        with self.assertRaises(StateIntegrityError):
            validate_state(invalid)


if __name__ == "__main__":
    unittest.main()
