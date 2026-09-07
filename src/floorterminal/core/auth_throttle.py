"""Persistent administrator-authentication throttling."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import restrict_file, write_json
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
        if not self.path.exists():
            return
        restrict_file(self.path)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            attempts = data.get("failed_attempts")
            blocked_epoch = data.get("blocked_until_epoch")
            if (
                data.get("schema_version") != 1
                or isinstance(attempts, bool)
                or not isinstance(attempts, int)
                or not 0 <= attempts <= 1_000_000
                or isinstance(blocked_epoch, bool)
                or not isinstance(blocked_epoch, (int, float))
            ):
                raise ValueError("invalid authentication throttle state")
            self.failed_attempts = attempts
            remaining = min(DELAYS[-1], max(0.0, blocked_epoch - self.wall_clock()))
            self.blocked_until_monotonic = self.monotonic() + remaining
        except (OSError, ValueError, json.JSONDecodeError):
            # A damaged security state must not silently remove protection.
            self.failed_attempts = len(DELAYS) - 1
            self.blocked_until_monotonic = self.monotonic() + DELAYS[-1]
            self._save(DELAYS[-1])

    def _save(self, remaining=0):
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
        self.failed_attempts += 1
        delay = DELAYS[min(self.failed_attempts, len(DELAYS) - 1)]
        self.blocked_until_monotonic = self.monotonic() + delay
        self._save(delay)
        return delay

    def clear(self):
        self.failed_attempts = 0
        self.blocked_until_monotonic = 0.0
        self._save(0)
