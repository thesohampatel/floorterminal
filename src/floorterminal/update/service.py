"""Background coordination between removable media, the channel, and the console.

The service is deliberately passive with respect to the production workflow. It
runs on one daemon thread, publishes an immutable status snapshot under a lock, and
never calls into Tk. The user interface reads the snapshot during its normal render
pass, so an unreachable network, an unreadable drive, a damaged journal, or a
missing update directory can only ever change what the panel says — never whether
the terminal reports downtime.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field, replace

from .. import __version__
from . import catalog, installer, journal, media, remote, trust, version
from .installer import ActivationError
from .layout import InstallLayout
from .media import MediaError

LEVEL_OK = "ok"
LEVEL_ATTENTION = "attention"
LEVEL_UNKNOWN = "unknown"

RESTART_SUPERVISOR = "supervisor"
RESTART_EXEC = "exec"
RESTART_UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class StagedUpdate:
    """A verified package on this terminal that is waiting for authorization."""

    version: str
    release_title: str = ""
    release_summary: str = ""
    released_utc: str = ""
    artifact_sha256: str = ""
    signing_key_id: str = ""
    source_mount: str = ""
    highlights: tuple = ()


@dataclass(frozen=True)
class UpdateStatus:
    """Immutable snapshot describing everything the panel needs to draw."""

    level: str = LEVEL_UNKNOWN
    headline: str = "Update status not yet determined"
    detail: str = ""
    installed_version: str = __version__
    managed: bool = False
    state: str = journal.STATE_UNMANAGED
    checking: bool = False
    check_enabled: bool = True
    channel: remote.ChannelResult | None = None
    channel_error: str = ""
    channel_stale: bool = False
    update_available: bool = False
    latest_version: str = ""
    staged: StagedUpdate | None = None
    media_mount: str = ""
    media_error: str = ""
    rollback_version: str = ""
    activated_at_utc: str = ""
    previous_version: str = ""
    last_error: str = ""
    restart_required: bool = False
    candidate_versions: tuple = ()
    history: tuple = field(default_factory=tuple)

    @property
    def installed_features(self):
        return catalog.installed_features()

    @property
    def can_install(self):
        return bool(
            self.managed
            and self.staged
            and not self.restart_required
            and self.state != journal.STATE_PROBATION
        )

    @property
    def can_rollback(self):
        return bool(self.managed and self.rollback_version)


class UpdateService:
    """Owns update state for one running application instance."""

    def __init__(
        self, config=None, logger=None, layout=None, clock=None, media_roots=None
    ):
        self.config = config or {}
        self.logger = logger
        self.clock = clock or time.time
        self.layout = layout if layout is not None else InstallLayout.resolve()
        # Deliberately a constructor seam for the offline test suite only. It is
        # never read from configuration, the environment, or removable media, so a
        # deployed terminal always scans exactly the mount roots in ``trust``.
        self.media_roots = media_roots
        self.installed_version = __version__
        self._lock = threading.RLock()
        # Guards every operation that touches the staging directory, the version
        # slots, or the journal. The background scanner and an operator-authorized
        # activation both stage and promote files, so they must not interleave.
        self._install_lock = threading.RLock()
        self._status = UpdateStatus(installed_version=self.installed_version)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._next_check = 0.0
        self._check_lock = threading.Lock()
        self._started_monotonic = time.monotonic()
        self._confirmed = False
        self._journal = journal.Journal()
        self._channel = None
        self._channel_error = ""
        self._blocked_versions = set()
        self._candidate_versions = ()

    # ------------------------------------------------------------------ setup

    @property
    def check_enabled(self):
        return bool(self.config.get("software_update_check_enabled", True))

    def _log(self, event, level="INFO", **details):
        if self.logger is not None:
            try:
                self.logger.log(event, level, **details)
            except Exception:  # noqa: BLE001 - logging must never break the workflow
                return

    def prepare(self):
        """Reconcile on-disk state at startup and publish the first snapshot."""
        try:
            # The application holds its deployment single-instance lock at startup.
            for partial in self.layout.staging_dir.glob(".copy-*"):
                if partial.is_dir() and not partial.is_symlink():
                    shutil.rmtree(partial)
            self._journal = installer.initialise(self.layout, self.installed_version)
        except OSError as exc:
            self._journal = journal.Journal()
            self._set(last_error=f"Update state is unreadable: {exc}")
        self._channel = remote.load_cache(self.layout.remote_cache)
        self._refresh(scan_media=False)
        self._log(
            "update_subsystem_ready",
            installed_version=self.installed_version,
            managed=self.layout.managed,
            activation_state=self._journal.state,
            check_enabled=self.check_enabled,
        )
        return self.status()

    def start(self):
        """Start the single background worker; safe to call more than once."""
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._worker, name="update-service", daemon=True
        )
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._wake.set()

    # --------------------------------------------------------------- snapshot

    def status(self) -> UpdateStatus:
        with self._lock:
            return self._status

    def _set(self, **values):
        with self._lock:
            self._status = replace(self._status, **values)
            return self._status

    # ---------------------------------------------------------------- worker

    def _worker(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - a background fault is reportable, not fatal
                self._log("update_worker_failed", "WARNING", error=str(exc))
                self._set(last_error=str(exc)[:300])
            self._wake.wait(trust.MEDIA_POLL_SECONDS)
            self._wake.clear()

    def _tick(self):
        self._maybe_confirm()
        self._refresh(scan_media=True)
        if self.check_enabled and self.clock() >= self._next_check:
            self.check_channel()

    def _maybe_confirm(self):
        """Mark a probationary version healthy once it has run long enough."""
        if (
            self._confirmed
            or self._journal.state != journal.STATE_PROBATION
            or self.layout.active_version() != self.installed_version
        ):
            return
        if time.monotonic() - self._started_monotonic < trust.PROBATION_DWELL_SECONDS:
            return
        try:
            with self._install_lock:
                self._journal = installer.confirm(self.layout, self._journal)
            self._confirmed = True
            self._log(
                "update_version_confirmed",
                version=self._journal.active_version,
                previous_version=self._journal.previous_version,
            )
        except OSError as exc:
            self._log("update_confirmation_failed", "WARNING", error=str(exc))

    # ------------------------------------------------------------------ media

    def scan_media(self, labelled_only=True):
        """Look for an update medium and stage a verified package from it."""
        with self._install_lock:
            result = self._scan_media(labelled_only)
            staged, mount, error = result
            self._set(staged=staged, media_mount=mount, media_error=error)
            return result

    def _scan_media(self, labelled_only):
        self._blocked_versions = set()
        staged = self._staged_from_disk()
        errors = [self._staging_error] if self._staging_error else []
        candidates = []
        local = None
        if staged:
            local = media.read_package_directory(
                self.layout.staging_dir / staged.version
            )
            candidates.append(local)
        mounts = media.candidate_mounts(
            labelled_only=labelled_only, roots=self.media_roots
        )
        inspected = 0
        for mount in mounts[: media.MAX_MEDIA_ENTRIES]:
            try:
                directories = media.candidate_package_directories(mount)
            except MediaError as exc:
                errors.append(str(exc))
                continue
            for directory in directories:
                inspected += 1
                if inspected > media.MAX_MEDIA_ENTRIES:
                    errors.append(
                        "Too many update packages; keep at most 64 on connected media"
                    )
                    break
                try:
                    found = media.read_package_directory(directory, mount=mount)
                    if (
                        directory.name != trust.UPDATE_PACKAGE_DIRNAME
                        and directory.name != found.version
                    ):
                        raise MediaError(
                            "Version directory does not match its signed manifest"
                        )
                    candidates.append(found)
                except (MediaError, OSError) as exc:
                    errors.append(str(exc))
                    self._log(
                        "update_media_rejected",
                        "WARNING",
                        mount=str(mount),
                        error=str(exc),
                    )
            if inspected > media.MAX_MEDIA_ENTRIES:
                break
        if inspected > media.MAX_MEDIA_ENTRIES:
            self._candidate_versions = (staged.version,) if staged else ()
            return (
                staged,
                "",
                "Too many update packages; keep at most 64 on connected media",
            )
        grouped = {}
        for found in candidates:
            entries = grouped.setdefault(found.version, [])
            if entries and (
                entries[0].release != found.release
                or entries[0].package.target != found.package.target
            ):
                self._blocked_versions.add(found.version)
            entries.append(found)
        if self._blocked_versions:
            errors.append(
                "Conflicting signed contents for version(s): "
                + ", ".join(sorted(self._blocked_versions, key=version.parse))
            )
        self._candidate_versions = tuple(
            sorted(grouped, key=version.parse, reverse=True)
        )
        for name in self._candidate_versions:
            if name in self._blocked_versions:
                continue
            entries = grouped[name]
            reason = media.check_installable(entries[0], self.installed_version)
            if reason:
                errors.append(reason)
                continue
            for found in entries:
                mount_text = (
                    next((str(item.mount) for item in entries if item is not local), "")
                    if found is local
                    else str(found.mount)
                )
                try:
                    if staged and name == staged.version:
                        # The disk copy was just reauthenticated. The same signed
                        # package on a removed/damaged drive cannot alter that copy.
                        selected = replace(
                            staged, source_mount=mount_text or staged.source_mount
                        )
                    else:
                        media.verify_artifact(found)
                        media.stage(
                            self.layout,
                            found,
                            expect_executable=self._expect_executable(),
                        )
                        selected = self._describe_staged(name, mount_text)
                        journal.append_log(
                            self.layout.update_log,
                            "update_staged",
                            from_version=self.installed_version,
                            to_version=name,
                            signing_key_id=selected.signing_key_id,
                            source=mount_text,
                        )
                        self._log(
                            "update_package_staged",
                            version=name,
                            signing_key_id=selected.signing_key_id,
                            mount=mount_text,
                        )
                        media.mirror_log(
                            found.mount, "update_staged", staged_version=name
                        )
                    # Retain only the newest verified candidate after a successful
                    # replacement; unrelated deployment files are never involved.
                    for old in installer.staged_versions(self.layout):
                        if old != name:
                            installer.discard_staging(self.layout, old)
                    return (
                        selected,
                        selected.source_mount,
                        "; ".join(dict.fromkeys(errors))[:300],
                    )
                except (MediaError, OSError) as exc:
                    errors.append(str(exc))
                    self._log(
                        "update_media_rejected",
                        "WARNING",
                        mount=mount_text,
                        error=str(exc),
                    )
        return (
            None,
            str(mounts[0]) if mounts else "",
            "; ".join(dict.fromkeys(errors))[:300],
        )

    def _expect_executable(self):
        """Only enforce the Linux ELF check where the terminal actually runs Linux."""
        return platform.system() == "Linux"

    def _staged_from_disk(self):
        """Only describe candidates whose retained signature and payload verify."""
        previous_error = getattr(self, "_staging_error", "")
        self._staging_error = ""
        usable = [
            name
            for name in installer.staged_versions(self.layout)
            if version.try_parse(name)
            and version.is_newer(name, self.installed_version)
            and name not in self._blocked_versions
        ]
        for name in sorted(usable, key=version.parse, reverse=True):
            try:
                return self._describe_staged(name, "")
            except (MediaError, OSError) as exc:
                self._staging_error = f"Staged update rejected: {exc}. Reinsert the verified update drive."
                if self._staging_error != previous_error:
                    self._log("staged_update_rejected", "WARNING", error=str(exc))
        return None

    def _describe_staged(self, staged_version, mount_text):
        package = media.verify_local_package(
            self.layout.staging_dir / str(staged_version), staged_version
        )
        reason = media.check_installable(package, self.installed_version)
        if reason:
            raise MediaError(reason)
        release = package.release
        return StagedUpdate(
            version=release.version,
            release_title=release.release_title,
            release_summary=release.release_summary,
            released_utc=release.released_utc,
            artifact_sha256=release.artifact_sha256,
            signing_key_id=package.package.signing_key_id,
            source_mount=mount_text,
            highlights=release.highlights()[:12],
        )

    # ---------------------------------------------------------------- channel

    def check_channel(self, force=False):
        """Serialize checks so out-of-order responses cannot replace newer evidence."""
        if not self._check_lock.acquire(blocking=False):
            return self.status()
        try:
            return self._check_channel(force)
        finally:
            self._check_lock.release()

    def _check_channel(self, force=False):
        """Run one availability check; always returns, never raises."""
        if not self.check_enabled and not force:
            self._next_check = self.clock() + trust.CHECK_INTERVAL_SECONDS
            self._refresh(scan_media=False)
            return self.status()
        self._set(checking=True)
        now = self.clock()
        try:
            channel = remote.fetch_channel()
            result = remote.result_from_channel(channel, now)
            remote.validate_progression(result, self._channel)
            self._next_check = now + trust.CHECK_INTERVAL_SECONDS
            self._log(
                "update_check_completed",
                latest_version=result.version,
                signing_key_id=result.signing_key_id,
            )
            self._channel_error = ""
        except remote.ChannelError as exc:
            result = remote.failure_result(exc.outcome, str(exc), now)
            self._next_check = now + trust.CHECK_RETRY_SECONDS
            self._log(
                "update_check_failed", "WARNING", outcome=exc.outcome, error=str(exc)
            )
            self._channel_error = result.detail
        except Exception as exc:  # noqa: BLE001 - the check is never allowed to escalate
            result = remote.failure_result(remote.OUTCOME_UNAVAILABLE, str(exc), now)
            self._next_check = now + trust.CHECK_RETRY_SECONDS
            self._log(
                "update_check_failed", "WARNING", outcome="unavailable", error=str(exc)
            )
            self._channel_error = result.detail
        if result.successful or self._channel is None or not self._channel.successful:
            self._channel = result
            remote.save_cache(self.layout.remote_cache, result)
        else:
            # Keep the last signed, trustworthy answer visible. The failure is a
            # separate fact; changing the cached result's outcome would erase its
            # version from the Settings panel and contradict this policy.
            pass
        self._set(checking=False)
        return self._refresh(scan_media=False)

    # --------------------------------------------------------------- refresh

    def _refresh(self, scan_media=True):
        if scan_media:
            staged, mount_text, media_error = self.scan_media()
        else:
            # Without a fresh scan the medium's own findings stay as the last scan
            # left them; only the on-disk staging directory is re-read.
            previous = self.status()
            with self._install_lock:
                staged = self._staged_from_disk()
            if (
                staged
                and previous.staged
                and staged.version == previous.staged.version
                and staged.artifact_sha256 == previous.staged.artifact_sha256
            ):
                staged = replace(staged, source_mount=previous.staged.source_mount)
            mount_text = previous.media_mount
            media_error = self._staging_error or previous.media_error
        record = self._journal
        managed = self.layout.managed
        channel = self._channel
        latest = channel.version if channel and channel.successful else ""
        stale = bool(channel and channel.successful and channel.is_stale(self.clock()))
        available = bool(
            latest
            and version.try_parse(latest)
            and version.is_newer(latest, self.installed_version)
        )
        level, headline, detail = self._classify(
            managed,
            record,
            staged,
            media_error,
            channel,
            stale,
            available,
            self._channel_error,
        )
        restart_required = bool(
            managed and self.layout.active_version() != self.installed_version
        )
        if restart_required:
            level, headline, detail = (
                LEVEL_ATTENTION,
                "Restart required to complete the version change",
                "The active slot has changed. Restart this terminal before another upgrade.",
            )
        return self._set(
            restart_required=restart_required,
            candidate_versions=self._candidate_versions,
            level=level,
            headline=headline,
            detail=detail,
            installed_version=self.installed_version,
            managed=managed,
            state=record.state,
            check_enabled=self.check_enabled,
            channel=channel,
            channel_error=self._channel_error,
            channel_stale=stale,
            update_available=available,
            latest_version=latest,
            staged=staged,
            media_mount=mount_text,
            media_error=media_error,
            rollback_version=installer.rollback_target(self.layout, record) or ""
            if managed
            else "",
            activated_at_utc=record.activated_at_utc,
            previous_version=record.previous_version,
            history=tuple(record.history[-12:]),
        )

    def _classify(
        self,
        managed,
        record,
        staged,
        media_error,
        channel,
        stale,
        available,
        channel_error,
    ):
        """Derive the single indicator colour, in fixed priority order."""
        if record.state == journal.STATE_ROLLED_BACK and record.last_action in {
            "watchdog_rollback"
        }:
            return (
                LEVEL_UNKNOWN,
                "Previous version restored automatically",
                (
                    f"Version {record.active_version} is running because a newer "
                    "version did not start. Contact the maintainer before retrying "
                    "the update."
                ),
            )
        if record.state == journal.STATE_PROBATION:
            return (
                LEVEL_ATTENTION,
                f"Version {record.active_version} is on trial",
                "Wait for automatic confirmation before another upgrade. Rollback remains available.",
            )
        if staged:
            detail = "Newest compatible verified package. An administrator must authorize installation."
            if available and version.is_newer(channel.version, staged.version):
                detail += f" Channel recommends {channel.version}; this drive provides {staged.version}."
            if media_error:
                detail += f" Other packages skipped: {media_error}"
            return (
                LEVEL_ATTENTION,
                f"Version {staged.version} is verified and ready to install",
                detail,
            )
        if media_error:
            return LEVEL_UNKNOWN, "Update medium was rejected", media_error
        if channel_error and channel and channel.successful:
            return (
                LEVEL_ATTENTION,
                "Latest update check failed; verified information is retained",
                f"{channel_error} Last verified at {channel.checked_at_utc}: version {channel.version}.",
            )
        if stale:
            return (
                LEVEL_ATTENTION,
                "Update information is out of date",
                f"Last verified at {channel.checked_at_utc}: version {channel.version}. Check again.",
            )
        if available:
            minimum = version.try_parse(channel.minimum_upgradable_version)
            if minimum and version.parse(self.installed_version) < minimum:
                return (
                    LEVEL_ATTENTION,
                    f"Version {channel.version} needs an intermediate upgrade",
                    (
                        f"This terminal runs {self.installed_version}. Install a compatible release "
                        f"at least {minimum} first, then rescan the drive."
                    ),
                )
            return (
                LEVEL_ATTENTION,
                f"Version {channel.version} is available",
                f"This terminal runs {self.installed_version}. Prepare a signed update drive.",
            )
        if not self.check_enabled:
            return (
                LEVEL_ATTENTION,
                "Update availability check is turned off",
                (
                    "This terminal cannot tell whether a newer version exists. Check "
                    "the project releases page manually, or enable the check in "
                    "Settings."
                ),
            )
        if channel is None:
            return (
                LEVEL_UNKNOWN,
                "Update availability has not been checked yet",
                (
                    "The first check runs shortly after startup. The console works "
                    "normally whether or not it succeeds."
                ),
            )
        if not channel.successful:
            return (
                LEVEL_UNKNOWN,
                "Update availability could not be checked",
                channel.detail
                or (
                    "The update channel is unreachable from this terminal. Reporting "
                    "and every other function are unaffected."
                ),
            )
        if stale:
            return (
                LEVEL_ATTENTION,
                "Update information is out of date",
                (
                    f"The last successful check was {channel.checked_at_utc}. The "
                    "result below may no longer be accurate."
                ),
            )
        if version.is_newer(self.installed_version, channel.version):
            return (
                LEVEL_ATTENTION,
                "Running version is newer than the recommended release",
                (
                    f"This terminal runs {self.installed_version}; the signed channel recommends "
                    f"{channel.version}. No automatic downgrade is offered."
                ),
            )
        note = "" if managed else " In-place updates need a managed installation."
        return (
            LEVEL_OK,
            f"Version {self.installed_version} is up to date",
            f"Checked against the published release channel at {channel.checked_at_utc}."
            + note,
        )

    # ----------------------------------------------------------------- actions

    def request_scan(self):
        """Wake the worker immediately, for example after an operator touch."""
        self._wake.set()

    def refresh(self, scan_media=False) -> UpdateStatus:
        """Recompute and publish the snapshot from current on-disk state."""
        return self._refresh(scan_media=scan_media)

    def install_staged(
        self, authorized_by="", *, expected_version=None, expected_sha256=None
    ):
        """Activate the verified staged version. Raises :class:`ActivationError`."""
        status = self.status()
        staged = status.staged
        if staged is None:
            raise ActivationError("No verified update is staged on this terminal")
        if not status.managed:
            raise ActivationError(
                "This installation runs a fixed executable rather than managed "
                "version slots, so it cannot be updated in place. Reinstall with the "
                "current install.sh, then retry."
            )
        mount = staged.source_mount

        def mirror(event, level="INFO", **details):
            if mount:
                media.mirror_log(mount, event, level, **details)

        with self._install_lock:
            fresh = self._staged_from_disk()
            if (
                fresh is None
                or fresh.version != (expected_version or staged.version)
                or fresh.artifact_sha256 != (expected_sha256 or staged.artifact_sha256)
            ):
                raise ActivationError(
                    "The selected update changed; review and authorize it again"
                )
            if self.layout.active_version() != self.installed_version:
                raise ActivationError("Restart this terminal before another upgrade")
            result = installer.activate(
                self.layout,
                fresh.version,
                authorized_by=authorized_by,
                source=mount or "removable_media",
                mirror=mirror,
            )
            self._journal = journal.read_journal(self.layout.journal)
        self._confirmed = False
        self._refresh(scan_media=False)
        self._log(
            "update_installed",
            from_version=result.from_version,
            to_version=result.to_version,
            authorized_by=authorized_by,
        )
        return result

    def rollback(self, authorized_by="", target=None):
        """Restore the previous installed version. Raises :class:`ActivationError`."""
        status = self.status()
        if not status.managed:
            raise ActivationError(
                "This installation does not use managed version slots, so it cannot "
                "roll back automatically."
            )
        with self._install_lock:
            result = installer.rollback(
                self.layout, target, authorized_by=authorized_by, mirror=None
            )
            self._journal = journal.read_journal(self.layout.journal)
        self._confirmed = True
        self._refresh(scan_media=False)
        self._log(
            "update_rolled_back",
            "WARNING",
            from_version=result.from_version,
            to_version=result.to_version,
            authorized_by=authorized_by,
        )
        return result

    def discard_staged(self):
        with self._install_lock:
            installer.discard_staging(self.layout)
        self._refresh(scan_media=False)

    def restart_mechanism(self):
        """Describe how this process can hand control to the newly active version."""
        if os.environ.get("INVOCATION_ID") or os.environ.get(
            "FLOORTERMINAL_SUPERVISED"
        ):
            return RESTART_SUPERVISOR
        if getattr(sys, "frozen", False) and self.layout.active_link.exists():
            return RESTART_EXEC
        return RESTART_UNSUPPORTED

    def restart(self):
        """Replace this process with the active version. Does not return on success."""
        mechanism = self.restart_mechanism()
        self.stop()
        if mechanism == RESTART_EXEC:
            target = str(self.layout.active_link)
            os.execv(target, [target])
        raise SystemExit(0)
