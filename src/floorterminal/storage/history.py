"""Private local incident archive, independent of disposable diagnostic logs.

StateStore stages snapshots before acknowledging an operation. A separate worker
upserts them in SQLite and only then acknowledges the staging queue. Replaying
after power loss is harmless. Cleanup never touches active incidents or outboxes.
"""

import json
import os
import shutil
import sqlite3
import stat
import time
import uuid
from copy import deepcopy
from pathlib import Path

MAX_PENDING = 256
MAX_RECORD_BYTES = 128 * 1024
HISTORY_FIELDS = (
    "incident_id",
    "incident_scope",
    "status",
    "response_record_id",
    "started_at",
    "repair_at",
    "operator_response",
    "work_label",
    "work_type",
    "issue_zones",
    "failure_selections",
    "failure_notes",
    "engineer_ids",
    "engineer_names",
    "engineer_history",
    "escalated_at",
)
SUMMARY_FIELDS = {
    "completed_at",
    "classification",
    "total_seconds",
    "active_work_seconds",
    "response_category",
}


def validate_pending(records):
    if not isinstance(records, list) or len(records) > MAX_PENDING:
        raise ValueError(
            "Local history queue is full; check device storage before recording more incidents"
        )
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            *HISTORY_FIELDS,
            *SUMMARY_FIELDS,
        }:
            raise ValueError("Invalid local history record")
        uuid.UUID(record["incident_id"])
        if record["incident_id"] in seen:
            raise ValueError("Duplicate local history record")
        seen.add(record["incident_id"])
        if record["completed_at"] is not None and (
            isinstance(record["completed_at"], bool)
            or not isinstance(record["completed_at"], (int, float))
            or not 0 < record["completed_at"] < 1e12
        ):
            raise ValueError("Invalid history completion time")
        if len(json.dumps(record, allow_nan=False).encode()) > MAX_RECORD_BYTES:
            raise ValueError("Local history record exceeds safety capacity")
    if len(json.dumps(records, allow_nan=False).encode()) > 8 * 1024 * 1024:
        raise ValueError(
            "Local history recovery queue exceeds its safe storage capacity"
        )


def validate_links(links):
    if not isinstance(links, dict) or len(links) > MAX_PENDING:
        raise ValueError("Local history link queue is full")
    for key, value in links.items():
        uuid.UUID(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, str))
            or len(str(value)) > 200
        ):
            raise ValueError("Invalid history external record reference")


def stage(state, completed_at=None, incident=None, classification=None):
    incident = state if incident is None else incident
    if not incident.get("incident_id"):
        return
    record = {key: deepcopy(incident.get(key)) for key in HISTORY_FIELDS}
    record["completed_at"] = completed_at
    record["classification"] = classification
    record["total_seconds"] = (
        max(0, int(completed_at - (incident.get("started_at") or completed_at)))
        if completed_at
        else None
    )
    record["active_work_seconds"] = (
        max(
            0,
            int(
                completed_at
                - (
                    incident.get("repair_at")
                    or incident.get("started_at")
                    or completed_at
                )
            ),
        )
        if completed_at
        else None
    )
    operator = incident.get("operator_response")
    record["response_category"] = (
        "operator_then_engineering"
        if operator and operator.get("handed_over_at")
        else "operator_self_fix"
        if operator
        else "planned"
        if incident.get("status") == "ENGINEERING"
        else "engineering"
    )
    pending = state.setdefault("history_pending", [])
    # Latest snapshot contains the complete crew timeline, failure selection and
    # handover timestamps, not an unbounded stream of animation/UI events.
    pending[:] = [r for r in pending if r["incident_id"] != record["incident_id"]]
    pending.append(record)
    validate_pending(pending)


def stage_active(state, previous):
    from .incidents import all_incidents

    old = {i.get("incident_id"): i for i in all_incidents(previous)}
    for incident in all_incidents(state):
        before = old.get(incident.get("incident_id"), {})
        if incident.get("incident_id") and any(
            incident.get(k) != before.get(k) for k in HISTORY_FIELDS
        ):
            stage(state, incident=incident)


class IncidentArchive:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "incidents.sqlite3"

    def _open(self):
        if self.root.is_symlink():
            raise OSError("History directory must not be a symbolic link")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        for path in (
            self.path,
            Path(str(self.path) + "-journal"),
            Path(str(self.path) + "-wal"),
            Path(str(self.path) + "-shm"),
        ):
            if path.is_symlink():
                raise OSError("History files must not be symbolic links")
            if path.exists() and (
                not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1
            ):
                raise OSError(
                    "History files must be regular, private files without hard links"
                )
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        os.chmod(self.path, 0o600)
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported local history schema")
            db.execute(
                "CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, completed REAL, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS completed_incidents ON incidents(completed)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS external_links (id TEXT PRIMARY KEY, record_id TEXT NOT NULL)"
            )
            db.execute("PRAGMA user_version=1")
            return db
        except BaseException:
            db.close()
            raise

    def store(self, records, links=None):
        validate_pending(records)
        validate_links(links or {})
        db = self._open()
        try:
            with db:
                db.executemany(
                    "INSERT INTO external_links VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET record_id=excluded.record_id",
                    [(key, json.dumps(value)) for key, value in (links or {}).items()],
                )
                db.executemany(
                    "INSERT INTO incidents VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET completed=excluded.completed,payload=excluded.payload",
                    [
                        (
                            r["incident_id"],
                            r["completed_at"],
                            json.dumps(r, ensure_ascii=False, allow_nan=False),
                        )
                        for r in records
                    ],
                )
        finally:
            db.close()

    def maintain(self, now=None, protected=()):
        now = time.time() if now is None else now
        usage = shutil.disk_usage(self.root)
        reserve = max(256 * 1024**2, min(2 * 1024**3, int(usage.total * 0.05)))
        budget = max(
            0,
            min(
                512 * 1024**2,
                int(usage.total * 0.02),
                usage.free + self.path.stat().st_size - reserve,
            ),
        )
        db = self._open()
        try:
            size = self.path.stat().st_size
            # At most 200 completed records per pass. Retain at least today's
            # records, even under pressure; report pressure rather than lose them.
            age = 86400 if size > budget else 730 * 86400
            protected = tuple(sorted(key for key in set(protected) if key))
            # Filter before LIMIT: old protected records must not indefinitely
            # starve reclamation of newer eligible records during an outage.
            exclusion = (
                " AND id NOT IN (" + ",".join("?" for _ in protected) + ")"
                if protected
                else ""
            )
            with db:
                candidates = [
                    row[0]
                    for row in db.execute(
                        "SELECT id FROM incidents WHERE completed IS NOT NULL AND completed < ?"
                        + exclusion
                        + " ORDER BY completed LIMIT 200",
                        (now - age, *protected),
                    )
                ]
                db.executemany(
                    "DELETE FROM incidents WHERE id=?", [(key,) for key in candidates]
                )
                db.executemany(
                    "DELETE FROM external_links WHERE id=?",
                    [(key,) for key in candidates],
                )
                deleted = len(candidates)
                db.execute("PRAGMA incremental_vacuum(512)")
            count, opened = db.execute(
                "SELECT count(*),sum(completed IS NULL) FROM incidents"
            ).fetchone()
            return {
                "records": count,
                "open_records": opened or 0,
                "removed": deleted,
                "bytes": self.path.stat().st_size,
                "budget_bytes": budget,
                "storage_pressure": size > budget,
            }
        finally:
            db.close()

    def recent(self, limit=100):
        """Bounded read API for future reporting/export; no secrets are stored."""
        db = self._open()
        try:
            rows = db.execute(
                "SELECT payload,record_id FROM incidents LEFT JOIN external_links USING(id) ORDER BY COALESCE(completed, 1e12) DESC LIMIT ?",
                (max(1, min(1000, int(limit))),),
            )
            result = []
            for payload, record_id in rows:
                record = json.loads(payload)
                if record_id is not None:
                    record["response_record_id"] = json.loads(record_id)
                result.append(record)
            return result
        finally:
            db.close()
