"""Shared offline builders for the software-update test suite.

Every fixture signs with an ephemeral key generated inside the test process, so the
suite proves the verification path without embedding, needing, or exposing the real
maintainer release key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

from floorterminal.update import manifest, signing, trust

RELEASE_NOTES = {
    "release_title": "Reliability and offline update improvements",
    "release_summary": "Adds supervised offline updates and clearer synchronization badges.",
    "features": ["Signed offline USB software updates", "One-touch verified rollback"],
    "fixes": ["Sync badge no longer flickers during a retry"],
    "security": ["Update metadata must carry a maintainer signature"],
}


def make_key():
    """Return one ephemeral signing identity plus its trust-anchor entry."""
    seed = secrets.token_bytes(32)
    public = signing.public_key_from_seed(seed)
    key_id = hashlib.sha256(public).hexdigest()[:16]
    anchor = trust.TrustedKey(
        key_id=key_id,
        public_key_base64=base64.b64encode(public).decode("ascii"),
        valid_from_utc="2026-01-01T00:00:00Z",
        comment="offline test key",
    )
    return seed, key_id, anchor


def encode(document) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sign_document(seed, key_id, payload: bytes) -> bytes:
    return encode(
        {
            "schema_version": manifest.SCHEMA_VERSION,
            "algorithm": "ed25519",
            "key_id": key_id,
            "signature": base64.b64encode(signing.sign(seed, payload)).decode("ascii"),
        }
    )


def executable_bytes(marker="test", size=trust.MIN_ARTIFACT_BYTES + 512):
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = (183).to_bytes(2, "little")
    body = bytes(header) + marker.encode("ascii")
    return body + b"\x00" * (size - len(body))


def release_document(version="1.1.0", *, artifact=b"", minimum="1.0.0", **overrides):
    values = {**RELEASE_NOTES, **overrides}
    return {
        "version": version,
        "released_utc": "2026-11-14T09:00:00Z",
        "release_title": values["release_title"],
        "release_summary": values["release_summary"],
        "minimum_upgradable_version": minimum,
        "artifact": {
            "name": trust.EXECUTABLE_NAME,
            "sha256": hashlib.sha256(artifact).hexdigest(),
            "size_bytes": len(artifact),
        },
        "notes_url": f"{trust.RELEASES_URL}/tag/v{version}",
        "features": list(values["features"]),
        "fixes": list(values["fixes"]),
        "security": list(values["security"]),
    }


def package_document(version="1.1.0", *, artifact=b"", target=None, **overrides):
    return {
        "schema_version": manifest.SCHEMA_VERSION,
        "document_type": manifest.PACKAGE_DOCUMENT,
        "product_id": trust.PRODUCT_ID,
        "target": target or trust.SUPPORTED_TARGETS[0],
        "release": release_document(version, artifact=artifact, **overrides),
    }


def channel_document(version="1.1.0", *, artifact=b"", **overrides):
    return {
        "schema_version": manifest.SCHEMA_VERSION,
        "document_type": manifest.CHANNEL_DOCUMENT,
        "product_id": trust.PRODUCT_ID,
        "published_utc": "2026-11-14T09:05:00Z",
        "targets": list(trust.SUPPORTED_TARGETS),
        "archive": {
            "name": f"floorterminal-v{version}-linux-arm64.tar.gz",
            "sha256": "a" * 64,
        },
        "release": release_document(version, artifact=artifact, **overrides),
    }


def write_update_drive(
    root, seed, key_id, version="1.1.0", *, artifact=None, document=None
):
    """Create a complete update medium under ``root`` and return its mount path."""
    artifact = executable_bytes(version) if artifact is None else artifact
    mount = Path(root)
    package_dir = mount / trust.UPDATE_PACKAGE_DIRNAME
    package_dir.mkdir(parents=True, exist_ok=True)
    body = encode(document or package_document(version, artifact=artifact))
    (package_dir / trust.MANIFEST_NAME).write_bytes(body)
    (package_dir / trust.SIGNATURE_NAME).write_bytes(sign_document(seed, key_id, body))
    (package_dir / trust.EXECUTABLE_NAME).write_bytes(artifact)
    return mount


def build_installation(root, version="1.0.0"):
    """Create a managed installation with one version slot and an active link."""
    root = Path(root)
    slot = root / "versions" / version
    slot.mkdir(parents=True, exist_ok=True)
    executable = slot / trust.EXECUTABLE_NAME
    executable.write_bytes(executable_bytes(version))
    executable.chmod(0o700)
    link = root / trust.EXECUTABLE_NAME
    link.unlink(missing_ok=True)
    os.symlink(f"versions/{version}/{trust.EXECUTABLE_NAME}", link)
    (root / "config.json").write_text(
        '{"line_name": "Deployment owned"}', encoding="utf-8"
    )
    (root / "response_state.json").write_text('{"status": "RUNNING"}', encoding="utf-8")
    return root
