"""Durable activation journal, launcher boot state, and update activity log.

Three records are maintained deliberately, because they have different readers and
different failure requirements:

``boot_state``
    A tiny ``KEY=VALUE`` file the POSIX-shell launcher parses before the
    application starts. It must stay readable by a program that cannot depend on a
    JSON parser, and it is the only record the automatic rollback watchdog needs.

``journal.json``
    The full activation history the Software Update panel presents to operators.

``update-log.jsonl``
    An append-only operator- and auditor-visible event log that survives version
    changes and is mirrored onto the removable medium when one is present.

Every write is atomic and owner-private. A damaged record never prevents the
application from starting: the installed executable stays exactly where it is and
the update subsystem reports an unknown state instead.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from ..core.config import restrict_file, write_private
from . import trust

SCHEMA_VERSION = 1
MAX_HISTORY = 40
MAX_LOG_BYTES = 2 * 1024 * 1024
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:+-]*$")
_SAFE_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")

STATE_UNMANAGED = "unmanaged"
STATE_CONFIRMED = "confirmed"
STATE_PROBATION = "probation"
STATE_ROLLED_BACK = "rolled_back"
_STATES = (STATE_UNMANAGED, STATE_CONFIRMED, STATE_PROBATION, STATE_ROLLED_BACK)


def utc_now() -> str:
    """Return the current UTC instant in the fixed journal timestamp form."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class ActivationRecord:
    """One entry in the operator-visible activation history."""

    at_utc: str
    action: str
    from_version: str = ""
    to_version: str = ""
    outcome: str = "ok"
    detail: str = ""
    authorized_by: str = ""
    source: str = ""


@dataclass
class Journal:
    """Current activation state plus a bounded history."""

    state: str = STATE_UNMANAGED
    active_version: str = ""
    previous_version: str = ""
    activated_at_utc: str = ""
    confirmed_at_utc: str = ""
    start_attempts: int = 0
    last_action: str = ""
    last_error: str = ""
    history: list = field(default_factory=list)

    def record(self, entry: ActivationRecord):
        self.history.append(asdict(entry))
        del self.history[:-MAX_HISTORY]
        self.last_action = entry.action
        self.last_error = entry.detail if entry.outcome != "ok" else ""
        return self


def _clean(value, maximum=200):
    text = " ".join(str(value or "").split())
    return text[:maximum]


def read_journal(path) -> Journal:
    """Read the activation journal, returning a safe default when unusable."""
    try:
        restrict_file(path)
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Journal()
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return Journal()
    state = data.get("state")
    history = data.get("history")
    attempts = data.get("start_attempts")
    return Journal(
        state=state if state in _STATES else STATE_UNMANAGED,
        active_version=_clean(data.get("active_version"), 24),
        previous_version=_clean(data.get("previous_version"), 24),
        activated_at_utc=_clean(data.get("activated_at_utc"), 24),
        confirmed_at_utc=_clean(data.get("confirmed_at_utc"), 24),
        start_attempts=attempts
        if isinstance(attempts, int)
        and not isinstance(attempts, bool)
        and 0 <= attempts <= 999
        else 0,
        last_action=_clean(data.get("last_action"), 48),
        last_error=_clean(data.get("last_error"), 400),
        history=[entry for entry in history if isinstance(entry, dict)][-MAX_HISTORY:]
        if isinstance(history, list)
        else [],
    )


def write_journal(path, journal: Journal):
    """Persist the activation journal atomically with owner-only permissions."""
    payload = {"schema_version": SCHEMA_VERSION, **asdict(journal)}
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_private(path, encoded)


def render_boot_state(journal: Journal) -> bytes:
    """Render the shell-readable boot state for the supervised launcher."""
    values = {
        "SCHEMA": str(SCHEMA_VERSION),
        "STATUS": journal.state,
        "ACTIVE": journal.active_version,
        "PREVIOUS": journal.previous_version,
        "ATTEMPTS": str(journal.start_attempts),
        "LIMIT": str(trust.PROBATION_START_LIMIT),
        "UPDATED": utc_now(),
    }
    lines = []
    for key, value in values.items():
        text = str(value)
        # The launcher reads this file with a plain read loop and never evaluates
        # it, but restricting the alphabet keeps that guarantee locally checkable.
        if not _SAFE_KEY.match(key) or not _SAFE_VALUE.match(text):
            text = ""
        lines.append(f"{key}={text}")
    return ("\n".join(lines) + "\n").encode("ascii")


def write_boot_state(path, journal: Journal):
    """Persist the launcher boot state atomically."""
    write_private(path, render_boot_state(journal))


def read_boot_state(path):
    """Parse the launcher boot state into a dictionary of clean strings."""
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, ValueError):
        return {}
    values = {}
    for line in text.splitlines()[:32]:
        key, separator, value = line.partition("=")
        if separator and _SAFE_KEY.match(key) and _SAFE_VALUE.match(value):
            values[key] = value
    return values


def append_log(path, event, level="INFO", **details):
    """Append one bounded JSON Lines update event, rotating a log that grew large."""
    record = {
        "timestamp": utc_now(),
        "level": str(level).upper()[:8],
        "event": str(event)[:64],
        "product": trust.PRODUCT_ID,
        **{key: value for key, value in details.items() if value is not None},
    }
    line = json.dumps(record, ensure_ascii=False, default=str, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_file() and path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        # Update logging is evidence, never a control path: a full or read-only
        # filesystem must not stop an authorized activation or rollback.
        return False
    return True


def read_log(path, limit=40):
    """Return the most recent update events, newest first, ignoring damaged rows."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            rows = stream.readlines()[-(limit * 4) :]
    except OSError:
        return ()
    events = []
    for row in reversed(rows):
        try:
            record = json.loads(row)
        except ValueError:
            continue
        if isinstance(record, dict):
            events.append(record)
        if len(events) >= limit:
            break
    return tuple(events)
