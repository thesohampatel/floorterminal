"""Independent incident snapshots with a backwards-compatible focused view.

The top-level workflow is the incident currently shown. Other active incidents
are parked, not completed. Shared delivery and history journals never move when
the operator changes focus. All changes commit in the same StateStore document.
"""

import json
import uuid
from copy import deepcopy

MAX_ACTIVE_INCIDENTS = 128
SHARED_FIELDS = {
    "schema_version",
    "events",
    "engineer_usage",
    "delivery_outbox",
    "delivery_pause_until",
    "roster_cache",
    "roster_refresh",
    "pending_record_updates",
    "pending_messages",
    "parked_incidents",
    "history_pending",
    "history_links",
}


def active(state):
    return state.get("status") != "RUNNING" or bool(state.get("pending_planned_work"))


def all_incidents(state):
    if active(state):
        yield state
    yield from state.get("parked_incidents", {}).values()


def snapshot(state):
    return deepcopy({k: v for k, v in state.items() if k not in SHARED_FIELDS})


def switch(state, identifier, defaults):
    if identifier == state.get("incident_id") and active(state):
        return
    parked = state.setdefault("parked_incidents", {})
    target = parked.pop(identifier) if identifier else None
    if active(state):
        if not state.get("incident_id"):
            raise ValueError(
                "Active incident must have an identity before changing focus"
            )
        parked[state["incident_id"]] = snapshot(state)
    for key, value in defaults.items():
        if key not in SHARED_FIELDS:
            state[key] = deepcopy(value)
    if target:
        state.update(target)


def validate_incidents(state, validate_state, defaults):
    parked = state.get("parked_incidents", {})
    if not isinstance(parked, dict) or len(parked) > MAX_ACTIVE_INCIDENTS:
        raise ValueError("Too many active incidents")
    if len(parked) + int(active(state)) > MAX_ACTIVE_INCIDENTS:
        raise ValueError("Too many active incidents")
    seen, occupied = set(), set()
    items = list(all_incidents(state))
    if not active(state) and (
        state.get("incident_id") is not None or state.get("incident_scope") is not None
    ):
        items.insert(0, state)
    for item in items:
        identifier, scope = item.get("incident_id"), item.get("incident_scope")
        # Pre-grouping saved incidents remain valid until safely migrated.
        if identifier is None and scope is None and item is state:
            continue
        uuid.UUID(identifier)
        if identifier in seen:
            raise ValueError("Duplicate incident identity")
        seen.add(identifier)
        if not isinstance(scope, dict) or set(scope) != {
            "impact",
            "line_name",
            "groups",
            "reported_stations",
            "affected_stations",
            "routes",
            "connector_binding",
        }:
            raise ValueError("Invalid incident impact snapshot")
        bound = scope["connector_binding"]
        if (
            not isinstance(bound, str)
            or bound
            and (len(bound) != 64 or any(c not in "0123456789abcdef" for c in bound))
        ):
            raise ValueError("Invalid incident connector binding")
        from ..core.topology import validate_groups

        validate_groups(
            {"zones": scope["affected_stations"], "station_groups": scope["groups"]}
        )
        if not scope["groups"] or scope["impact"] not in {"line", "group"}:
            raise ValueError("Invalid incident groups")
        stations = scope["affected_stations"]
        if (
            not isinstance(stations, list)
            or any(not isinstance(s, str) for s in stations)
            or not stations
            or len(set(stations)) != len(stations)
        ):
            raise ValueError("Invalid affected stations")
        if active(item) and occupied.intersection(stations):
            raise ValueError("Active incidents cannot overlap affected stations")
        if active(item):
            occupied.update(stations)
        if not isinstance(scope["reported_stations"], list) or not set(
            scope["reported_stations"]
        ).issubset(stations):
            raise ValueError("Reported stations outside incident scope")
        if (
            not isinstance(scope["routes"], list)
            or len(scope["routes"]) > len(scope["groups"]) + 1
        ):
            raise ValueError("Invalid incident routing")
        for route in scope["routes"]:
            if (
                not isinstance(route, dict)
                or set(route) != {"group_id", "asset_id", "location_id"}
                or any(
                    not isinstance(v, str)
                    or len(v) > 200
                    or (v and not v.isprintable())
                    for v in route.values()
                )
            ):
                raise ValueError("Invalid group target")
        if item is not state:
            if (
                not active(item)
                or parked.get(identifier) is not item
                or set(item) != set(defaults) - SHARED_FIELDS
            ):
                raise ValueError("Invalid parked incident fields")
            validate_state({**deepcopy(defaults), **item}, nested=True)
    if len(json.dumps(parked, allow_nan=False).encode()) > 8 * 1024 * 1024:
        raise ValueError("Active incident recovery capacity reached")
