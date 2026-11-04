"""Deterministic v1.2.1 layout and message-only shortcut regressions."""

import itertools
import string
import unittest
from copy import deepcopy

from floorterminal.core.config import DEFAULT_CONFIG, ConfigurationError, prepare_config
from floorterminal.core.support import support_buttons, validate_support_buttons
from floorterminal.ui.failure_layout import reason_page
from floorterminal.ui.keyboard_layout import keyboard_page
from floorterminal.ui.layout import Viewport, header_regions, text_pages

from .test_completion_workflow import SupportCallTests, rate_limited


class RefinedLayoutTests(unittest.TestCase):
    def test_information_pages_keep_heading_with_content_without_losing_text(self):
        lines = [
            ("STATUS", True),
            ("First detail", False),
            ("", False),
            ("HELP", True),
            ("Next detail", False),
            ("More detail", False),
            ("", False),
            ("SOURCE", True),
            ("Release source", False),
        ]
        for capacity in range(1, 12):
            pages = text_pages(lines, capacity)
            self.assertEqual(
                [item for page in pages for item in page if item[0]],
                [item for item in lines if item[0]],
            )
            for page in pages:
                self.assertLessEqual(len(page), capacity)
                if capacity > 1:
                    self.assertFalse(page[-1][1])

    def test_clock_has_its_own_space_at_all_supported_widths(self):
        for width in range(320, 2200, 13):
            controls, clock, title_right, feedback_right = header_regions(width)
            self.assertLess(title_right, controls[0])
            self.assertLessEqual(clock[2], width)
            self.assertGreaterEqual(clock[2] - clock[0], 124)
            self.assertTrue(clock[2] <= controls[0] or clock[1] >= controls[3])
            if clock[1] >= 62:
                self.assertLess(feedback_right, clock[0])
            else:
                self.assertLess(title_right, clock[0])

    def test_keyboard_reaches_every_character_with_uniform_touch_keys(self):
        for width, height in (
            (320, 400),
            (360, 640),
            (800, 480),
            (480, 800),
            (1920, 1200),
        ):
            view = Viewport.from_pixels(width, height)
            box = (20, 128, min(1100, view.width - 8) - 12, view.height - 130)
            for symbols in (False, True):
                seen = []
                pages = keyboard_page(box, symbols=symbols)[2]
                for page in range(pages):
                    keys, actual, total, navigation = keyboard_page(
                        box, page, symbols=symbols
                    )
                    self.assertEqual((actual, total), (page, pages))
                    seen.extend(char for char, _rect in keys)
                    dimensions = set()
                    for _char, (a, b, c, d) in keys:
                        self.assertGreaterEqual(c - a, 44)
                        self.assertGreaterEqual(d - b, 44)
                        self.assertLessEqual(d, navigation[1] if navigation else box[3])
                        dimensions.add((round(c - a, 3), round(d - b, 3)))
                    self.assertEqual(len(dimensions), 1)
                    for (_, one), (_, two) in itertools.combinations(keys, 2):
                        self.assertTrue(
                            one[2] <= two[0]
                            or two[2] <= one[0]
                            or one[3] <= two[1]
                            or two[3] <= one[1]
                        )
                expected = (
                    string.punctuation
                    if symbols
                    else string.digits + string.ascii_uppercase
                )
                self.assertEqual(set(seen), set(expected))
                self.assertEqual(len(seen), len(expected))

    def test_failure_tiles_are_equal_in_every_row_even_the_last(self):
        for width in (280, 440, 760, 1060):
            for count in range(30):
                slots = reason_page((20, 80, width + 20, 350), range(count), 0)[1]
                self.assertEqual(
                    len({(round(c - a, 3), round(d - b, 3)) for a, b, c, d in slots}), 1
                )


class SupportConfigurationTests(unittest.TestCase):
    def test_legacy_destinations_are_resolved_without_mutation(self):
        config = deepcopy(DEFAULT_CONFIG)
        config["quality_chat_name"] = "Inspection help"
        self.assertEqual(support_buttons(config)[1]["destination"], "Inspection help")
        self.assertIsNone(config["support_buttons"])
        config["quality_chat_name"] = None
        self.assertEqual(support_buttons(config)[1]["destination"], "")

    def test_invalid_configuration_is_rejected(self):
        for value in (
            [],
            {},
            "bad",
            [None] * 3,
            [{"enabled": 1, "label": "A", "destination": "B"}] * 3,
            [{"enabled": True, "label": "\n", "destination": "B"}] * 3,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_support_buttons(value)

    def test_config_round_trip_keeps_custom_shortcuts_and_legacy_routing(self):
        config = deepcopy(DEFAULT_CONFIG)
        config["support_buttons"] = [
            {"enabled": True, "label": name, "destination": name + " chat"}
            for name in (
                "Maintenance team",
                "Quality technician",
                "Production supervisor",
            )
        ]
        restored = prepare_config(config)
        self.assertEqual(restored["support_buttons"], config["support_buttons"])
        self.assertEqual(
            restored["engineering_team_name"], config["engineering_team_name"]
        )
        config["support_buttons"][0]["destination"] = "bad\nname"
        with self.assertRaises(ConfigurationError):
            prepare_config(config)


class ConfigurableSupportWorkflowTests(SupportCallTests):
    def test_custom_label_and_destination_are_used_without_creating_incident(self):
        app = self.app()
        app.config["support_buttons"] = [
            {
                "label": "Maintenance team",
                "destination": "Maint helpers",
                "enabled": True,
            },
            {
                "label": "Quality technician",
                "destination": "Inspector",
                "enabled": True,
            },
            {
                "label": "Production supervisor",
                "destination": "Supervisor",
                "enabled": False,
            },
        ]
        before = deepcopy(app.state)
        result = self.run_call(app)
        target, content = self.provider.calls_to("message")[-1]
        self.assertEqual(target, "Maint helpers")
        self.assertIn("Maintenance team", content)
        self.assertIn("Maintenance team", result)
        self.assertEqual(app.state["status"], before["status"])
        self.assertFalse(self.provider.calls_to("create"))
        previous = len(self.provider.calls)
        app.call_team("Production")
        self.assertEqual(len(self.provider.calls), previous)

    def test_pending_custom_help_keeps_original_destination_after_edit(self):
        app = self.app()
        app.config["support_buttons"] = [
            {"label": name, "destination": name, "enabled": True}
            for name in ("Maintenance team", "Inspector", "Supervisor")
        ]
        self.provider.fail("message", rate_limited())
        self.run_call(app)
        app.config["support_buttons"][0]["destination"] = "Changed later"
        self.provider.failures.clear()
        app.flush_messages(force=True)
        self.assertEqual(self.provider.calls_to("message")[-1][0], "Maintenance team")
