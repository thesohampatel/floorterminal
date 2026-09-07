"""Persistent production workflow state and schema migration."""

from __future__ import annotations

import json
from numbers import Real

from ..core.config import STATE_FILE, restrict_file, write_json

STATE_SCHEMA_VERSION = 1
VALID_STATUSES = {"RUNNING", "DOWN", "REPAIRING", "ENGINEERING"}


class StateIntegrityError(ValueError):
    """Raised when persisted operational state cannot be trusted."""


INITIAL_STATE = {
    "schema_version": STATE_SCHEMA_VERSION,
    "status": "RUNNING",
    "response_record_id": None,
    "started_at": None,
    "repair_at": None,
    "events": [],
    "issue_zones": [],
    "engineer_ids": [],
    "engineer_names": [],
    "engineer_history": [],
    "failure_selections": {},
    "failure_notes": {},
    "engineer_usage": {},
    "escalated_at": None,
    "asset_status": None,
    "asset_status_id": None,
    "asset_offline_status_id": None,
    "asset_status_sync_pending": False,
    "asset_status_sync_target": None,
    "asset_status_sync_key": None,
    "asset_status_sync_attempts": 0,
    "asset_status_sync_context": None,
    "pending_response_status": None,
    "pending_participant_assignment": None,
    "pending_response_record": None,
    "pending_sync_error": "",
    "pending_planned_work": None,
}


def _optional_number(value):
    return value is None or isinstance(value, Real) and not isinstance(value, bool)


def validate_state(data):
    if not isinstance(data, dict):
        raise StateIntegrityError("response_state.json must contain one JSON object")
    unknown = set(data) - set(INITIAL_STATE)
    if unknown:
        raise StateIntegrityError(
            "Persisted state contains unsupported fields: " + ", ".join(sorted(unknown))
        )
    status = data.get("status")
    if status not in VALID_STATUSES:
        raise StateIntegrityError(f"Invalid persisted machine status: {status!r}")
    if any(
        not _optional_number(data.get(key))
        for key in (
            "started_at",
            "repair_at",
            "escalated_at",
        )
    ):
        raise StateIntegrityError("Persisted timer values must be numbers or null")
    response_record_id = data.get("response_record_id")
    if response_record_id is not None and (
        isinstance(response_record_id, bool) or not isinstance(response_record_id, (str, int))
    ):
        raise StateIntegrityError(
            "Persisted response_record_id must be text, a number, or null"
        )
    for key in (
        "events",
        "issue_zones",
        "engineer_ids",
        "engineer_names",
        "engineer_history",
    ):
        if not isinstance(data.get(key), list):
            raise StateIntegrityError(f"Persisted {key} must be a list")
    if not all(isinstance(value, str) for value in data["issue_zones"]):
        raise StateIntegrityError("Persisted issue_zones must contain station names")
    if not isinstance(data.get("failure_selections"), dict):
        raise StateIntegrityError("Persisted failure_selections must be an object")
    if any(
        not isinstance(station, str)
        or not isinstance(values, list)
        or any(not isinstance(value, str) for value in values)
        for station, values in data["failure_selections"].items()
    ):
        raise StateIntegrityError(
            "Persisted failure_selections must contain station text lists"
        )
    failure_notes = data.get("failure_notes")
    if not isinstance(failure_notes, dict) or any(
        not isinstance(station, str) or not isinstance(note, str) or len(note) > 240
        for station, note in failure_notes.items()
    ):
        raise StateIntegrityError(
            "Persisted failure_notes must contain short text notes"
        )
    usage = data.get("engineer_usage")
    if not isinstance(usage, dict) or any(
        not isinstance(key, str)
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for key, value in usage.items()
    ):
        raise StateIntegrityError("Persisted engineer_usage must contain usage counts")
    if not isinstance(data.get("asset_status_sync_pending"), bool):
        raise StateIntegrityError("Persisted asset_status_sync_pending must be Boolean")
    target = data.get("asset_status_sync_target")
    if target not in {None, "ONLINE", "OFFLINE", "IGNORE"}:
        raise StateIntegrityError("Persisted asset_status_sync_target is invalid")
    sync_key = data.get("asset_status_sync_key")
    if sync_key is not None and (not isinstance(sync_key, str) or not sync_key.strip()):
        raise StateIntegrityError("Persisted asset_status_sync_key is invalid")
    asset_attempts = data.get("asset_status_sync_attempts")
    if (
        isinstance(asset_attempts, bool)
        or not isinstance(asset_attempts, int)
        or asset_attempts < 0
    ):
        raise StateIntegrityError(
            "Persisted asset_status_sync_attempts must be a non-negative integer"
        )
    asset_context = data.get("asset_status_sync_context")
    if asset_context is not None:
        if not isinstance(asset_context, dict):
            raise StateIntegrityError("Persisted asset status context must be an object")
        if asset_context.get("status") not in {"ONLINE", "OFFLINE", "IGNORE"}:
            raise StateIntegrityError("Persisted asset status context target is invalid")
        if asset_context.get("downtime_type") not in {None, "PLANNED", "UNPLANNED"}:
            raise StateIntegrityError("Persisted asset status context type is invalid")
        for key in ("description", "started_at"):
            if not isinstance(asset_context.get(key, ""), str):
                raise StateIntegrityError(
                    f"Persisted asset status context {key} must be text"
                )
        if not _optional_number(asset_context.get("last_attempt_at")):
            raise StateIntegrityError(
                "Persisted asset status context last_attempt_at must be a number or null"
            )
    pending_status = data.get("pending_response_status")
    if pending_status is not None:
        if not isinstance(pending_status, dict):
            raise StateIntegrityError("Persisted response status update must be an object")
        if pending_status.get("status") not in {"IN_PROGRESS", "DONE"}:
            raise StateIntegrityError("Persisted response status target is invalid")
        if isinstance(pending_status.get("record_id"), bool) or not isinstance(
            pending_status.get("record_id"), (str, int)
        ):
            raise StateIntegrityError("Persisted response status record ID is invalid")
        attempts = pending_status.get("attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise StateIntegrityError("Persisted response status attempts are invalid")
        if not _optional_number(pending_status.get("last_attempt_at")):
            raise StateIntegrityError("Persisted response status last attempt is invalid")
    pending_assignment = data.get("pending_participant_assignment")
    if pending_assignment is not None:
        if not isinstance(pending_assignment, dict):
            raise StateIntegrityError("Persisted participant assignment must be an object")
        if isinstance(pending_assignment.get("record_id"), bool) or not isinstance(
            pending_assignment.get("record_id"), (str, int)
        ):
            raise StateIntegrityError("Persisted participant assignment record ID is invalid")
        team_id = pending_assignment.get("team_id")
        if team_id is not None and (
            isinstance(team_id, bool) or not isinstance(team_id, (str, int))
        ):
            raise StateIntegrityError("Persisted participant assignment team ID is invalid")
        user_ids = pending_assignment.get("user_ids")
        if not isinstance(user_ids, list) or any(
            isinstance(value, bool) or not isinstance(value, (str, int))
            for value in user_ids
        ):
            raise StateIntegrityError("Persisted participant IDs are invalid")
        attempts = pending_assignment.get("attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise StateIntegrityError("Persisted participant assignment attempts are invalid")
        if not _optional_number(pending_assignment.get("last_attempt_at")):
            raise StateIntegrityError("Persisted participant assignment last attempt is invalid")
    if not isinstance(data.get("pending_sync_error"), str):
        raise StateIntegrityError("Persisted pending_sync_error must be text")
    pending = data.get("pending_response_record")
    if pending is not None:
        if not isinstance(pending, dict):
            raise StateIntegrityError(
                "Persisted pending_response_record must be an object or null"
            )
        for key in ("title", "description", "priority"):
            if not isinstance(pending.get(key), str) or not pending[key].strip():
                raise StateIntegrityError(f"Pending response record is missing {key}")
        if (
            not isinstance(pending.get("report_id"), str)
            or not pending["report_id"].strip()
        ):
            raise StateIntegrityError("Pending response record is missing report_id")
        if (
            not _optional_number(pending.get("created_at"))
            or pending.get("created_at") is None
        ):
            raise StateIntegrityError("Pending response record created_at must be a number")
        attempts = pending.get("sync_attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise StateIntegrityError(
                "Pending response record sync_attempts must be a non-negative integer"
            )
        last_attempt = pending.get("last_attempt_at")
        if not _optional_number(last_attempt):
            raise StateIntegrityError(
                "Pending response record last_attempt_at must be a number or null"
            )
        for key in ("zones_summary", "failures_summary"):
            value = pending.get(key)
            if value is not None and not isinstance(value, str):
                raise StateIntegrityError(f"Pending response record {key} must be text")
    planned = data.get("pending_planned_work")
    if planned is not None:
        if not isinstance(planned, dict):
            raise StateIntegrityError(
                "Persisted pending_planned_work must be an object or null"
            )
        for key in ("work_label", "work_type", "title", "description", "priority"):
            if not isinstance(planned.get(key), str) or not planned[key].strip():
                raise StateIntegrityError(f"Pending planned work is missing {key}")
        team_id = planned.get("team_id")
        if team_id is not None and (
            isinstance(team_id, bool) or not isinstance(team_id, (str, int))
        ):
            raise StateIntegrityError(
                "Pending planned work team_id must be text, a number, or null"
            )
        participants = planned.get("participants")
        if not isinstance(participants, list) or any(
            not isinstance(member, dict)
            or not isinstance(member.get("id"), str)
            or not isinstance(member.get("displayName"), str)
            for member in participants
        ):
            raise StateIntegrityError("Pending planned work participants are invalid")
        if (
            not isinstance(planned.get("report_id"), str)
            or not planned["report_id"].strip()
        ):
            raise StateIntegrityError("Pending planned work is missing report_id")
        if (
            not _optional_number(planned.get("created_at"))
            or planned.get("created_at") is None
        ):
            raise StateIntegrityError(
                "Pending planned work created_at must be a number"
            )
        planned_attempts = planned.get("sync_attempts", 0)
        if (
            isinstance(planned_attempts, bool)
            or not isinstance(planned_attempts, int)
            or planned_attempts < 0
        ):
            raise StateIntegrityError(
                "Pending planned work sync_attempts must be a non-negative integer"
            )
        if not _optional_number(planned.get("last_attempt_at")):
            raise StateIntegrityError(
                "Pending planned work last_attempt_at must be a number or null"
            )
        for key in ("zones_summary", "failures_summary"):
            value = planned.get(key)
            if value is not None and not isinstance(value, str):
                raise StateIntegrityError(f"Pending planned work {key} must be text")
    return data


class StateStore:
    def __init__(self, path=STATE_FILE):
        self.path = path
        if path.exists():
            restrict_file(path)
        try:
            saved = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            )
        except OSError as exc:
            raise StateIntegrityError(f"Cannot read {path.name}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise StateIntegrityError(
                f"Corrupt {path.name} at line {exc.lineno}, column {exc.colno}; the terminal will not assume Production is running"
            ) from exc
        if saved and not isinstance(saved, dict):
            raise StateIntegrityError(f"{path.name} must contain one JSON object")
        schema = saved.get("schema_version") if isinstance(saved, dict) else None
        if schema not in (None, STATE_SCHEMA_VERSION):
            raise StateIntegrityError(
                f"Unsupported downtime state schema_version: {schema!r}"
            )
        self.data = {**INITIAL_STATE, **saved}
        self.data["schema_version"] = STATE_SCHEMA_VERSION
        self.data.setdefault("events", [])
        self.data.setdefault("engineer_ids", [])
        self.data.setdefault("engineer_names", [])
        self.data.setdefault("engineer_history", [])
        self.data.setdefault("failure_selections", {})
        self.data.setdefault("failure_notes", {})
        self.data.setdefault("engineer_usage", {})
        self.data.setdefault("escalated_at", None)
        if not self.data.get("asset_status"):
            self.data["asset_status"] = (
                "ONLINE" if self.data.get("status") == "RUNNING" else "OFFLINE"
            )
        self.data.setdefault("asset_status_id", None)
        self.data.setdefault("asset_offline_status_id", None)
        self.data.setdefault("asset_status_sync_target", None)
        self.data.setdefault("asset_status_sync_key", None)
        self.data.setdefault("asset_status_sync_attempts", 0)
        self.data.setdefault("asset_status_sync_context", None)
        self.data.setdefault("pending_response_status", None)
        self.data.setdefault("pending_participant_assignment", None)
        if "asset_status_sync_pending" not in saved:
            self.data["asset_status_sync_pending"] = (
                self.data.get("status") != "RUNNING" and "asset_status" not in saved
            )
        if not isinstance(self.data["failure_selections"], dict):
            self.data["failure_selections"] = {}
        validate_state(self.data)

    def save(self):
        validate_state(self.data)
        write_json(self.path, self.data)
