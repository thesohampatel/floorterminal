"""Focus, stop propagation and immutable per-incident routing."""

import uuid
from copy import deepcopy

from ..core.topology import groups_for, scope_for, scope_text
from ..storage.incidents import MAX_ACTIVE_INCIDENTS, active, all_incidents, switch
from ..storage.state import INITIAL_STATE


class GroupWorkflowMixin:
    def validate_active_topology(self):
        from ..core.config import ConfigurationError

        current = {group["id"]: group for group in self.station_groups()}
        for incident in all_incidents(self.state):
            scope = incident.get("incident_scope")
            if scope and (
                any(current.get(group["id"]) != group for group in scope["groups"])
                or (
                    scope["impact"] == "line"
                    and set(scope["affected_stations"]) != set(self.config["zones"])
                )
            ):
                raise ConfigurationError(
                    "Configured station groups differ from an active incident. Restore the saved topology before starting; recovery data has not been discarded."
                )

    def station_groups(self):
        return groups_for(self.config)

    def group_targets(self):
        definition = getattr(self.provider, "definition", None)
        return definition.workflow.get("group_targets", {}) if definition else {}

    def preview_scope(self):
        return scope_for(self.config, self.selected_zones(), self.group_targets())

    def begin_incident(self, identifier):
        if active(self.state):
            raise RuntimeError(
                "Continue the existing incident before starting another in this group"
            )
        scope = self.preview_scope()
        from ..storage.delivery import binding

        scope["connector_binding"] = binding(self.provider)
        others = list(all_incidents(self.state))
        if len(others) >= MAX_ACTIVE_INCIDENTS:
            raise RuntimeError(
                "Active incident capacity reached; resolve an existing incident first"
            )
        for other in others:
            if set(scope["affected_stations"]).intersection(
                other["incident_scope"]["affected_stations"]
            ):
                raise RuntimeError(
                    "This stop would overlap an open incident. Open the stopped group to continue it; resolve existing incidents before reporting a whole-line stop."
                )
        self.state.update(incident_id=identifier, incident_scope=scope)
        return scope_text(scope)

    def migrate_active_scope(self):
        if active(self.state) and not self.state.get("incident_id"):
            pending = (
                self.state.get("pending_response_record")
                or self.state.get("pending_planned_work")
                or {}
            )
            self.state["incident_id"] = pending.get("report_id") or str(uuid.uuid4())
            # Legacy incidents stopped the entire line, even if only one fault
            # station was selected. Preserve that physical interpretation.
            self.state["incident_scope"] = scope_for(
                self.config, ["ENTIRE LINE"], self.group_targets()
            )
            from ..storage.delivery import binding

            self.state["incident_scope"]["connector_binding"] = binding(self.provider)
            self.save_state()

    def focus_incident(self, identifier=None):
        self.migrate_active_scope()
        if getattr(self.provider, "deferred_writes", False) and any(
            self.state.get(key)
            for key in (
                "pending_response_record",
                "pending_planned_work",
                "pending_response_status",
                "pending_participant_assignment",
                "asset_status_sync_pending",
            )
        ):
            # Convert older single-slot retry state to the shared delivery
            # journal before parking it. This conversion performs no HTTP calls.
            self.synchronize_due_work(force=True)
        switch(self.state, identifier, INITIAL_STATE)
        self.save_state()

    def incident_for_station(self, station):
        for item in all_incidents(self.state):
            scope = item.get("incident_scope")
            if scope is None or station in scope["affected_stations"]:
                return item
        return None

    def group_station_touch(self, station):
        """Return True when the touch changed incident focus, not fault choices."""
        if not self.config.get("station_groups"):
            return False
        incident = self.incident_for_station(station)
        if incident:
            if incident is not self.state:
                identifier = incident["incident_id"]
                self.perform(
                    "Opening group response", lambda: self.focus_incident(identifier)
                )
            else:
                self.notify(
                    "This group's response is open below • continue its next step",
                    "info",
                    4,
                )
            return True
        if active(self.state):

            def select_new():
                self.focus_incident()
                self.state["issue_zones"] = [station]
                self.save_state()

            self.perform(
                "Selecting running group",
                select_new,
                lambda _: self.open_failure_selection(station),
            )
            return True
        return False

    def incident_context(self, incident=None):
        incident = self.state if incident is None else incident
        scope = incident.get("incident_scope")
        if not scope:
            return {}
        assets = list(
            dict.fromkeys(r["asset_id"] for r in scope["routes"] if r["asset_id"])
        )
        locations = list(
            dict.fromkeys(r["location_id"] for r in scope["routes"] if r["location_id"])
        )
        return {
            "asset_id": assets[0] if len(assets) == 1 else "",
            "location_id": locations[0] if len(locations) == 1 else "",
            "asset_ids": assets,
            "location_ids": locations,
            "group_ids": [g["id"] for g in scope["groups"]],
            "group_names": [g["name"] for g in scope["groups"]],
            "affected_stations": list(scope["affected_stations"]),
            "reported_stations": list(scope["reported_stations"]),
            "impact_scope": scope["impact"],
            "incident_id": incident.get("incident_id"),
            "failure_details": [
                {
                    "station": station,
                    "reasons": list(
                        incident.get("failure_selections", {}).get(station, [])
                    ),
                    "note": incident.get("failure_notes", {}).get(station, ""),
                }
                for station in scope["reported_stations"]
            ],
        }

    def external_assets(self, target):
        scope = self.state.get("incident_scope")
        if not scope:
            return None
        routes = {r["asset_id"]: deepcopy(r) for r in scope["routes"] if r["asset_id"]}
        if target in {"ONLINE", "OFFLINE"}:
            # Several local groups may represent the same remote machine.
            # It remains Offline until the last affected group is released.
            for other in self.state.get("parked_incidents", {}).values():
                for route in other["incident_scope"]["routes"]:
                    routes.pop(route["asset_id"], None)
        return list(routes.values())

    def escalate_group(self, identifier):
        """Background escalation without changing the operator's focused view."""
        if identifier == self.state.get("incident_id"):
            return self.escalate_downtime()
        import time

        from ..core.topology import scope_text

        item = self.state["parked_incidents"][identifier]
        item["escalated_at"] = time.time()
        message = f"RESPONSE OVERDUE • {item['incident_scope']['line_name']}\n{scope_text(item['incident_scope'])}\nResponse record: {item.get('response_record_id')}"
        targets = (
            ["escalation_chat_name"]
            if self.config.get("escalation_chat_name")
            else ["engineering_chat_name", "common_activity_chat_name"]
        )
        # Queue text already carries its own scope; do not append focused scope.
        for chat in dict.fromkeys(self.config.get(key, "") for key in targets):
            if chat and getattr(self.provider, "deferred_writes", False):
                self.provider._queue("send_message", [chat, message], incident=item)
        self.save_state()
        return "Group response escalated"
