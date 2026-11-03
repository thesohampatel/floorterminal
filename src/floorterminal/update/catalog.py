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
        version="1.2.0",
        released_utc="",
        title="Development preview — not released",
        summary=(
            "Configurable request budgets, bounded retained rendering, immediate "
            "touch feedback, adaptive layouts and durable background delivery. "
            "No release is published yet."
        ),
        features=(
            "Configurable rolling-minute application request budget",
            "Local-first incident and planned Engineering workflows",
            "Atomic line release with durable, retried follow-ups",
            "Independent background delivery and restart recovery",
            "Protected review of uncertain external writes",
            "Cached crew directory with explicit offline choices",
            "Retained canvas rendering with bounded image caching",
            "Single animation timer with hidden-screen backoff",
            "Touch acknowledgment and persistent operation feedback",
            "Rounded Settings pages within the application window",
            "Portrait/landscape reflow and touch-sized station pages",
            "Bounded dialogs and Settings that preserve unsaved edits",
            "Per-station failures and editable responder assignments",
            "Connector v1 mappings and independent capabilities",
            "Signed offline USB updates with one-touch rollback",
        ),
    ),
    CatalogEntry(
        version="1.1.0",
        released_utc="2026-09-29T00:00:00Z",
        title="Reliable completion and sharper touchscreen",
        summary=(
            "Atomic, retry-safe line release, durable notifications, specific "
            "error messages, editable chat names, and anti-aliased rendering."
        ),
        features=(
            "Touch selection of any stations or the entire line",
            "Per-station failure lists with automatic Others note",
            "Local-first unplanned and planned Engineering workflows",
            "Atomic line release with durable, retried follow-ups",
            "Notifications queued through rate limits and restarts",
            "Asset notes with stations, reasons, and operator notes",
            "Specific, persistent explanations of failed actions",
            "Downtime, repair, escalation, and micro-stop timers",
            "Editable team and chat names with directory hints",
            "Typed Connector v1 mappings with capability isolation",
            "Anti-aliased, DPI-independent 7-inch to desktop layouts",
            "Signed offline USB updates with one-touch rollback",
        ),
    ),
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
