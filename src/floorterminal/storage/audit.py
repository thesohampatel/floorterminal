"""Private, bounded audit logging; kiosk writes never wait for slow storage."""

from __future__ import annotations

import json
import os
import queue
import stat
import threading
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from ..core.config import PROJECT_DIR
from .housekeeping import inspect_storage, inventory, prune_logs


class ActivityLogger:
    LEVELS: ClassVar = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }
    SEGMENT_BYTES = 4 * 1024 * 1024
    MAX_RECORD_BYTES = 64 * 1024

    def __init__(self, config, *, background=False):
        configured = Path(str(config.get("log_directory", "logs")))
        self.root = configured if configured.is_absolute() else PROJECT_DIR / configured
        self.line_name = config.get("line_name", "")
        self.lock = threading.Lock()
        self._closed = threading.Event()
        self._queue = queue.Queue(maxsize=1024) if background else None
        self.dropped_records = 0
        self.write_failures = 0
        self.last_error = ""
        self._reported_gaps = (0, 0)
        self._thread = None
        if background:
            self._thread = threading.Thread(
                target=self._writer, name="audit-writer", daemon=True
            )
            self._thread.start()
        else:
            self.prune()

    @staticmethod
    def _private_directory(path):
        if path.is_symlink():
            raise OSError("Refusing symbolic-link log directory")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            if stat.S_IMODE(path.stat().st_mode) != 0o700:
                path.chmod(0o700)
        except OSError:
            pass

    def _repair_permissions(self):
        checked_directories = set()
        for _, path, _ in inventory(self.root):
            if any(p.is_symlink() for p in (self.root, path, *tuple(path.parents)[:3])):
                continue
            try:
                metadata = self._audit_metadata(path)
                if metadata is None:
                    continue
                # Already-private segments need no open/close or chmod. Only a
                # real repair takes a checked descriptor, never a pathname chmod.
                if hasattr(os, "fchmod") and stat.S_IMODE(metadata.st_mode) != 0o600:
                    flags = (
                        os.O_RDONLY
                        | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_NONBLOCK", 0)
                    )
                    descriptor = os.open(path, flags)
                    try:
                        metadata = os.fstat(descriptor)
                        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                            continue
                        os.fchmod(descriptor, 0o600)
                    finally:
                        os.close(descriptor)
                for directory in (self.root, *tuple(path.parents)[:3]):
                    if directory in checked_directories:
                        continue
                    checked_directories.add(directory)
                    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
                        directory.chmod(0o700)
            except OSError:
                continue

    def storage_capacity(self):
        report = inspect_storage(self.root)
        report.update(
            audit_dropped_records=self.dropped_records,
            audit_write_failures=self.write_failures,
            audit_error=self.last_error,
        )
        return report

    def log(self, event, level="INFO", **details):
        level = level.upper()
        if self.LEVELS.get(level, 20) < 20 or self._closed.is_set():
            return
        now = datetime.now().astimezone()
        record = {
            "timestamp": now.isoformat(timespec="milliseconds"),
            "level": level,
            "event": event,
            "mode": "PRODUCTION",
            "line": self.line_name,
            **details,
        }
        try:
            # Snapshot at the event, not later after mutable workflow data changes.
            # Capping before enqueue bounds queued payload memory to 64 MiB too.
            item = (now.strftime("%Y/%m/%d"), self._encode(record))
        except (TypeError, ValueError, RecursionError):
            self.dropped_records += 1
            return
        if self._queue is None:
            self._write(*item)
        else:
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self.dropped_records += 1

    def _writer(self):
        while not self._closed.is_set() or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                gaps = (self.dropped_records, self.write_failures)
                if gaps != self._reported_gaps:
                    day, _encoded = item
                    notice = self._encode(
                        {
                            "timestamp": datetime.now().astimezone().isoformat(),
                            "event": "audit_delivery_gap",
                            "level": "WARNING",
                            "mode": "PRODUCTION",
                            "line": self.line_name,
                            "dropped_records": gaps[0],
                            "failed_records": gaps[1],
                        }
                    )
                    if self._write(day, notice):
                        self._reported_gaps = gaps
                self._write(*item)
            finally:
                self._queue.task_done()

    @staticmethod
    def _audit_metadata(path):
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("Refusing nonregular or linked audit file")
        return metadata

    def _rotate(self, path, incoming):
        metadata = self._audit_metadata(path)
        if metadata is None or metadata.st_size + incoming <= self.SEGMENT_BYTES:
            return
        # Validate every source/destination before renaming any segment.
        for number in (1, 2, 3):
            self._audit_metadata(path.with_name(f"activity.{number}.jsonl"))
        for number in (3, 2, 1):
            target = path.with_name(f"activity.{number}.jsonl")
            source = (
                path if number == 1 else path.with_name(f"activity.{number - 1}.jsonl")
            )
            if target.is_symlink() or source.is_symlink():
                raise OSError("Refusing symbolic-link audit segment")
            if source.exists():
                source.replace(target)

    @classmethod
    def _encode(cls, record):
        encoded = (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode(
            "utf-8"
        )
        if len(encoded) > cls.MAX_RECORD_BYTES:
            summary = {
                k: str(record.get(k, ""))[:160]
                for k in ("timestamp", "level", "event", "mode")
            }
            encoded = (
                json.dumps(
                    summary | {"details_omitted": "Audit record exceeded 64 KiB"}
                )
                + "\n"
            ).encode()
        return encoded

    def _write(self, day, encoded):
        try:
            with self.lock:
                cursor = self.root
                self._private_directory(cursor)
                for part in Path(day).parts:
                    cursor /= part
                    self._private_directory(cursor)
                path = cursor / "activity.jsonl"
                self._rotate(path, len(encoded))
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_APPEND
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0)
                )
                descriptor = os.open(path, flags, 0o600)
                with os.fdopen(descriptor, "ab") as stream:
                    metadata = os.fstat(stream.fileno())
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        raise OSError("Refusing nonregular or linked audit file")
                    if (
                        hasattr(os, "fchmod")
                        and stat.S_IMODE(metadata.st_mode) != 0o600
                    ):
                        os.fchmod(stream.fileno(), 0o600)
                    stream.write(encoded)
            self.last_error = ""
            return True
        except (OSError, TypeError, ValueError):
            self.write_failures += 1
            self.last_error = (
                "Audit storage is unavailable; incident recovery is separate"
            )
            return False

    def prune(self):
        with self.lock:
            self._repair_permissions()
            return prune_logs(self.root)

    def close(self, timeout=0.25):
        self._closed.set()
        if self._thread:
            self._thread.join(timeout=timeout)
