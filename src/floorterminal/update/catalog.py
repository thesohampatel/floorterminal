"""Release feature catalog compiled into the application.

The Software Update panel must describe the running version truthfully with no
network, no removable medium, and no writable data file. This catalog is therefore
part of the build: what it says about the installed version is exactly what was
reviewed when that version was released.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import __version__


@dataclass(frozen=True)
class CatalogEntry:
    """One released version and the capabilities it delivers."""

    version: str
    released_utc: str
    title: str
    summary: str
    features: tuple[str, ...]


CATALOG = (
    CatalogEntry(
        version="1.0.0",
        released_utc="2026-08-31T00:00:00Z",
        title="First public open-source release",
        summary=(
            "Provider-neutral line-side reporting and first-response console for "
            "Raspberry Pi touchscreen kiosks and desktop evaluation."
        ),
        # Each entry is written to fit one line of the Software Update panel.
        features=(
            "Touch selection of any stations or the entire line",
            "Per-station failure lists with automatic Others note",
            "Local-first unplanned and planned Engineering workflows",
            "Responders editable while repair remains active",
            "Downtime, repair, escalation, and micro-stop timers",
            "Message-only Engineering, Quality, Production requests",
            "Typed Connector v1 mappings with capability isolation",
            "Durable rate-limited sync with idempotent create retry",
            "Strict state recovery and dated private audit logs",
            "PBKDF2 Settings unlock and authorized kiosk controls",
            "Responsive 7-inch, 10.1-inch, and desktop layouts",
            "Signed offline USB updates with one-touch rollback",
        ),
    ),
)

_BY_VERSION = {entry.version: entry for entry in CATALOG}


def entry_for(release_version=None):
    """Return the catalog entry for ``release_version`` or ``None`` when unknown."""
    return _BY_VERSION.get(str(release_version or __version__))


def installed_entry():
    """Return the catalog entry describing the running build."""
    return entry_for(__version__)


def installed_features():
    """Return the feature list for the running build, never raising."""
    entry = installed_entry()
    return entry.features if entry else ()
