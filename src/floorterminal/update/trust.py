"""Immutable update-channel policy compiled into every build.

Nothing in this module is configurable at runtime. The trusted signing keys, the
update endpoint, the accepted removable-media identity, and every safety bound are
fixed at build time so a deployed terminal cannot be redirected to an attacker's
update source by editing a file, a setting, an environment variable, or the
removable medium itself. Changing any value here requires a source change, review,
and a new audited build.
"""

from __future__ import annotations

from dataclasses import dataclass

from .signing import decode_key

#: Identifies the product an update package is allowed to replace. A package for
#: any other product identifier is rejected before it is copied to the terminal.
PRODUCT_ID = "floorterminal"

#: Platform/architecture pair a package must declare to be installable here.
SUPPORTED_TARGETS = ("linux/aarch64",)

#: Filename of the executable inside an installed version slot.
EXECUTABLE_NAME = "floorterminal"


@dataclass(frozen=True)
class TrustedKey:
    """One release-signing identity that this build accepts."""

    key_id: str
    public_key_base64: str
    valid_from_utc: str
    comment: str

    @property
    def public_key(self) -> bytes:
        return decode_key(self.public_key_base64)


#: Release-signing anchors. Multiple entries exist only to support key rotation:
#: an update signed by any listed key is accepted, so a retired key must be
#: removed here and the change shipped in a build before the key is destroyed.
TRUSTED_KEYS = (
    TrustedKey(
        key_id="ba1b79d27fddd67a",
        public_key_base64="Ff8PJdWWQ5r5GsQZLQpBvq7fz/3WN4Th4DXpW2mYN1I=",
        valid_from_utc="2026-09-03T02:48:56Z",
        comment="Soham Patel • primary offline release-signing key",
    ),
)

# ---------------------------------------------------------------------------
# Publication identity
# ---------------------------------------------------------------------------

#: Canonical public project location shown to operators and used for the optional
#: availability check. Every constant below is part of the signed build.
GITHUB_OWNER = "thesohampatel"
GITHUB_REPOSITORY = "floorterminal"
PROJECT_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPOSITORY}"
RELEASES_URL = f"{PROJECT_URL}/releases"
UPDATE_GUIDE_URL = f"{PROJECT_URL}/blob/main/docs/update-user-guide.md"
MAINTAINER_NAME = "Soham Patel"
MAINTAINER_EMAIL = "sohampatel1782@gmail.com"

#: The only host the availability check may contact, and the only URL it may use.
UPDATE_CHANNEL_HOST = "raw.githubusercontent.com"
UPDATE_CHANNEL_URL = (
    f"https://{UPDATE_CHANNEL_HOST}/{GITHUB_OWNER}/{GITHUB_REPOSITORY}"
    "/main/update-channel/latest.json"
)

# ---------------------------------------------------------------------------
# Removable-media identity
# ---------------------------------------------------------------------------

#: Accepted USB volume labels. FAT32 and exFAT limit a label to eleven characters,
#: so the primary label is deliberately short; the longer aliases exist for ext4
#: and NTFS media prepared by a managed deployment process.
UPDATE_VOLUME_LABELS = (
    "FLOORTERM",
    "FLOOR-TERM",
    "FTERM_UPD",
    "FT_UPDATE",
)

#: Directory that must exist on the medium; its name is part of the contract so an
#: unrelated drive that happens to share a label is still ignored.
UPDATE_PACKAGE_DIRNAME = "floorterminal-update"
MANIFEST_NAME = "update_manifest.json"
SIGNATURE_NAME = "update_manifest.json.sig"
MEDIA_LOG_DIRNAME = "update-log"

#: Mount roots scanned for removable media, in probe order.
MEDIA_ROOTS = ("/media", "/run/media", "/mnt", "/Volumes")

# ---------------------------------------------------------------------------
# Safety bounds
# ---------------------------------------------------------------------------

MAX_MANIFEST_BYTES = 64 * 1024
MAX_SIGNATURE_BYTES = 4 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MIN_ARTIFACT_BYTES = 1024 * 1024
#: Free space required beyond the artifact itself before staging is attempted.
STAGING_HEADROOM_BYTES = 256 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024

#: Retained installed version slots, including the running one. Older slots are
#: pruned only after a new version is confirmed healthy.
RETAINED_VERSION_SLOTS = 3

#: Consecutive supervised starts a freshly activated version may take before the
#: launcher restores the previous version automatically.
PROBATION_START_LIMIT = 3
#: Uninterrupted seconds a new version must run before it is marked confirmed.
PROBATION_DWELL_SECONDS = 120

#: Removable-media polling. Deliberately slow: this is a convenience trigger, not
#: a control path, and it must not compete with the touch workflow.
MEDIA_POLL_SECONDS = 6

#: Availability check bounds. The check is optional, never blocks the workflow,
#: and never runs more often than the minimum interval.
NETWORK_TIMEOUT_SECONDS = 6.0
MAX_CHANNEL_RESPONSE_BYTES = 64 * 1024
CHECK_INTERVAL_SECONDS = 6 * 60 * 60
CHECK_RETRY_SECONDS = 30 * 60
#: A cached result older than this is reported as stale rather than current.
CHECK_FRESHNESS_SECONDS = 14 * 24 * 60 * 60
USER_AGENT = "floorterminal-update-check/1"


def trusted_key(key_id):
    """Return the trusted key with ``key_id`` or ``None`` when it is not accepted."""
    for key in TRUSTED_KEYS:
        if key.key_id == str(key_id):
            return key
    return None
