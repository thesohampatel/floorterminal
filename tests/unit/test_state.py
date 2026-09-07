import json
import tempfile
import unittest
from pathlib import Path

from floorterminal.storage.state import StateIntegrityError, StateStore


class StateStoreTests(unittest.TestCase):
    def test_non_v1_state_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"schema_version": 999, "status": "RUNNING"}))
            with self.assertRaisesRegex(StateIntegrityError, "Unsupported"):
                StateStore(path)

    def test_round_trip_preserves_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            store.data.update(status="DOWN", response_record_id=42)
            store.save()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            restored = StateStore(path).data
            self.assertEqual(restored["status"], "DOWN")
            self.assertEqual(restored["response_record_id"], 42)

    def test_legacy_active_state_requests_asset_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"status": "REPAIRING", "response_record_id": 42}))
            path.chmod(0o644)
            restored = StateStore(path).data
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(restored["asset_status"], "OFFLINE")
            self.assertTrue(restored["asset_status_sync_pending"])
            self.assertIsNone(restored["asset_status_sync_key"])

    def test_asset_idempotency_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            store.data.update(
                asset_status_sync_pending=True,
                asset_status_sync_target="OFFLINE",
                asset_status_sync_key="asset-event-1",
                asset_status_sync_attempts=2,
            )
            store.save()
            restored = StateStore(path).data
            self.assertEqual(restored["asset_status_sync_key"], "asset-event-1")
            self.assertEqual(restored["asset_status_sync_attempts"], 2)

    def test_corrupt_or_invalid_state_never_silently_becomes_running(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"status":')
            with self.assertRaisesRegex(StateIntegrityError, "will not assume"):
                StateStore(path)
            self.assertEqual(path.read_text(), '{"status":')

            path.write_text(json.dumps({"status": "UNKNOWN"}))
            with self.assertRaisesRegex(StateIntegrityError, "Invalid persisted"):
                StateStore(path)

    def test_pending_response_record_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            store.data.update(
                status="DOWN",
                started_at=123.0,
                pending_response_record={
                    "title": "Stopped line",
                    "description": "Recorded locally",
                    "priority": "HIGH",
                    "created_at": 123.0,
                    "report_id": "offline-report-1",
                    "sync_attempts": 2,
                },
            )
            store.save()
            restored = StateStore(path).data
            self.assertEqual(restored["status"], "DOWN")
            self.assertEqual(restored["pending_response_record"]["title"], "Stopped line")
            self.assertEqual(restored["pending_response_record"]["sync_attempts"], 2)

    def test_pending_planned_work_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            store.data.update(
                pending_planned_work={
                    "work_label": "Preventive Maintenance",
                    "work_type": "PREVENTIVE",
                    "team_id": "team-1",
                    "participants": [{"id": "u1", "displayName": "Alex Engineer"}],
                    "title": "Planned work",
                    "description": "Recorded locally",
                    "priority": "MEDIUM",
                    "created_at": 123.0,
                    "report_id": "offline-planned-1",
                    "sync_attempts": 1,
                }
            )
            store.save()
            restored = StateStore(path).data
            self.assertEqual(
                restored["pending_planned_work"]["report_id"], "offline-planned-1"
            )
            self.assertEqual(restored["pending_planned_work"]["sync_attempts"], 1)

    def test_pending_planned_work_rejects_malformed_participants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "RUNNING",
                        "pending_planned_work": {
                            "work_label": "Preventive Maintenance",
                            "work_type": "PREVENTIVE",
                            "team_id": "team-1",
                            "participants": [{"id": 1, "displayName": "Alex"}],
                            "title": "Planned work",
                            "description": "Recorded locally",
                            "priority": "MEDIUM",
                            "created_at": 123.0,
                            "report_id": "offline-planned-1",
                        },
                    }
                )
            )
            with self.assertRaisesRegex(StateIntegrityError, "participants"):
                StateStore(path)


if __name__ == "__main__":
    unittest.main()
