"""Calendar refresh policy and bounded, credential-free roster retry metadata."""

import math
from datetime import UTC, datetime, time, timedelta

IDLE_SECONDS = 60
REFRESH_FIELDS = {
    "binding",
    "team_name",
    "attempted_at",
    "retry_at",
    "failures",
    "pending",
    "manual",
    "error",
}
ERRORS = {"", "interrupted", "unavailable", "rate_limited", "configuration"}


def local_day(timestamp):
    try:
        return datetime.fromtimestamp(timestamp, UTC).astimezone().date()
    except (ValueError, OverflowError, OSError):
        return None


def daily_due(saved_at, now):
    """Use calendar boundaries, not 24-hour intervals (including DST days)."""
    return (
        saved_at > now + 300
        or local_day(saved_at) is None
        or local_day(saved_at) != local_day(now)
    )


def next_midnight(now):
    tomorrow = local_day(now) + timedelta(days=1)
    # Resolve the target local calendar midnight using the host's timezone at
    # that date, not today's UTC offset (DST days are not always 24 hours).
    return datetime.combine(tomorrow, time.min).astimezone().timestamp()


def validate_refresh(value):
    if not isinstance(value, dict):
        raise TypeError("Invalid team refresh metadata")
    if not value:
        return
    if (
        set(value) != REFRESH_FIELDS
        or not isinstance(value["binding"], str)
        or len(value["binding"]) != 64
        or any(c not in "0123456789abcdef" for c in value["binding"])
        or not isinstance(value["team_name"], str)
        or len(value["team_name"]) > 120
        or not value["team_name"].strip()
        or not value["team_name"].isprintable()
        or type(value["pending"]) is not bool
        or type(value["manual"]) is not bool
        or type(value["failures"]) is not int
        or not 0 <= value["failures"] <= 32
        or not isinstance(value["error"], str)
        or value["error"] not in ERRORS
    ):
        raise ValueError("Invalid team refresh metadata fields")
    for key in ("attempted_at", "retry_at"):
        if (
            isinstance(value[key], bool)
            or not isinstance(value[key], (int, float))
            or not math.isfinite(value[key])
            or value[key] < 0
        ):
            raise ValueError("Invalid team refresh timestamp")
