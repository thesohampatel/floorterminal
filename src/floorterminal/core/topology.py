"""Physical production topology, independent of any external service.

An empty group list is the original continuous line. Explicit groups partition
the configured stations; a group may stop itself or the entire line. There are
no hidden dependencies or transitive graph rules for operators to guess.
"""

import re
from copy import deepcopy


def validate_groups(config):
    groups = config.get("station_groups", [])
    if not isinstance(groups, list):
        raise TypeError("Station groups must be a list")
    if not groups:
        return
    ids, names, assigned = set(), set(), set()
    zones = set(config["zones"])
    for group in groups:
        if not isinstance(group, dict) or set(group) != {
            "id",
            "name",
            "stations",
            "stop_scope",
        }:
            raise ValueError(
                "Each station group needs id, name, stations and stop_scope"
            )
        identifier, name = group["id"], group["name"]
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,64}", identifier
        ):
            raise ValueError(
                "Group IDs need 1–64 letters, numbers, underscores or hyphens"
            )
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 100
            or not name.isprintable()
        ):
            raise ValueError("Group names must be printable text of 1–100 characters")
        if identifier in ids or name.casefold() in names:
            raise ValueError("Station group IDs and names must be unique")
        ids.add(identifier)
        names.add(name.casefold())
        stations = group["stations"]
        if (
            not isinstance(stations, list)
            or not stations
            or any(not isinstance(s, str) for s in stations)
        ):
            raise ValueError("Each group needs at least one station")
        if (
            len(set(stations)) != len(stations)
            or set(stations) - zones
            or assigned.intersection(stations)
        ):
            raise ValueError("Each configured station must belong to exactly one group")
        assigned.update(stations)
        if group["stop_scope"] not in {"group", "line"}:
            raise ValueError("Group stop_scope must be group or line")
    if assigned != zones:
        raise ValueError("Assign every station to a group before saving")


def groups_for(config):
    return config.get("station_groups") or [
        {
            "id": "line",
            "name": config.get("line_name", "Line"),
            "stations": list(config.get("zones", [])),
            "stop_scope": "line",
        }
    ]


def scope_for(config, selected, targets=None):
    """Snapshot impact and external routing; never fall back to the line asset
    for an independent group with a missing connector mapping.
    """
    groups = groups_for(config)
    whole = "ENTIRE LINE" in selected
    reported = list(config["zones"]) if whole else list(selected)
    chosen = [g for g in groups if set(g["stations"]).intersection(reported)]
    if not chosen or set(reported) - set(config["zones"]):
        raise ValueError("Select a configured station first")
    full = whole or any(g["stop_scope"] == "line" for g in chosen)
    affected = groups if full else chosen
    routes = []
    for group in affected:
        route = (targets or {}).get(group["id"], {})
        if not config.get("station_groups"):
            route = {
                "asset_id": config.get("asset_id", ""),
                "location_id": config.get("location_id", ""),
                **route,
            }
        routes.append(
            {
                "group_id": group["id"],
                "asset_id": str(route.get("asset_id", "")),
                "location_id": str(route.get("location_id", "")),
            }
        )
    # Only an actual whole-line stop may target a configured aggregate asset.
    if full and config.get("station_groups") and config.get("asset_id"):
        routes.append(
            {
                "group_id": "",
                "asset_id": str(config["asset_id"]),
                "location_id": str(config.get("location_id", "")),
            }
        )
    return {
        "impact": "line" if full else "group",
        "connector_binding": "",
        "line_name": config.get("line_name", "Line"),
        "groups": deepcopy(affected),
        "reported_stations": reported,
        "affected_stations": [
            s for s in config["zones"] if any(s in g["stations"] for g in affected)
        ],
        "routes": routes,
    }


def scope_text(scope):
    if not scope:
        return ""
    return (
        f"Impact: {'whole line' if scope['impact'] == 'line' else 'selected groups only'}"
        f"\nGroups: {', '.join(g['name'] for g in scope['groups'])}"
        f"\nStopped stations: {', '.join(scope['affected_stations'])}"
    )
