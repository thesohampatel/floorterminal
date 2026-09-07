"""Offline, signature-verified software updates for deployed terminals.

The subsystem is entirely additive to the production workflow. Reporting, timers,
state recovery, connectors, Settings, and the kiosk lifecycle behave identically
whether the update indicator is green, amber, or red, and whether the update
directories exist at all. Nothing here can block or delay a downtime report.

Trust flows in one direction only. Software is installed exclusively from removable
media whose manifest carries a detached Ed25519 signature made by a key compiled
into the running build, after an administrator authorizes the change on the
touchscreen. The optional network check is advisory: it can tell an operator that a
newer version exists, and can never deliver, choose, or trigger software.
"""

from __future__ import annotations

from .catalog import CATALOG, CatalogEntry, installed_entry, installed_features
from .installer import ActivationError, ActivationResult
from .layout import InstallLayout, install_root
from .manifest import ManifestError
from .media import MediaError
from .service import (
    LEVEL_ATTENTION,
    LEVEL_OK,
    LEVEL_UNKNOWN,
    RESTART_EXEC,
    RESTART_SUPERVISOR,
    RESTART_UNSUPPORTED,
    StagedUpdate,
    UpdateService,
    UpdateStatus,
)
from .version import Version, VersionError

__all__ = [
    "CATALOG",
    "LEVEL_ATTENTION",
    "LEVEL_OK",
    "LEVEL_UNKNOWN",
    "RESTART_EXEC",
    "RESTART_SUPERVISOR",
    "RESTART_UNSUPPORTED",
    "ActivationError",
    "ActivationResult",
    "CatalogEntry",
    "InstallLayout",
    "ManifestError",
    "MediaError",
    "StagedUpdate",
    "UpdateService",
    "UpdateStatus",
    "Version",
    "VersionError",
    "install_root",
    "installed_entry",
    "installed_features",
]
