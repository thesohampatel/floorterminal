"""Archive crash replay, privacy, bounded retention and independent local use."""

import json
import os
import sqlite3
import time
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

from floorterminal.services.history import HistoryCoordinator
from floorterminal.storage.history import IncidentArchive, validate_pending
from floorterminal.storage.state import StateSaveError

from .test_station_groups import GroupHarness


class IncidentHistoryTests(GroupHarness):
    def test_maintenance_only_does_not_lock_operator_or_rewrite_state(self):
        app = self.group_app()
        app.save_state()
        saved = self.path.read_bytes()
        service = HistoryCoordinator(app)
        service.active = True
        service.health = {"error": "earlier failure"}
        service.results.put(([], {}, {"removed": 0}, None))
        app.perform = mock.Mock()
        before = time.monotonic()
        service.poll()
        app.perform.assert_not_called()
        self.assertFalse(service.active)
        self.assertFalse(app.busy)
        self.assertEqual(service.health, {"removed": 0})
        self.assertGreaterEqual(service.next_at, before + 5)
        self.assertEqual(self.path.read_bytes(), saved)

    def test_maintenance_only_leaves_newly_staged_history_untouched(self):
        app, record = self.record()
        app.state["history_links"] = {record["incident_id"]: "R1"}
        original = deepcopy(app.state)
        service = HistoryCoordinator(app)
        service.active = True
        # The maintenance snapshot preceded the new report and link.
        service.results.put(([], {}, {}, None))
        app.perform = mock.Mock()
        service.poll()
        app.perform.assert_not_called()
        self.assertEqual(app.state, original)
        self.assertFalse(service.active)

    def test_link_only_batch_still_requires_durable_acknowledgement(self):
        app, record = self.record()
        links = {record["incident_id"]: "R1"}
        app.state["history_links"] = dict(links)
        service = HistoryCoordinator(app)
        service.active = True
        service.results.put(([], links, {}, None))
        app.perform = mock.Mock(return_value=True)
        service.poll()
        app.perform.assert_called_once()
        self.assertTrue(service.active)
        self.assertEqual(app.state["history_links"], links)
        args, _ = app.perform.call_args
        result = args[1]()
        args[2](result)
        self.assertEqual(app.state["history_links"], {})
        self.assertEqual(app.state["history_pending"], [record])
        self.assertFalse(service.active)

    def test_frequent_writes_do_not_postpone_hourly_cleanup(self):
        app, _ = self.record()
        service = HistoryCoordinator(app)
        deadline = time.monotonic() + 1200
        service.next_cleanup = deadline
        with (
            mock.patch.object(service.archive, "store"),
            mock.patch.object(service.archive, "maintain") as maintain,
        ):
            service.poll()
            service.close(2)
        self.assertEqual(service.next_cleanup, deadline)
        maintain.assert_not_called()

    def test_protected_prefix_does_not_starve_cleanup(self):
        _, record = self.record()
        archive = IncidentArchive(self.path.parent / "records")
        old = time.time() - 731 * 86400
        records = []
        for index in range(202):
            value = deepcopy(record)
            value["incident_id"] = str(uuid.uuid4())
            value["completed_at"] = old + index
            records.append(value)
        archive.store(records)
        protected = {r["incident_id"] for r in records[:200]}
        result = archive.maintain(protected=protected)
        self.assertEqual(result["removed"], 2)
        self.assertEqual({r["incident_id"] for r in archive.recent(1000)}, protected)

    def test_hardlinked_archive_is_rejected(self):
        _, record = self.record()
        archive = IncidentArchive(self.path.parent / "records")
        archive.root.mkdir()
        original = self.path.parent / "unrelated"
        original.write_text("preserve")
        os.link(original, archive.path)
        with self.assertRaises(OSError):
            archive.store([record])
        self.assertEqual(original.read_text(), "preserve")

    def test_archive_ack_runs_on_local_worker_and_keeps_newer_snapshot(self):
        app, record = self.record()
        service = HistoryCoordinator(app)
        service.active = True
        service.results.put(([record], {}, {}, None))
        calls = []
        app.perform = lambda *args, **kwargs: calls.append((args, kwargs)) or True
        service.poll()
        self.assertEqual(len(app.state["history_pending"]), 1)
        self.assertEqual(len(calls), 1)
        newer = deepcopy(record)
        newer["failure_notes"] = {"Station 1": "Reconciled note"}
        app.state["history_pending"] = [newer]
        result = calls[0][0][1]()
        calls[0][0][2](result)
        self.assertEqual(app.state["history_pending"], [newer])
        self.assertFalse(service.active)

    def record(self):
        app = self.group_app()
        self.report(app, "Station 1", "Operator A")
        self.action(app, app.finish_work)
        return app, deepcopy(app.state["history_pending"][0])

    def test_history_contains_failure_scope_crew_and_completion(self):
        app = self.group_app()
        app.state["failure_selections"] = {"Station 1": ["Others"]}
        app.state["failure_notes"] = {"Station 1": "Guard sensor"}
        self.report(app, "Station 1", "Operator A")
        self.action(app, app.finish_work)
        record = app.state["history_pending"][0]
        self.assertEqual(record["failure_notes"]["Station 1"], "Guard sensor")
        self.assertEqual(record["incident_scope"]["groups"][0]["id"], "cell-a")
        self.assertGreaterEqual(record["completed_at"], record["started_at"])
        self.assertEqual(record["operator_response"]["name"], "Operator A")
        self.assertEqual(record["response_category"], "operator_self_fix")
        self.assertIsInstance(record["total_seconds"], int)
        self.assertGreaterEqual(record["active_work_seconds"], 0)
        self.assertTrue(record["classification"])
        self.assertNotIn("credentials", json.dumps(record))

    def test_crash_between_archive_commit_and_ack_is_idempotent(self):
        app, record = self.record()
        archive = IncidentArchive(self.path.parent / "records")
        archive.store([record])
        app = self.group_app()
        archive.store(app.state["history_pending"])
        self.assertEqual(len(archive.recent()), 1)

    def test_archive_links_late_remote_id_after_local_completion(self):
        app, record = self.record()
        archive = IncidentArchive(self.path.parent / "records")
        archive.store([record])
        self.assertTrue(archive.recent()[0]["response_record_id"].startswith("local:"))
        app.state["history_pending"] = []
        app.save_state()
        self.drain(app)
        archive.store([], app.state["history_links"])
        self.assertEqual(archive.recent()[0]["response_record_id"], "R1")

    def test_file_and_directory_permissions_are_private(self):
        _, record = self.record()
        archive = IncidentArchive(self.path.parent / "records")
        archive.store([record])
        if os.name != "nt":
            self.assertEqual(archive.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(archive.root.stat().st_mode & 0o777, 0o700)

    def test_symlink_and_corrupt_archive_are_not_replaced(self):
        _, record = self.record()
        root = self.path.parent / "records"
        root.mkdir()
        target = root / "private.txt"
        target.write_text("preserve")
        archive = IncidentArchive(root)
        archive.path.symlink_to(target)
        with self.assertRaises(OSError):
            archive.store([record])
        self.assertEqual(target.read_text(), "preserve")
        archive.path.unlink()
        archive.path.write_text("corrupt but preserve for recovery")
        with self.assertRaises(sqlite3.DatabaseError):
            archive.store([record])
        self.assertEqual(archive.path.read_text(), "corrupt but preserve for recovery")

    def test_cleanup_only_removes_old_completed_unprotected_records(self):
        _, record = self.record()
        archive = IncidentArchive(self.path.parent / "records")
        old = time.time() - 731 * 86400
        records = []
        for offset, closed in enumerate((old, old, None, time.time())):
            value = deepcopy(record)
            value["incident_id"] = str(uuid.uuid4())
            value["completed_at"] = closed
            records.append(value)
        archive.store(records)
        report = archive.maintain(protected={records[1]["incident_id"]})
        self.assertEqual(report["removed"], 1)
        self.assertEqual(
            {r["incident_id"] for r in archive.recent()},
            {r["incident_id"] for r in records[1:]},
        )

    def test_storage_pressure_reclaims_old_closed_data_not_today(self):
        _, record = self.record()
        archive = IncidentArchive(self.path.parent / "records")
        yesterday = deepcopy(record)
        yesterday.update(
            incident_id=str(uuid.uuid4()), completed_at=time.time() - 3 * 86400
        )
        archive.store([record, yesterday])
        with mock.patch(
            "floorterminal.storage.history.shutil.disk_usage",
            return_value=SimpleNamespace(total=1024**3, free=0),
        ):
            report = archive.maintain()
        self.assertTrue(report["storage_pressure"])
        self.assertEqual(report["removed"], 1)
        self.assertEqual(archive.recent()[0]["incident_id"], record["incident_id"])

    def test_history_failure_does_not_ack_or_discard_pending_record(self):
        app, record = self.record()
        service = HistoryCoordinator(app)
        app.notify = lambda *_args: None
        with mock.patch.object(
            service.archive, "store", side_effect=OSError("read only")
        ):
            service.poll()
            deadline = time.monotonic() + 3
            while service.results.empty() and time.monotonic() < deadline:
                time.sleep(0.01)
            service.poll()
        self.assertEqual(app.state["history_pending"], [record])
        self.assertIn("read only", service.health["error"])

    def test_archive_ack_does_not_restage_unchanged_open_incident(self):
        app = self.group_app()
        self.report(app, "Station 1")
        app.state["history_pending"] = []
        app.save_state()
        self.assertEqual(app.state["history_pending"], [])

    def test_completed_history_survives_failed_release_save(self):
        app = self.group_app()
        self.report(app, "Station 1", "")
        before = deepcopy(app.state)
        with (
            mock.patch(
                "floorterminal.storage.state.write_json",
                side_effect=OSError("disk full"),
            ),
            self.assertRaises(StateSaveError),
        ):
            self.action(app, app.finish_work)
        self.assertEqual(app.state, before)
        self.assertIsNone(app.state["history_pending"][0]["completed_at"])

    def test_standalone_reporting_never_grows_external_outbox(self):
        app = self.group_app(configured=False)
        app.config["reporting_mode"] = "local"
        for _ in range(15):
            self.report(app, "Station 1", "")
            self.action(app, app.finish_work)
        self.assertEqual(app.state["delivery_outbox"], [])
        self.assertEqual(len(app.state["history_pending"]), 15)
        self.assertEqual(len(self.transport.requests), 0)

    def test_history_capacity_and_oversized_record_fail_closed(self):
        _, record = self.record()
        oversized = deepcopy(record)
        oversized["failure_notes"] = {"Station 1": "x" * 131072}
        with self.assertRaises(ValueError):
            validate_pending([oversized])
        with self.assertRaises(ValueError):
            validate_pending([record] * 257)
