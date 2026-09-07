"""Structured production audit logging with automatic retention."""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import ClassVar

from ..core.config import PROJECT_DIR


class ActivityLogger:
    LEVELS: ClassVar = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }

    def __init__(self, config):
        configured = Path(str(config.get("log_directory", "logs")))
        self.root = configured if configured.is_absolute() else PROJECT_DIR / configured
        self.retention_days = max(1, int(config.get("log_retention_days", 183)))
        self.minimum = self.LEVELS.get(str(config.get("log_level", "INFO")).upper(), 20)
        self.storage_reserve = (
            max(128, int(config.get("log_storage_reserve_mb", 512))) * 1024 * 1024
        )
        self.daily_growth_floor = (
            max(1, int(config.get("log_daily_growth_floor_mb", 2))) * 1024 * 1024
        )
        self.line_name = config.get("line_name", "")
        self.lock = threading.Lock()
        self._repair_permissions()
        self.prune()

    @staticmethod
    def _private_directory(path):
        if path.is_symlink():
            raise OSError(f"Refusing symbolic-link log directory: {path}")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.chmod(0o700)
        except OSError:
            pass

    def _repair_permissions(self):
        """Repair files produced by releases that inherited a permissive umask."""
        if not self.root.exists():
            return
        for directory in (
            self.root,
            *self.root.glob("[0-9][0-9][0-9][0-9]"),
            *self.root.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]"),
            *self.root.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]"),
        ):
            if directory.is_dir() and not directory.is_symlink():
                try:
                    directory.chmod(0o700)
                except OSError:
                    pass
        for path in self.root.glob(
            "[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/activity.jsonl"
        ):
            if path.is_file() and not path.is_symlink():
                try:
                    path.chmod(0o600)
                except OSError:
                    pass

    def storage_capacity(self):
        """Estimate whether free space covers retention plus an OS safety reserve."""
        anchor = self.root
        while not anchor.exists() and anchor != anchor.parent:
            anchor = anchor.parent
        usage = shutil.disk_usage(anchor)
        files = (
            list(
                self.root.glob(
                    "[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/activity.jsonl"
                )
            )
            if self.root.exists()
            else []
        )
        total = 0
        active_days = set()
        for path in files:
            try:
                total += path.stat().st_size
                active_days.add(tuple(path.parts[-4:-1]))
            except OSError:
                continue
        observed_daily = total / max(1, len(active_days))
        estimated_daily = max(self.daily_growth_floor, observed_daily)
        # Fifty percent headroom covers unusually busy periods and larger error records.
        projected_logs = int(estimated_daily * self.retention_days * 1.5)
        required = projected_logs + self.storage_reserve
        mb = 1024 * 1024
        return {
            "enough": usage.free >= required,
            "free_mb": round(usage.free / mb),
            "required_mb": round(required / mb),
            "projected_log_mb": round(projected_logs / mb),
            "reserve_mb": round(self.storage_reserve / mb),
            "observed_log_mb": round(total / mb, 2),
            "retention_days": self.retention_days,
        }

    def log(self, event, level="INFO", **details):
        level = level.upper()
        if self.LEVELS.get(level, 20) < self.minimum:
            return
        now = datetime.now().astimezone()
        path = self.root / now.strftime("%Y/%m/%d") / "activity.jsonl"
        record = {
            "timestamp": now.isoformat(timespec="milliseconds"),
            "level": level,
            "event": event,
            "mode": "PRODUCTION",
            "line": self.line_name,
            **details,
        }
        try:
            with self.lock:
                relative = path.parent.relative_to(self.root)
                cursor = self.root
                self._private_directory(cursor)
                for part in relative.parts:
                    cursor /= part
                    self._private_directory(cursor)
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(path, flags, 0o600)
                if hasattr(os, "fchmod"):
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(record, ensure_ascii=False, default=str) + "\n"
                    )
        except OSError:
            pass

    def prune(self):
        cutoff = datetime.now().astimezone().date() - timedelta(
            days=self.retention_days
        )
        if not self.root.exists():
            return
        for day_dir in self.root.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]"):
            try:
                folder_date = date.fromisoformat("-".join(day_dir.parts[-3:]))
                if folder_date < cutoff:
                    shutil.rmtree(day_dir)
            except (ValueError, OSError):
                continue
        for pattern in ("[0-9][0-9][0-9][0-9]/*", "[0-9][0-9][0-9][0-9]"):
            for folder in sorted(self.root.glob(pattern), reverse=True):
                try:
                    folder.rmdir()
                except OSError:
                    pass
