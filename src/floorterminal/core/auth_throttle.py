"""Persistent administrator-authentication throttling."""

from __future__ import annotations

import math
import stat
import time
from pathlib import Path

from .config import write_json
from .json_file import read_bounded_json
from .paths import RUNTIME_ROOT

AUTH_THROTTLE_FILE = RUNTIME_ROOT / "auth_throttle.json"
DELAYS = (0, 0, 0, 2, 5, 30, 60)


class PersistentAuthThrottle:
    """Retain failed-attempt delays across application and device restarts."""

    def __init__(self, path=AUTH_THROTTLE_FILE, wall_clock=None, monotonic=None):
        self.path = Path(path)
        self.wall_clock = wall_clock or time.time
        self.monotonic = monotonic or time.monotonic
        self.failed_attempts = 0
        self.blocked_until_monotonic = 0.0
        self._load()

    def _load(self):
        try:
            data = read_bounded_json(self.path, max_bytes=4096, private=True)
            if not isinstance(data, dict):
                raise TypeError("invalid authentication throttle state")
            attempts = data.get("failed_attempts")
            blocked_epoch = data.get("blocked_until_epoch")
            if (
                type(data.get("schema_version")) is not int
                or data["schema_version"] != 1
                or set(data)
                != {"schema_version", "failed_attempts", "blocked_until_epoch"}
                or isinstance(attempts, bool)
                or not isinstance(attempts, int)
                or not 0 <= attempts <= 1_000_000
                or isinstance(blocked_epoch, bool)
                or not isinstance(blocked_epoch, (int, float))
                or not math.isfinite(blocked_epoch)
            ):
                raise ValueError("invalid authentication throttle state")
            self.failed_attempts = attempts
            remaining = min(DELAYS[-1], max(0.0, blocked_epoch - self.wall_clock()))
            self.blocked_until_monotonic = self.monotonic() + remaining
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, UnicodeError, OverflowError):
            # A damaged security state must not silently remove protection.
            self.failed_attempts = len(DELAYS) - 1
            self.blocked_until_monotonic = self.monotonic() + DELAYS[-1]
            # Do not repair by overwriting an unsafe file or prevent the
            # operator screen from starting. A regular damaged file will be
            # replaced at the next authorized/failed attempt, after the delay.

    def _save(self, remaining=0):
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            metadata = None
        if metadata and (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1):
            raise OSError("Authentication throttle must be a single-link regular file")
        write_json(
            self.path,
            {
                "schema_version": 1,
                "failed_attempts": self.failed_attempts,
                "blocked_until_epoch": self.wall_clock() + max(0, remaining),
            },
        )

    def remaining(self):
        return max(0, int(self.blocked_until_monotonic - self.monotonic() + 0.999))

    def register_failure(self):
        self.failed_attempts = min(1_000_000, self.failed_attempts + 1)
        delay = DELAYS[min(self.failed_attempts, len(DELAYS) - 1)]
        self.blocked_until_monotonic = self.monotonic() + delay
        self._save(delay)
        return delay

    def clear(self):
        previous = self.failed_attempts, self.blocked_until_monotonic
        self.failed_attempts = 0
        self.blocked_until_monotonic = 0.0
        try:
            self._save(0)
        except OSError:
            self.failed_attempts, self.blocked_until_monotonic = previous
            raise
