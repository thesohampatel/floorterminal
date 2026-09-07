"""Managed installation layout for atomically switchable version slots.

A managed installation keeps every deployed executable in its own immutable slot
and exposes the active one through a single symbolic link::

    /opt/floorterminal/
        floorterminal          -> versions/1.0.0/floorterminal
        bin/floorterminal-launch                    supervised launcher and boot watchdog
        versions/<version>/               one immutable slot per installed version
        update/staging/                   verified candidate before activation
        update/boot_state                 launcher-readable activation journal
        update/journal.json               full activation history for the console
        update/update-log.jsonl           append-only operator-visible update log
        config.json  connector.json  response_state.json  logs/   deployment data

Deployment data lives beside the link and is never read, moved, or rewritten by an
update. Switching versions therefore only replaces one symbolic link, which is a
single atomic ``rename`` on POSIX: an interrupted update always leaves either the
old slot or the new slot active, never a partially written executable.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ..core.paths import RUNTIME_ROOT
from . import trust

VERSIONS_DIRNAME = "versions"
UPDATE_DIRNAME = "update"
STAGING_DIRNAME = "staging"
LAUNCHER_DIRNAME = "bin"
LAUNCHER_NAME = "floorterminal-launch"


def _is_slot_executable(executable: Path) -> bool:
    """Detect ``<root>/versions/<version>/<executable>`` without trusting names."""
    parent = executable.parent
    return parent.parent.name == VERSIONS_DIRNAME and bool(parent.name)


def install_root() -> Path:
    """Return the deployment root that owns configuration, state, and logs.

    ``core.paths`` already resolves the runtime root from the executable, but a
    managed installation runs the executable from inside a version slot. The slot
    layout is recognised explicitly so configuration never migrates into a slot and
    disappears at the next activation, even when the launcher is bypassed.
    """
    override = os.environ.get("FLOORTERMINAL_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if _is_slot_executable(executable):
            return executable.parent.parent.parent
    return Path(RUNTIME_ROOT)


@dataclass(frozen=True)
class InstallLayout:
    """Resolved paths for one deployment root."""

    root: Path

    @classmethod
    def resolve(cls, root=None) -> InstallLayout:
        return cls(Path(root) if root is not None else install_root())

    @property
    def active_link(self) -> Path:
        return self.root / trust.EXECUTABLE_NAME

    @property
    def versions_dir(self) -> Path:
        return self.root / VERSIONS_DIRNAME

    @property
    def update_dir(self) -> Path:
        return self.root / UPDATE_DIRNAME

    @property
    def staging_dir(self) -> Path:
        return self.update_dir / STAGING_DIRNAME

    @property
    def launcher(self) -> Path:
        return self.root / LAUNCHER_DIRNAME / LAUNCHER_NAME

    @property
    def boot_state(self) -> Path:
        return self.update_dir / "boot_state"

    @property
    def journal(self) -> Path:
        return self.update_dir / "journal.json"

    @property
    def update_log(self) -> Path:
        return self.update_dir / "update-log.jsonl"

    @property
    def remote_cache(self) -> Path:
        return self.update_dir / "channel_cache.json"

    def slot(self, release_version) -> Path:
        """Return the immutable directory for one installed version."""
        name = str(release_version).strip()
        # Slot names come from validated version strings; the guard keeps a future
        # caller from turning metadata into a path traversal.
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError(f"Unsafe version slot name: {release_version!r}")
        return self.versions_dir / name

    def slot_executable(self, release_version) -> Path:
        return self.slot(release_version) / trust.EXECUTABLE_NAME

    def installed_versions(self):
        """Return every version slot that currently holds an executable."""
        if not self.versions_dir.is_dir():
            return ()
        found = []
        for path in sorted(self.versions_dir.iterdir()):
            if path.is_dir() and (path / trust.EXECUTABLE_NAME).is_file():
                found.append(path.name)
        return tuple(found)

    def active_version(self):
        """Return the version the active link resolves to, or ``None``."""
        link = self.active_link
        try:
            if not link.is_symlink():
                return None
            target = Path(os.readlink(link))
            if not target.is_absolute():
                target = (link.parent / target).resolve()
            if _is_slot_executable(target):
                return target.parent.name
        except OSError:
            return None
        return None

    @property
    def managed(self) -> bool:
        """Whether this deployment uses switchable slots and can be updated."""
        return self.active_version() is not None

    def ensure_directories(self):
        """Create the update working directories with owner-only permissions."""
        for path in (self.versions_dir, self.update_dir, self.staging_dir):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self
