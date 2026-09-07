"""Atomic version activation, supervised probation, and verified rollback.

Activating a version replaces exactly one symbolic link. ``rename`` is atomic on
POSIX, so an interruption at any instant — power loss, a pulled drive, a killed
process — leaves either the previous slot or the new slot active and never a
half-written executable. The previously running slot is never modified or removed
while it can still be needed, so the version the site last accepted always remains
launchable.

A newly activated version starts on probation. The supervised launcher counts
starts before the application runs; the application marks the version confirmed
only after it has stayed up for the configured dwell time. A version that cannot
start therefore exhausts its attempts and is restored to the previous slot by the
launcher without any operator action.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from . import journal, media, trust, version
from .journal import ActivationRecord, Journal
from .layout import InstallLayout


class ActivationError(RuntimeError):
    """Raised when an activation or rollback cannot be performed safely."""


@dataclass(frozen=True)
class ActivationResult:
    """Outcome of one activation or rollback."""

    action: str
    from_version: str
    to_version: str
    restart_required: bool = True


def _fsync_directory(path: Path):
    """Persist a rename so an immediate power loss cannot resurrect the old link."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _swap_link(layout: InstallLayout, release_version: str):
    """Point the active link at ``release_version`` atomically."""
    link = layout.active_link
    target = layout.slot_executable(release_version)
    if not target.is_file():
        raise ActivationError(
            f"Version {release_version} is not installed on this terminal"
        )
    if link.exists() and not link.is_symlink():
        raise ActivationError(
            "This installation runs a fixed executable rather than managed version "
            "slots. Reinstall with the current install.sh to enable updates."
        )
    relative = os.path.join(
        layout.versions_dir.name, str(release_version), trust.EXECUTABLE_NAME
    )
    temporary = link.parent / f".{link.name}.activating"
    try:
        temporary.unlink(missing_ok=True)
        os.symlink(relative, temporary)
        os.replace(temporary, link)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ActivationError(f"Could not switch the active version: {exc}") from exc
    _fsync_directory(link.parent)


def _persist(layout: InstallLayout, record: Journal):
    layout.ensure_directories()
    journal.write_journal(layout.journal, record)
    journal.write_boot_state(layout.boot_state, record)


def slot_release(layout: InstallLayout, release_version):
    """Return the stored release description for an installed slot, if present."""
    path = layout.slot(release_version) / "release.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def initialise(layout: InstallLayout, installed_version) -> Journal:
    """Reconcile the journal with what is actually installed, at every startup.

    This runs before anything else in the update subsystem so the panel, the
    launcher, and the audit log always agree with the filesystem, including after
    the watchdog restored a previous version without the application's help.
    """
    record = journal.read_journal(layout.journal)
    active = layout.active_version()
    if active is None:
        record.state = journal.STATE_UNMANAGED
        record.active_version = str(installed_version)
        record.start_attempts = 0
        return record
    if record.active_version != active:
        rolled_back = (
            record.state == journal.STATE_PROBATION
            and active == record.previous_version
        )
        record.record(
            ActivationRecord(
                at_utc=journal.utc_now(),
                action="watchdog_rollback" if rolled_back else "reconciled",
                from_version=record.active_version,
                to_version=active,
                outcome="warning" if rolled_back else "ok",
                detail=(
                    "The supervised launcher restored the previous version after "
                    "the new version failed to start."
                    if rolled_back
                    else ""
                ),
                source="launcher" if rolled_back else "startup",
            )
        )
        record.state = (
            journal.STATE_ROLLED_BACK if rolled_back else journal.STATE_CONFIRMED
        )
        record.active_version = active
        record.start_attempts = 0
        if rolled_back:
            journal.append_log(
                layout.update_log,
                "update_auto_rolled_back",
                "ERROR",
                to_version=active,
                detail="New version exhausted its supervised start attempts",
            )
    elif record.state == journal.STATE_UNMANAGED:
        record.state = journal.STATE_CONFIRMED
        record.active_version = active
        record.confirmed_at_utc = record.confirmed_at_utc or journal.utc_now()
    _persist(layout, record)
    return record


def confirm(layout: InstallLayout, record: Journal | None = None) -> Journal:
    """Mark the running version healthy once it has survived the dwell period."""
    record = record or journal.read_journal(layout.journal)
    if record.state != journal.STATE_PROBATION:
        return record
    record.state = journal.STATE_CONFIRMED
    record.confirmed_at_utc = journal.utc_now()
    record.start_attempts = 0
    record.record(
        ActivationRecord(
            at_utc=record.confirmed_at_utc,
            action="confirmed",
            from_version=record.previous_version,
            to_version=record.active_version,
            source="health_check",
        )
    )
    _persist(layout, record)
    journal.append_log(
        layout.update_log,
        "update_confirmed",
        version=record.active_version,
        previous_version=record.previous_version,
        dwell_seconds=trust.PROBATION_DWELL_SECONDS,
    )
    prune(layout, record)
    return record


def activate(
    layout: InstallLayout,
    release_version,
    *,
    authorized_by="",
    source="removable_media",
    mirror=None,
) -> ActivationResult:
    """Install a staged version and switch to it under supervised probation."""
    release_version = str(version.parse(release_version))
    previous = layout.active_version()
    if previous is None:
        raise ActivationError(
            "This installation does not use managed version slots, so it cannot be "
            "updated in place. Reinstall with the current install.sh first."
        )
    if previous == release_version:
        raise ActivationError(f"Version {release_version} is already active")
    record = journal.read_journal(layout.journal)
    if record.state == journal.STATE_PROBATION:
        raise ActivationError(
            "Wait until the running version is confirmed before another upgrade"
        )
    promote_staged(layout, release_version, installed_version=previous)
    record = journal.read_journal(layout.journal)
    record.state = journal.STATE_PROBATION
    record.previous_version = previous
    record.active_version = release_version
    record.activated_at_utc = journal.utc_now()
    record.confirmed_at_utc = ""
    record.start_attempts = 0
    record.record(
        ActivationRecord(
            at_utc=record.activated_at_utc,
            action="activated",
            from_version=previous,
            to_version=release_version,
            authorized_by=str(authorized_by)[:64],
            source=source,
        )
    )
    # The journal is written first on purpose: if power is lost between here and
    # the link swap, the launcher sees a probation entry whose rollback target is
    # the version that is still active, which resolves to no change at all.
    _persist(layout, record)
    _swap_link(layout, release_version)
    details = {
        "from_version": previous,
        "to_version": release_version,
        "authorized_by": str(authorized_by)[:64],
        "source": source,
    }
    journal.append_log(layout.update_log, "update_activated", **details)
    if mirror:
        mirror("update_activated", "INFO", **details)
    return ActivationResult("activated", previous, release_version)


def promote_staged(layout: InstallLayout, release_version, installed_version=None):
    """Move a verified staged executable into its immutable version slot."""
    release_version = str(release_version)
    slot_executable = layout.slot_executable(release_version)
    staged_dir = layout.staging_dir / release_version
    staged = staged_dir / trust.EXECUTABLE_NAME
    if not staged.is_file():
        raise ActivationError(
            f"No verified staged package for version {release_version} is available"
        )
    try:
        package = media.verify_local_package(staged_dir, release_version)
        reason = media.check_installable(
            package, installed_version or layout.active_version()
        )
        if reason:
            raise media.MediaError(reason)
        if slot_executable.is_symlink():
            raise media.MediaError("Refusing symbolic link for installed executable")
        if slot_executable.is_file():
            # A retained version slot must match the newly authenticated package,
            # never silently supersede it with a corrupt or unrelated executable.
            media.verify_artifact(replace(package, artifact=slot_executable))
            return slot_executable
        slot = layout.slot(release_version)
        if slot.exists() or slot.is_symlink():
            raise media.MediaError(
                "An incomplete version slot exists; administrator review required"
            )
        # Publish executable and signed evidence together. An interrupted
        # promotion must not leave an executable with missing verification data.
        os.replace(staged_dir, slot)
        slot_executable.chmod(0o700)
        _fsync_directory(slot)
        _fsync_directory(layout.versions_dir)
    except (OSError, media.MediaError) as exc:
        raise ActivationError(
            f"Could not verify or install version {release_version}: {exc}"
        ) from exc
    return slot_executable


def _unconfirmed_versions(record):
    """Exclude failed/trial payloads from recovery even when their slot remains."""
    pending = set()
    for entry in record.history:
        action, target = entry.get("action"), entry.get("to_version")
        if action == "activated":
            pending.add(target)
        elif action == "confirmed":
            pending.discard(target)
        elif action == "watchdog_rollback":
            pending.add(entry.get("from_version"))
    return pending


def rollback_candidates(layout: InstallLayout, record: Journal | None = None):
    """Prefer the last accepted version; never promote an arbitrary newer slot."""
    record = record or journal.read_journal(layout.journal)
    active = layout.active_version()
    if not version.try_parse(active):
        return ()
    blocked = _unconfirmed_versions(record)
    usable = []
    for name in layout.installed_versions():
        parsed = version.try_parse(name)
        path = layout.slot_executable(name)
        if (
            not parsed
            or name == active
            or name in blocked
            or layout.slot(name).is_symlink()
            or path.is_symlink()
        ):
            continue
        if name == record.previous_version or parsed < version.parse(active):
            usable.append(name)
    usable.sort(key=version.parse, reverse=True)
    if record.previous_version in usable:
        usable.remove(record.previous_version)
        usable.insert(0, record.previous_version)
    return tuple(usable)


def rollback_target(layout: InstallLayout, record: Journal | None = None):
    candidates = rollback_candidates(layout, record)
    return candidates[0] if candidates else None


def rollback(
    layout: InstallLayout,
    release_version=None,
    *,
    authorized_by="",
    mirror=None,
) -> ActivationResult:
    """Restore a previously installed version that is still present on disk."""
    record = journal.read_journal(layout.journal)
    target = str(release_version or rollback_target(layout, record) or "")
    if not target:
        raise ActivationError("No previous version is available on this terminal")
    if not version.try_parse(target) or not layout.slot_executable(target).is_file():
        raise ActivationError(
            f"Version {target} is no longer installed on this terminal"
        )
    current = layout.active_version()
    if target not in rollback_candidates(layout, record):
        raise ActivationError("This version is not an accepted rollback target")
    slot = layout.slot(target)
    if (slot / trust.MANIFEST_NAME).exists() or (slot / trust.SIGNATURE_NAME).exists():
        try:
            media.verify_local_package(slot, target)
        except (media.MediaError, OSError) as exc:
            raise ActivationError(f"Rollback verification failed: {exc}") from exc
    if current == target:
        raise ActivationError(f"Version {target} is already active")
    _swap_link(layout, target)
    record.state = journal.STATE_CONFIRMED
    record.previous_version = current or ""
    record.active_version = target
    record.activated_at_utc = journal.utc_now()
    record.confirmed_at_utc = record.activated_at_utc
    record.start_attempts = 0
    record.record(
        ActivationRecord(
            at_utc=record.activated_at_utc,
            action="rolled_back",
            from_version=current or "",
            to_version=target,
            authorized_by=str(authorized_by)[:64],
            source="operator",
        )
    )
    _persist(layout, record)
    details = {
        "from_version": current or "",
        "to_version": target,
        "authorized_by": str(authorized_by)[:64],
    }
    journal.append_log(layout.update_log, "update_rolled_back", "WARNING", **details)
    if mirror:
        mirror("update_rolled_back", "WARNING", **details)
    return ActivationResult("rolled_back", current or "", target)


def prune(layout: InstallLayout, record: Journal | None = None, keep=None):
    """Remove superseded slots, never touching the active or rollback version."""
    record = record or journal.read_journal(layout.journal)
    keep = trust.RETAINED_VERSION_SLOTS if keep is None else max(2, int(keep))
    # An empty name must not occupy a retention slot when there is no previous
    # version yet, or the newest superseded slot would be pruned one turn early.
    protected = {
        name
        for name in (layout.active_version(), rollback_target(layout, record))
        if name
    }
    installed = [
        name for name in layout.installed_versions() if version.try_parse(name)
    ]
    ordered = sorted(installed, key=version.parse, reverse=True)
    retained, removed = set(protected), []
    for name in ordered:
        if len(retained) < keep:
            retained.add(name)
    for name in ordered:
        if name in retained:
            continue
        shutil.rmtree(layout.slot(name), ignore_errors=True)
        removed.append(name)
    if removed:
        journal.append_log(
            layout.update_log, "update_slots_pruned", removed_versions=removed
        )
    return tuple(removed)


def discard_staging(layout: InstallLayout, release_version=None):
    """Delete staged candidates that were never authorized."""
    if release_version:
        shutil.rmtree(layout.staging_dir / str(release_version), ignore_errors=True)
        return
    shutil.rmtree(layout.staging_dir, ignore_errors=True)
    layout.staging_dir.mkdir(parents=True, exist_ok=True, mode=0o700)


def staged_versions(layout: InstallLayout):
    """Return staged candidate versions that are ready for authorization."""
    if not layout.staging_dir.is_dir():
        return ()
    found = []
    for path in sorted(layout.staging_dir.iterdir()):
        if (
            path.is_dir()
            and not path.is_symlink()
            and version.try_parse(path.name)
            and (path / trust.EXECUTABLE_NAME).is_file()
        ):
            found.append(path.name)
    return tuple(found)
