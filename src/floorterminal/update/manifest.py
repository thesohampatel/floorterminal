"""Strict, fail-closed parsing of signed update metadata.

Update metadata always arrives from outside the trust boundary: a removable drive
carried through a factory, or an HTTPS response. It is therefore parsed with an
exact allow-list of keys, bounded lengths, bounded list sizes, and no coercion.
Anything unexpected raises :class:`ManifestError` instead of being ignored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import trust, version
from .signing import SignatureError, decode_signature, verify

SCHEMA_VERSION = 1
PACKAGE_DOCUMENT = "update_package"
CHANNEL_DOCUMENT = "update_channel"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_KEY_ID = re.compile(r"^[0-9a-f]{8,64}$")

_MAX_TITLE = 90
_MAX_SUMMARY = 400
_MAX_ITEM = 160
_MAX_ITEMS = 24
_MAX_URL = 200


class ManifestError(ValueError):
    """Raised when update metadata is malformed, unsupported, or untrusted."""


def _text(data, key, maximum, *, required=True, default=""):
    if key not in data:
        if required:
            raise ManifestError(f"Update metadata is missing '{key}'")
        return default
    value = data[key]
    if not isinstance(value, str):
        raise ManifestError(f"Update metadata field '{key}' must be text")
    value = value.strip()
    if required and not value:
        raise ManifestError(f"Update metadata field '{key}' cannot be empty")
    if len(value) > maximum:
        raise ManifestError(
            f"Update metadata field '{key}' exceeds {maximum} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ManifestError(
            f"Update metadata field '{key}' contains control characters"
        )
    return value


def _string_list(data, key):
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ManifestError(f"Update metadata field '{key}' must be a list")
    if len(value) > _MAX_ITEMS:
        raise ManifestError(
            f"Update metadata field '{key}' exceeds {_MAX_ITEMS} entries"
        )
    items = []
    for entry in value:
        if not isinstance(entry, str):
            raise ManifestError(f"Update metadata field '{key}' must contain only text")
        text = " ".join(entry.split())
        if not text:
            continue
        if len(text) > _MAX_ITEM:
            raise ManifestError(f"An entry in '{key}' exceeds {_MAX_ITEM} characters")
        if any(ord(character) < 32 or ord(character) == 127 for character in text):
            raise ManifestError(f"An entry in '{key}' contains control characters")
        items.append(text)
    return tuple(items)


def _timestamp(data, key):
    value = _text(data, key, 20)
    if not _TIMESTAMP.match(value):
        raise ManifestError(f"'{key}' must use the form YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ManifestError(f"'{key}' is not a real UTC timestamp: {exc}") from exc
    return value


def _digest(data, key):
    value = _text(data, key, 64)
    if not _SHA256.match(value):
        raise ManifestError(f"'{key}' must be a lowercase 64-character SHA-256 digest")
    return value


def _size(data, key, minimum, maximum):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"'{key}' must be a whole number of bytes")
    if not minimum <= value <= maximum:
        raise ManifestError(f"'{key}' must be between {minimum} and {maximum} bytes")
    return value


def _url(data, key, *, required=False):
    value = _text(data, key, _MAX_URL, required=required)
    if not value:
        return ""
    if not value.startswith(f"{trust.PROJECT_URL}/"):
        raise ManifestError(f"'{key}' must reference the official project repository")
    return value


def _reject_unknown(data, allowed, label):
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ManifestError(
            f"{label} contains unsupported fields: {', '.join(unknown)}"
        )


def _require_object(value, label):
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be one JSON object")
    return value


@dataclass(frozen=True)
class ReleaseRecord:
    """Operator-facing description of one published release."""

    version: str
    released_utc: str
    release_title: str
    release_summary: str
    minimum_upgradable_version: str
    artifact_name: str
    artifact_sha256: str
    artifact_size_bytes: int
    notes_url: str = ""
    features: tuple[str, ...] = field(default_factory=tuple)
    fixes: tuple[str, ...] = field(default_factory=tuple)
    security: tuple[str, ...] = field(default_factory=tuple)

    @property
    def parsed_version(self):
        return version.parse(self.version)

    def highlights(self):
        """Return labelled change entries in a fixed operator-facing order."""
        return (
            *(("NEW", item) for item in self.features),
            *(("FIX", item) for item in self.fixes),
            *(("SECURITY", item) for item in self.security),
        )


_RELEASE_KEYS = (
    "version",
    "released_utc",
    "release_title",
    "release_summary",
    "minimum_upgradable_version",
    "artifact",
    "notes_url",
    "features",
    "fixes",
    "security",
)
_ARTIFACT_KEYS = ("name", "sha256", "size_bytes")


def _release(data, label) -> ReleaseRecord:
    _require_object(data, label)
    _reject_unknown(data, _RELEASE_KEYS, label)
    release_version = _text(data, "version", 24)
    minimum = _text(data, "minimum_upgradable_version", 24)
    try:
        parsed = version.parse(release_version)
        minimum_parsed = version.parse(minimum)
        if minimum_parsed > parsed:
            raise version.VersionError(
                "Minimum upgrade version exceeds the release version"
            )
    except version.VersionError as exc:
        raise ManifestError(str(exc)) from exc
    artifact = _require_object(data.get("artifact"), f"{label} 'artifact'")
    _reject_unknown(artifact, _ARTIFACT_KEYS, f"{label} 'artifact'")
    name = _text(artifact, "name", 64)
    if name != trust.EXECUTABLE_NAME:
        raise ManifestError(
            f"Update artifact must be named '{trust.EXECUTABLE_NAME}', not {name!r}"
        )
    return ReleaseRecord(
        version=str(parsed),
        released_utc=_timestamp(data, "released_utc"),
        release_title=_text(data, "release_title", _MAX_TITLE),
        release_summary=_text(data, "release_summary", _MAX_SUMMARY),
        minimum_upgradable_version=str(version.parse(minimum)),
        artifact_name=name,
        artifact_sha256=_digest(artifact, "sha256"),
        artifact_size_bytes=_size(
            artifact, "size_bytes", trust.MIN_ARTIFACT_BYTES, trust.MAX_ARTIFACT_BYTES
        ),
        notes_url=_url(data, "notes_url"),
        features=_string_list(data, "features"),
        fixes=_string_list(data, "fixes"),
        security=_string_list(data, "security"),
    )


@dataclass(frozen=True)
class UpdatePackage:
    """A verified update package described by removable media."""

    release: ReleaseRecord
    target: str
    signing_key_id: str


@dataclass(frozen=True)
class ChannelDocument:
    """A verified availability announcement fetched from the update channel."""

    release: ReleaseRecord
    published_utc: str
    targets: tuple[str, ...]
    archive_name: str
    archive_sha256: str
    signing_key_id: str
    document_bytes: bytes = b""
    signature_bytes: bytes = b""


_PACKAGE_KEYS = ("schema_version", "document_type", "product_id", "target", "release")
_CHANNEL_KEYS = (
    "schema_version",
    "document_type",
    "product_id",
    "published_utc",
    "targets",
    "archive",
    "release",
)
_ARCHIVE_KEYS = ("name", "sha256")


def _envelope(data, document_type, allowed):
    _require_object(data, "Update metadata")
    _reject_unknown(data, allowed, "Update metadata")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(
            f"Unsupported update metadata schema_version; expected {SCHEMA_VERSION}"
        )
    if data.get("document_type") != document_type:
        raise ManifestError(
            f"Expected a '{document_type}' document, found "
            f"{str(data.get('document_type'))[:32]!r}"
        )
    if data.get("product_id") != trust.PRODUCT_ID:
        raise ManifestError(
            f"Update metadata is for another product: {str(data.get('product_id'))[:48]!r}"
        )


def parse_package(raw: bytes) -> UpdatePackage:
    """Validate the manifest bytes carried on removable media."""
    data = _decode(raw, trust.MAX_MANIFEST_BYTES)
    _envelope(data, PACKAGE_DOCUMENT, _PACKAGE_KEYS)
    target = _text(data, "target", 32)
    if target not in trust.SUPPORTED_TARGETS:
        raise ManifestError(
            f"Update package targets {target!r}; this build installs only "
            + ", ".join(trust.SUPPORTED_TARGETS)
        )
    return UpdatePackage(
        release=_release(data.get("release"), "Update package 'release'"),
        target=target,
        signing_key_id="",
    )


def parse_channel(raw: bytes) -> ChannelDocument:
    """Validate an availability announcement retrieved from the update channel."""
    data = _decode(raw, trust.MAX_CHANNEL_RESPONSE_BYTES)
    _envelope(data, CHANNEL_DOCUMENT, _CHANNEL_KEYS)
    targets = _string_list(data, "targets")
    if not targets or not set(targets).intersection(trust.SUPPORTED_TARGETS):
        raise ManifestError("Update channel declares no supported target")
    archive = _require_object(data.get("archive"), "Update channel 'archive'")
    _reject_unknown(archive, _ARCHIVE_KEYS, "Update channel 'archive'")
    return ChannelDocument(
        release=_release(data.get("release"), "Update channel 'release'"),
        published_utc=_timestamp(data, "published_utc"),
        targets=targets,
        archive_name=_text(archive, "name", 120),
        archive_sha256=_digest(archive, "sha256"),
        signing_key_id="",
    )


def _decode(raw: bytes, maximum: int):
    if not isinstance(raw, (bytes, bytearray)):
        raise ManifestError("Update metadata must be supplied as bytes")
    if len(raw) > maximum:
        raise ManifestError(f"Update metadata exceeds the {maximum}-byte safety limit")
    try:
        return json.loads(bytes(raw).decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ManifestError("Update metadata is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"Update metadata is not valid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc


_SIGNATURE_KEYS = ("schema_version", "algorithm", "key_id", "signature")


def verify_signature(document: bytes, signature_raw: bytes) -> str:
    """Verify a detached signature over ``document`` and return the trusted key id.

    The exact bytes of the metadata file are the signed message, so no canonical
    re-serialization is involved and a signature cannot survive any edit.
    """
    data = _decode(signature_raw, trust.MAX_SIGNATURE_BYTES)
    _require_object(data, "Update signature")
    _reject_unknown(data, _SIGNATURE_KEYS, "Update signature")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError("Unsupported update signature schema_version; expected 1")
    if data.get("algorithm") != "ed25519":
        raise ManifestError("Update signatures must use the ed25519 algorithm")
    key_id = _text(data, "key_id", 64)
    if not _KEY_ID.match(key_id):
        raise ManifestError("Update signature key_id is malformed")
    key = trust.trusted_key(key_id)
    if key is None:
        raise ManifestError(
            f"Update is signed by key {key_id} which this build does not trust"
        )
    try:
        signature = decode_signature(_text(data, "signature", 200))
    except SignatureError as exc:
        raise ManifestError(str(exc)) from exc
    if not verify(key.public_key, bytes(document), signature):
        raise ManifestError(
            "Update signature does not match the metadata; the file was altered "
            "or was not produced by the maintainer"
        )
    return key_id


def _enforce_key_validity(key_id: str, *timestamps: str):
    """Reject otherwise valid metadata that predates its signing key."""
    key = trust.trusted_key(key_id)
    try:
        valid_from = datetime.strptime(
            key.valid_from_utc, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        claims = [
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            for value in timestamps
        ]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ManifestError("Trusted signing-key validity policy is invalid") from exc
    if any(claim < valid_from for claim in claims):
        raise ManifestError(
            f"Update metadata predates the validity of signing key {key_id}"
        )


def load_verified_package(document: bytes, signature_raw: bytes) -> UpdatePackage:
    """Verify the signature first, then parse the removable-media manifest."""
    key_id = verify_signature(document, signature_raw)
    package = parse_package(document)
    _enforce_key_validity(key_id, package.release.released_utc)
    return UpdatePackage(package.release, package.target, key_id)


def load_verified_channel(document: bytes, signature_raw: bytes) -> ChannelDocument:
    """Verify the signature first, then parse the availability announcement."""
    key_id = verify_signature(document, signature_raw)
    channel = parse_channel(document)
    _enforce_key_validity(key_id, channel.release.released_utc, channel.published_utc)
    return ChannelDocument(
        channel.release,
        channel.published_utc,
        channel.targets,
        channel.archive_name,
        channel.archive_sha256,
        key_id,
        bytes(document),
        bytes(signature_raw),
    )
