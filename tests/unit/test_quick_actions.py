"""Reduced navigation must not weaken persistence, scope or crew semantics."""

from copy import deepcopy
from unittest import mock

from floorterminal.storage.state import StateSaveError, StateStore

from .test_station_groups import GroupHarness

MEMBERS = [
    {"id": "one", "displayName": "Engineer One"},
    {"id": "two", "displayName": "Engineer Two"},
]


class QuickActionTests(GroupHarness):
    def picker(self, app, kind="repair"):
        app.show_engineer_picker(
            {"members": deepcopy(MEMBERS), "team_id": "t1", "context": {"kind": kind}}
        )

    def selected(self):
        app = self.group_app()
        app.select_issue_zone("0")
        return app

    def test_direct_report_commits_draft_reasons_and_scope_together(self):
        app = self.selected()
        app.modal["selected"] = {"Mechanical"}
        app.report_from_failure_picker()
        self.assertIsNone(app.modal)
        saved = StateStore(self.path).data
        self.assertEqual(saved["status"], "DOWN")
        self.assertEqual(saved["failure_selections"]["Station 1"], ["Mechanical"])
        self.assertEqual(
            saved["incident_scope"]["affected_stations"], ["Station 1", "Station 2"]
        )
        self.assertEqual(
            len(
                [
                    x
                    for x in saved["delivery_outbox"]
                    if x["method"] == "create_response_record"
                ]
            ),
            1,
        )

    def test_reporting_with_no_failure_reason_remains_allowed(self):
        app = self.selected()
        app.report_from_failure_picker()
        self.assertEqual(app.state["status"], "DOWN")
        self.assertFalse(app.state["failure_selections"])

    def test_failed_direct_report_keeps_draft_without_losing_saved_selections(self):
        app = self.selected()
        app.modal["selected"] = {"Mechanical"}
        before = deepcopy(app.state)
        with (
            mock.patch(
                "floorterminal.storage.state.write_json", side_effect=OSError("full")
            ),
            self.assertRaises(StateSaveError),
        ):
            app.report_from_failure_picker()
        self.assertEqual(app.state, before)
        self.assertEqual(app.modal["selected"], {"Mechanical"})

    def test_multi_station_failure_details_are_preserved_by_direct_report(self):
        app = self.selected()
        app.modal["selected"] = {"Mechanical"}
        app.save_failure_selection()
        app.select_issue_zone("2")
        app.modal["selected"] = {"Others"}
        app.report_from_failure_picker(self_fix=True)
        self.assertEqual(app.state["status"], "REPAIRING")
        self.assertTrue(app.operator_resolving())
        self.assertEqual(
            set(app.state["incident_scope"]["affected_stations"]),
            {"Station 1", "Station 2", "Station 3", "Station 4"},
        )
        self.assertEqual(
            app.state["failure_selections"],
            {"Station 1": ["Mechanical"], "Station 3": ["Others"]},
        )

    def test_direct_self_fix_handover_reuses_record_and_original_start(self):
        app = self.selected()
        app.report_from_failure_picker(self_fix=True)
        original = app.state["response_record_id"], app.state["started_at"]
        self.action(app, app.request_engineering_handover)
        self.picker(app)
        app.choose_engineer(0)
        self.assertEqual(
            (app.state["response_record_id"], app.state["started_at"]), original
        )
        self.assertFalse(app.operator_resolving())
        self.assertEqual(app.state["engineer_ids"], ["one"])

    def test_quick_arrival_join_and_last_departure_do_not_resume_production(self):
        app = self.selected()
        app.report_from_failure_picker()
        self.picker(app)
        app.choose_engineer(0)
        original = app.state["response_record_id"], app.state["repair_at"]
        self.picker(app, "edit")
        app.choose_engineer(1)
        self.assertEqual(set(app.state["engineer_ids"]), {"one", "two"})
        self.picker(app, "edit")
        app.choose_engineer(0)
        self.assertEqual(app.state["engineer_ids"], ["two"])
        self.picker(app, "edit")
        app.choose_engineer(0)  # Current member is sorted first.
        self.assertEqual(app.state["engineer_ids"], [])
        self.assertEqual(app.state["status"], "REPAIRING")
        self.assertEqual(
            (app.state["response_record_id"], app.state["repair_at"]), original
        )
        self.assertTrue(all(p["left_at"] for p in app.state["engineer_history"]))

    def test_failed_quick_arrival_does_not_leave_usage_or_selected_name_behind(self):
        app = self.selected()
        app.report_from_failure_picker()
        self.picker(app)
        before = deepcopy(app.state)
        with mock.patch(
            "floorterminal.storage.state.write_json", side_effect=OSError("full")
        ):
            app.choose_engineer(0)
        self.assertEqual(app.state, before)
        self.assertEqual(app.modal["selected"], set())
        app.choose_engineer(0)
        self.assertEqual(app.state["engineer_ids"], ["one"])

    def test_batch_selection_remains_explicit_and_atomic(self):
        app = self.selected()
        app.report_from_failure_picker()
        self.picker(app)
        app.modal["batch"] = True
        app.choose_engineer(0)
        app.choose_engineer(1)
        self.assertEqual(app.state["status"], "DOWN")
        self.assertEqual(app.state["engineer_ids"], [])
        app.confirm_engineers()
        self.assertEqual(set(app.state["engineer_ids"]), {"one", "two"})

    def test_filter_preserves_full_crew_draft_and_can_match_id(self):
        app = self.selected()
        app.report_from_failure_picker()
        self.picker(app)
        previous = app.modal
        previous["batch"], previous["selected"] = True, {"one"}
        app.open_text_input(
            "engineer_search", "Find", "Name", "two", return_modal=previous
        )
        app.submit_text_input()
        self.assertEqual(app.modal["selected"], {"one"})
        app.choose_engineer(0)
        app.confirm_engineers()
        self.assertEqual(set(app.state["engineer_ids"]), {"one", "two"})

    def test_a_second_report_touch_cannot_create_a_second_incident(self):
        app = self.selected()
        draft = deepcopy(app.modal)
        app.report_from_failure_picker()
        app.modal = draft
        with self.assertRaises(RuntimeError):
            app.report_from_failure_picker()
        self.assertEqual(
            len(
                [
                    x
                    for x in app.state["delivery_outbox"]
                    if x["method"] == "create_response_record"
                ]
            ),
            1,
        )
