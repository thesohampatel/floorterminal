"""System-clock plausibility check.

Every audit record, downtime duration, escalation deadline, and update entry is
timestamped from the system clock. A Raspberry Pi has no battery-backed real-time
clock, so a terminal that boots without network time can come up in 1970 or at the
image's build date and silently write unusable records.

Workflow timers already run on a monotonic clock and are unaffected, so this check
never blocks anything. It exists so the condition is visible in the audit stream and
on screen instead of being discovered months later during an investigation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

#: A terminal cannot legitimately be running before the version it runs was built.
#: Compared against the release date compiled into the build.
BACKWARD_TOLERANCE_SECONDS = 24 * 60 * 60
#: Ten years is far beyond any plausible deployment life for one build.
FORWARD_LIMIT_SECONDS = 10 * 365 * 24 * 60 * 60


@dataclass(frozen=True)
class ClockCheck:
    """Outcome of one plausibility comparison."""

    trusted: bool
    reason: str = ""
    system_time_utc: str = ""
    reference_utc: str = ""

    @property
    def summary(self):
        if self.trusted:
            return "System clock is plausible"
        return f"System clock is not plausible: {self.reason}"


def _stamp(epoch):
    return (
        datetime.fromtimestamp(float(epoch), UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def check_clock(reference_utc=None, now=None) -> ClockCheck:
    """Compare the system clock with the release date compiled into this build."""
    now = float(now if now is not None else time.time())
    if reference_utc is None:
        from ..update.catalog import installed_entry

        entry = installed_entry()
        reference_utc = entry.released_utc if entry else None
    if not reference_utc:
        return ClockCheck(True, system_time_utc=_stamp(now))
    try:
        reference = datetime.strptime(reference_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except (TypeError, ValueError):
        return ClockCheck(True, system_time_utc=_stamp(now))
    released = reference.timestamp()
    details = {"system_time_utc": _stamp(now), "reference_utc": reference_utc}
    if now < released - BACKWARD_TOLERANCE_SECONDS:
        return ClockCheck(
            False,
            "the clock reads earlier than the date this version was released, so "
            "recorded times cannot be trusted until time synchronization succeeds",
            **details,
        )
    if now > released + FORWARD_LIMIT_SECONDS:
        return ClockCheck(
            False,
            "the clock reads implausibly far ahead of the date this version was "
            "released, so recorded times cannot be trusted",
            **details,
        )
    return ClockCheck(True, **details)
