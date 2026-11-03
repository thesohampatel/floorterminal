"""Bounded housekeeping of application-owned audit files, never recovery data."""

from __future__ import annotations

import os
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

MIB = 1024 * 1024
MAX_RETENTION_DAYS = 183
MAX_FILES = 12000
AUDIT_NAME = re.compile(r"activity(?:\.[123])?\.jsonl\Z")


def inventory(root: Path):
    """Walk only the dated audit layout without following directory/file links.

    Stop on an unexpectedly large tree instead of spending unbounded time or
    deleting an incomplete inventory. Unknown files are not owned by this job.
    """
    files = []
    visited = 0
    if not root.exists():
        return files
    if root.is_symlink():
        raise OSError("Audit root must not be a symbolic link")

    def walk(parent, depth):
        nonlocal visited
        with os.scandir(parent) as entries:
            for entry in entries:
                visited += 1
                if visited > MAX_FILES:
                    raise OSError("Audit inventory exceeds the safe housekeeping limit")
                if entry.is_symlink():
                    continue
                path = Path(entry.path)
                if depth < 3:
                    digits = 4 if depth == 0 else 2
                    if (
                        len(entry.name) == digits
                        and entry.name.isascii()
                        and entry.name.isdigit()
                        and entry.is_dir(follow_symlinks=False)
                    ):
                        walk(path, depth + 1)
                elif AUDIT_NAME.fullmatch(entry.name) and entry.is_file(
                    follow_symlinks=False
                ):
                    try:
                        day = date.fromisoformat("-".join(path.parts[-4:-1]))
                    except ValueError:
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    if metadata.st_nlink == 1:
                        files.append((day, path, metadata.st_size))

    walk(root, 0)
    return files


def policy(total, free, files):
    """Keep up to six months, shrinking the budget before OS space is exhausted."""
    occupied = sum(size for _, _, size in files)
    days = len({day for day, _, _ in files})
    reserve = min(2048 * MIB, max(256 * MIB, total // 20))
    budget = max(0, min(512 * MIB, total // 50, occupied + free - reserve))
    estimated_daily = int(max(64 * 1024, occupied / max(1, days)) * 1.5)
    retention = min(MAX_RETENTION_DAYS, max(1, budget // estimated_daily))
    required = reserve + estimated_daily
    return {
        "enough": free >= required,
        "free_mb": round(free / MIB),
        "required_mb": round(required / MIB),
        "projected_log_mb": round(estimated_daily * retention / MIB, 2),
        "reserve_mb": round(reserve / MIB),
        "observed_log_mb": round(occupied / MIB, 2),
        "retention_days": retention,
        "budget_mb": round(budget / MIB, 2),
        "budget_bytes": budget,
    }


def inspect_storage(root, files=None):
    anchor = root
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    usage = shutil.disk_usage(anchor)
    return policy(usage.total, usage.free, inventory(root) if files is None else files)


def prune_logs(root, today=None):
    """Delete only closed-day audit segments. Preserve today's file and strangers."""
    today = today or datetime.now().astimezone().date()
    files = inventory(root)
    report = inspect_storage(root, files)
    cutoff = today - timedelta(days=report["retention_days"] - 1)
    occupied = sum(size for _, _, size in files)
    removed = 0
    for day, path, size in sorted(files):
        if day >= today:
            continue
        if day >= cutoff and occupied <= report["budget_bytes"]:
            continue
        if any(p.is_symlink() for p in (root, path, *tuple(path.parents)[:3])):
            continue
        try:
            path.unlink()
            occupied -= size
            removed += 1
            for directory in tuple(path.parents)[:3]:
                try:
                    directory.rmdir()  # Empty only; never removes unknown files.
                except OSError:
                    break
        except OSError:
            continue
    return removed
