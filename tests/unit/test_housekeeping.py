"""Automatic, bounded housekeeping must never clean operational recovery data."""

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from floorterminal.services.health import system_observations
from floorterminal.storage.audit import ActivityLogger
from floorterminal.storage.housekeeping import MIB, inventory, policy, prune_logs


class HousekeepingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "logs"
        self.today = datetime.now().astimezone().date()

    def file(self, age, name="activity.jsonl", size=100):
        path = (
            self.root / (self.today - timedelta(days=age)).strftime("%Y/%m/%d") / name
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        return path

    def test_budget_reserve_and_retention_are_bounded(self):
        for total in (512 * MIB, 8 * 1024 * MIB, 64 * 1024 * MIB):
            for free in (0, 100 * MIB, total // 2):
                result = policy(total, free, [])
                self.assertLessEqual(
                    result["budget_bytes"], min(total // 50, 512 * MIB)
                )
                self.assertGreaterEqual(result["budget_bytes"], 0)
                self.assertGreaterEqual(result["retention_days"], 1)
                self.assertLessEqual(result["retention_days"], 183)

    def test_only_expired_owned_files_are_removed(self):
        expired = self.file(190)
        stranger = self.file(190, "connector.json")
        state = self.file(190, "response_state.json")
        recent = self.file(1)
        with patch(
            "floorterminal.storage.housekeeping.shutil.disk_usage",
            return_value=SimpleNamespace(total=32 * 1024 * MIB, free=8 * 1024 * MIB),
        ):
            self.assertEqual(prune_logs(self.root), 1)
        self.assertFalse(expired.exists())
        for path in (stranger, state, recent):
            self.assertTrue(path.exists())

    def test_pressure_removes_old_logs_but_never_todays_or_unknown_data(self):
        old = self.file(1)
        current = self.file(0)
        future = self.file(-1)
        pending = self.file(1, "pending.json")
        with patch(
            "floorterminal.storage.housekeeping.shutil.disk_usage",
            return_value=SimpleNamespace(total=1024 * MIB, free=0),
        ):
            prune_logs(self.root)
        self.assertFalse(old.exists())
        for path in (current, future, pending):
            self.assertTrue(path.exists())

    def test_directory_and_file_symlinks_are_not_followed(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        secret = outside / "activity.jsonl"
        secret.write_text("keep")
        day = self.file(200).parent
        (day / "activity.jsonl").unlink()
        (day / "activity.jsonl").symlink_to(secret)
        (self.root / "1900").symlink_to(outside, target_is_directory=True)
        self.assertEqual(inventory(self.root), [])
        prune_logs(self.root)
        self.assertEqual(secret.read_text(), "keep")

    def test_inventory_limit_aborts_without_deleting(self):
        path = self.file(200)
        with (
            patch("floorterminal.storage.housekeeping.MAX_FILES", 2),
            self.assertRaises(OSError),
        ):
            prune_logs(self.root)
        self.assertTrue(path.exists())

    def test_current_day_rotation_is_bounded_and_preserves_unrelated_files(self):
        logger = ActivityLogger({"log_directory": str(self.root)})
        logger.SEGMENT_BYTES = 512
        for _ in range(80):
            logger.log("event", details="x" * 80)
        files = inventory(self.root)
        self.assertEqual(len(files), 4)
        self.assertLessEqual(sum(size for _, _, size in files), 4 * 512)
        for _, path, _ in files:
            for line in path.read_text().splitlines():
                self.assertEqual(json.loads(line)["event"], "event")

    def test_oversized_record_is_summarized(self):
        logger = ActivityLogger({"log_directory": str(self.root)})
        logger.log("large", detail="x" * (128 * 1024))
        _, path, size = inventory(self.root)[0]
        self.assertLess(size, logger.MAX_RECORD_BYTES)
        self.assertIn("details_omitted", json.loads(path.read_text()))

    def test_slow_writer_never_blocks_ui_and_queue_is_bounded(self):
        entered, release = threading.Event(), threading.Event()
        original = ActivityLogger._write

        def slow(logger, *args):
            entered.set()
            release.wait(5)
            return original(logger, *args)

        with patch.object(ActivityLogger, "_write", slow):
            logger = ActivityLogger({"log_directory": str(self.root)}, background=True)
            self.addCleanup(lambda: logger.close(5))
            logger.log("first")
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            for _ in range(2000):
                logger.log("touch")
            self.assertLess(time.monotonic() - started, 3)
            self.assertLessEqual(logger._queue.qsize(), 1024)
            self.assertGreater(logger.dropped_records, 0)
            release.set()
            logger.close(5)
        self.assertFalse(logger._thread.is_alive())
        self.assertIn(
            "audit_delivery_gap",
            "".join(p.read_text() for _, p, _ in inventory(self.root)),
        )

    def test_write_failure_is_observable_not_fatal(self):
        logger = ActivityLogger({"log_directory": str(self.root)})
        with patch("floorterminal.storage.audit.os.open", side_effect=OSError("full")):
            logger.log("event")
        self.assertEqual(logger.write_failures, 1)
        self.assertTrue(logger.last_error)
        logger.log("recovered")
        self.assertFalse(logger.last_error)

    def test_audit_queue_snapshots_and_caps_payloads_before_writing(self):
        with patch.object(ActivityLogger, "_writer"):
            logger = ActivityLogger({"log_directory": str(self.root)}, background=True)
            original = ["before"]
            logger.log("snapshot", detail=original)
            original.append("after")
            _, encoded = logger._queue.get_nowait()
            self.assertEqual(json.loads(encoded)["detail"], ["before"])
            logger.log("x" * 200000, detail="x" * 200000)
            _, encoded = logger._queue.get_nowait()
            self.assertLessEqual(len(encoded), logger.MAX_RECORD_BYTES)
            cyclic = []
            cyclic.append(cyclic)
            logger.log("bad payload", detail=cyclic)
            self.assertEqual(logger.dropped_records, 1)
            logger.close()

    def test_legacy_retention_and_level_settings_do_not_disable_automatic_care(self):
        logger = ActivityLogger(
            {
                "log_directory": str(self.root),
                "log_level": "CRITICAL",
                "log_retention_days": 730,
            }
        )
        logger.log("important")
        self.assertEqual(len(inventory(self.root)), 1)
        self.assertLessEqual(logger.storage_capacity()["retention_days"], 183)

    def test_health_probe_gracefully_supports_platforms_without_linux_sensors(self):
        with patch("pathlib.Path.read_text", side_effect=OSError):
            self.assertEqual(system_observations(), {"warnings": []})

    def test_low_memory_and_temperature_are_visible(self):
        with patch(
            "pathlib.Path.read_text",
            side_effect=["MemTotal: 1024000 kB\nMemAvailable: 12000 kB\n", "85000"],
        ):
            report = system_observations()
        self.assertEqual(len(report["warnings"]), 2)
        self.assertEqual(report["temperature_c"], 85)
