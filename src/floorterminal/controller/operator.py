"""Operator-owned minor-stop response and explicit Engineering handover.

This is a response path, not attendance or an authorization to repair equipment.
The physical incident and its external record remain the same through handover.
"""

from __future__ import annotations

import time


class OperatorResponseMixin:
    def operator_resolving(self):
        response = self.state.get("operator_response")
        return bool(response and response.get("handed_over_at") is None)

    def operator_response_summary(self, finished_at=None):
        response = self.state.get("operator_response")
        if not response:
            return ""
        end = response.get("handed_over_at") or finished_at or time.time()
        duration = self.format_duration(max(0, end - response["started_at"]))
        category = (
            "Operator then Engineering"
            if response.get("handed_over_at")
            else "Operator self-fix"
        )
        return (
            f"Response category: {category}\nOperator: {response['name'] or 'Name not recorded'}"
            f"\nOperator response time: {duration}"
            + (
                "\nEngineering assistance was requested during the same incident."
                if response.get("requested_at")
                else ""
            )
        )

    def request_engineering_handover(self):
        response = self.state.get("operator_response")
        if not self.operator_resolving():
            raise RuntimeError("No operator self-fix is active")
        if response.get("requested_at"):
            return "Engineering is already requested for this incident"
        response["requested_at"] = time.time()
        self.state.update(status="DOWN", escalated_at=None)
        record = self.state.get("response_record_id")
        message = (
            f"ENGINEERING HELP REQUIRED • {self.config['line_name']}\nResponse record: #{record}"
            f"\nStations: {self.zone_summary()}\nReported failures: {self.failure_summary()}"
            f"\n{self.operator_response_summary()}"
            "\nOperator self-fix did not resolve the stoppage. Original downtime continues."
        )
        self.save_state()
        if self._supports("supports_response_record_assignments"):
            team = (
                self.provider.resolve_name(
                    "team", self.config.get("engineering_team_name", "")
                )
                if self.provider.INFO.supports_team_directory
                else None
            )
            self.sync_participant_assignment(record, team, [])
        self.post_record_comment(record, message)
        self.send_activity_chats(
            [
                "engineering_chat_name",
                "production_chat_name",
                "common_activity_chat_name",
            ],
            message,
        )
        self.log_event("Operator requested Engineering • same incident", self.ORANGE)
        self.logger.log("operator_handover_requested", response_record_id=record)
        self.play_sound("alert")
        return "Engineering requested • original downtime continues"

    def record_operator_handover(self):
        response = self.state.get("operator_response")
        if response and response.get("handed_over_at") is None:
            response["handed_over_at"] = time.time()
            self.logger.log(
                "operator_handed_over_to_engineering",
                response_record_id=self.state.get("response_record_id"),
            )
