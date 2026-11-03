"""Variable catalogues preserve touch geometry, station intent and persistence."""

import json
import unittest
from copy import deepcopy
from types import SimpleNamespace

from floorterminal.core.config import (
    DEFAULT_CONFIG,
    ConfigurationError,
    validate_config,
)
from floorterminal.storage.state import StateStore
from floorterminal.ui.failure_layout import reason_page
from floorterminal.ui.failure_settings import FailureSettingsMixin
from floorterminal.ui.layout import Viewport
from floorterminal.update.compatibility import CompatibilityError, inspect_runtime

from .test_station_groups import GroupHarness


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FailureCatalogueTests(unittest.TestCase):
    def test_others_only_and_large_distinct_station_catalogues(self):
        config = deepcopy(DEFAULT_CONFIG)
        config["station_failure_types"]["Station 1"] = []
        config["station_failure_types"]["Station 2"] = [
            f"Fault {i}" for i in range(10000)
        ]
        validate_config(config)

    def test_invalid_catalogues_fail_without_coercing_labels(self):
        for values in (
            None,
            "Reason",
            [1],
            [""],
            ["Others"],
            ["A", " a "],
            ["bad\nline"],
        ):
            config = deepcopy(DEFAULT_CONFIG)
            config["station_failure_types"]["Station 1"] = values
            with self.subTest(values=values), self.assertRaises(ConfigurationError):
                validate_config(config)

    def test_missing_station_catalogue_still_requires_explicit_setup(self):
        config = deepcopy(DEFAULT_CONFIG)
        del config["station_failure_types"]["Station 1"]
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_paged_geometry_keeps_touch_targets_and_reaches_every_reason(self):
        for width, height in (
            (320, 400),
            (800, 480),
            (480, 800),
            (1024, 600),
            (1920, 1200),
            (3840, 2160),
        ):
            view = Viewport.from_pixels(width, height)
            box = (20, 80, min(1100, view.width - 8) - 12, view.height - 130)
            for count in (0, 1, 4, 8, 53, 1000):
                matches = range(count)
                seen = []
                pages = reason_page(box, matches, 0)[3]
                for page in range(pages):
                    visible, slots, actual, total, controls = reason_page(
                        box, matches, page
                    )
                    self.assertEqual((actual, total), (page, pages))
                    self.assertEqual(
                        len(slots), len(visible) + 1
                    )  # Others always visible.
                    self.assertLessEqual(
                        len(slots), 64
                    )  # bounded render work at all densities
                    seen.extend(visible)
                    for i, (a, b, c, d) in enumerate(slots):
                        self.assertGreaterEqual(c - a, 44)
                        self.assertGreaterEqual(d - b, 44)
                        self.assertGreaterEqual(b, box[1] + 28)
                        self.assertLessEqual(d, box[3] + 0.01)
                        for x, y, z, w in [*slots[i + 1 :], controls]:
                            self.assertFalse(a < z and x < c and b < w and y < d)
                self.assertEqual(seen, list(matches))
                self.assertEqual(reason_page(box, matches, 10**6)[2], pages - 1)

    def editor(self, values):
        editor = FailureSettingsMixin()
        editor.failure_vars = [Value() for _ in range(4)]
        editor.failure_numbers = [Value() for _ in range(4)]
        editor.failure_count = Value()
        editor.failure_entries = [
            SimpleNamespace(focus_set=lambda: None) for _ in range(4)
        ]
        editor._load_failures(values)
        return editor

    def test_editor_pages_preserve_off_page_edits_and_have_no_count_limit(self):
        values = [f"Fault {i}" for i in range(101)]
        editor = self.editor(values)
        editor.failure_vars[0].set("Edited first")
        editor.change_failure_page(25)
        self.assertEqual(editor.failure_vars[0].get(), "Fault 100")
        editor.failure_vars[0].set("Edited last")
        editor.change_failure_page(-25)
        self.assertEqual(editor.failure_vars[0].get(), "Edited first")
        collected = editor._collect_failures()
        self.assertEqual(
            (collected[0], collected[-1], len(collected)),
            ("Edited first", "Edited last", 101),
        )

    def test_add_remove_and_others_only_do_not_repopulate_defaults(self):
        editor = self.editor(["A", "B", "C", "D"])
        editor.add_failure()
        self.assertEqual(editor._failure_page, 1)
        editor.failure_vars[0].set("E")
        self.assertEqual(editor._collect_failures(), ["A", "B", "C", "D", "E"])
        editor.remove_failure(0)
        self.assertEqual(editor._failure_page, 0)
        for _ in range(4):
            editor.remove_failure(0)
        self.assertEqual(editor._collect_failures(), [])
        for _ in range(30):
            editor.add_failure()
        self.assertEqual(len(editor._failure_draft), 1)


class FailureWorkflowTests(GroupHarness):
    def test_others_only_remains_optional_and_no_dummy_reasons_return(self):
        defaults = deepcopy(DEFAULT_CONFIG)
        app = self.group_app()
        app.config["station_failure_types"]["Station 1"] = []
        app.select_issue_zone("0")
        self.assertEqual(app.modal["options"], ["Others"])
        self.assertEqual(app.modal["selected"], set())
        app.report_from_failure_picker(self_fix=True)
        self.assertEqual(app.state["failure_selections"], {})
        self.assertTrue(app.operator_resolving())
        self.assertEqual(DEFAULT_CONFIG, defaults)

    def test_large_multi_station_selections_survive_restart_and_external_mapping(self):
        app = self.group_app()
        reasons = [f"Failure {i}" for i in range(100)]
        app.config["station_failure_types"]["Station 1"] = reasons
        app.config["station_failure_types"]["Station 3"] = []
        self.definition.data["workflow"]["fields"]["failure_details"] = (
            "context.failures"
        )
        app.select_issue_zone("0")
        self.assertEqual(app.modal["options"], reasons + ["Others"])
        app.modal["selected"] = set(reasons)
        app.save_failure_selection()
        app.select_issue_zone("2")
        app.modal["selected"] = {"Others"}
        app.report_from_failure_picker(self_fix=True)
        saved = StateStore(self.path).data
        self.assertEqual(
            saved["failure_selections"], {"Station 1": reasons, "Station 3": ["Others"]}
        )
        self.assertEqual(
            saved["incident_scope"]["affected_stations"],
            ["Station 1", "Station 2", "Station 3", "Station 4"],
        )
        for entry in saved["delivery_outbox"]:
            self.assertEqual(
                "failure_details" in entry["context"],
                entry["method"] == "create_response_record",
            )
        self.drain(app)
        create = next(
            r
            for r in self.transport.requests
            if r.operation_id == "response_record.create"
        )
        details = json.loads(create.body)["context"]["failures"]
        self.assertEqual(
            details,
            [
                {"station": "Station 1", "reasons": reasons, "note": ""},
                {"station": "Station 3", "reasons": ["Others"], "note": ""},
            ],
        )

    def test_search_preserves_selection_and_keeps_all_matches_reachable(self):
        app = self.group_app()
        app.config["station_failure_types"]["Station 1"] = [
            f"Reason {i}" for i in range(35)
        ]
        app.select_issue_zone("0")
        previous = app.modal
        previous["selected"] = {"Reason 34"}
        app.open_text_input(
            "failure_search", "Find", "Filter", "Reason 1", return_modal=previous
        )
        app.submit_text_input()
        self.assertEqual(app.modal["selected"], {"Reason 34"})
        self.assertEqual(len(app.modal["matches"]), 11)
        app.open_text_input(
            "failure_search", "Find", "Filter", "", return_modal=previous
        )
        app.submit_text_input()
        self.assertEqual(app.modal["matches"], list(range(35)))
        self.assertEqual(app.modal["page"], 0)

    def test_old_reader_cannot_accept_new_catalogue_sizes(self):
        config = deepcopy(DEFAULT_CONFIG)
        for reasons in ([], [str(i) for i in range(9)]):
            config["station_failure_types"]["Station 1"] = reasons
            (self.path.parent / "config.json").write_text(json.dumps(config))
            with self.assertRaisesRegex(CompatibilityError, "failure reasons"):
                inspect_runtime(self.path.parent, "1.1.0")
