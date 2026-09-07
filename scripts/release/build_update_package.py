#!/usr/bin/env python3
"""Build and sign one offline software-update package and its channel document.

The output of this script is everything a site needs to update a terminal without
a network, plus the two small files that let terminals notice a new version exists:

    <output>/usb/floorterminal-update/     copy onto the update drive
    <output>/update-channel/                       commit to the repository

Signing happens on the maintainer's offline workstation, never on a terminal and
never in continuous integration. The script re-verifies its own output through the
same code path a terminal uses, so a package that fails verification is never
published.

    python3 scripts/release/build_update_package.py \\
        --executable dist/releases/<profile>/<build-id>/floorterminal/floorterminal \\
        --version 1.1.0 \\
        --notes docs/releases/notes-1.1.0.json \\
        --key ~/offline/update-signing-<id>.private.json \\
        --archive floorterminal-v1.1.0-linux-arm64.tar.gz \\
        --output dist/update/1.1.0
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from floorterminal.update import manifest, signing, trust, version

NOTE_FIELDS = ("release_title", "release_summary", "notes_url")
LIST_FIELDS = ("features", "fixes", "security")

READ_ME = """FLOORTERMINAL • OFFLINE SOFTWARE UPDATE DRIVE
=====================================================

Version in this package : {version}
Released (UTC)          : {released}
Executable SHA-256      : {digest}
Signed with key id      : {key_id}

HOW TO USE THIS DRIVE
1. Keep this directory exactly as it is. Do not rename, edit, or add files.
2. Plug the drive into the Raspberry Pi terminal while the line is running.
3. The terminal verifies the signature and checksum by itself and turns its
   update indicator amber.
4. Touch the update indicator beside the information button, then touch
   INSTALL UPDATE and enter the administrator name and Settings password.
5. The terminal restarts into the new version and continues from the exact
   state it was in. Configuration, connector files, logs, and any active
   downtime event are never touched by an update.
6. If the new version does not suit the site, touch the update indicator again
   and use RESTORE PREVIOUS VERSION.

The terminal will refuse this package if any byte of it changes, if it was not
signed by the maintainer, or if it was built for another product or processor.
Nothing on this drive is ever executed by the terminal.

Maintainer: {maintainer} <{email}>
Project   : {project}
"""


def build_arguments():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--executable",
        required=True,
        help="built native executable beside its release notices",
    )
    parser.add_argument("--version", required=True, help="release version, e.g. 1.1.0")
    parser.add_argument("--notes", required=True, help="release notes JSON file")
    parser.add_argument("--key", required=True, help="private signing key JSON file")
    parser.add_argument("--output", required=True, help="output directory to create")
    parser.add_argument(
        "--target",
        default=trust.SUPPORTED_TARGETS[0],
        choices=list(trust.SUPPORTED_TARGETS),
        help="platform/architecture the executable was built for",
    )
    parser.add_argument(
        "--archive",
        default="",
        help="published GitHub archive filename recorded in the channel document",
    )
    parser.add_argument(
        "--archive-sha256",
        default="",
        help="SHA-256 of the published archive; computed when --archive-path is given",
    )
    parser.add_argument(
        "--archive-path", default="", help="local path to the published archive"
    )
    parser.add_argument(
        "--released",
        default="",
        help="release timestamp as YYYY-MM-DDTHH:MM:SSZ (default: now)",
    )
    parser.add_argument(
        "--skip-channel",
        action="store_true",
        help="produce only the update drive package",
    )
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def digest_file(path: Path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def load_notes(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"Cannot read release notes {path}: {exc}")
    if not isinstance(data, dict):
        fail("Release notes must contain one JSON object")
    allowed = {*NOTE_FIELDS, *LIST_FIELDS, "minimum_upgradable_version"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        fail("Release notes contain unsupported fields: " + ", ".join(unknown))
    for field in ("release_title", "release_summary"):
        if not str(data.get(field, "")).strip():
            fail(f"Release notes must provide {field}")
    return data


def load_key(path: Path):
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        seed = base64.b64decode(data["private_seed_base64"], validate=True)
        key_id = str(data["key_id"])
    except (OSError, ValueError, KeyError) as exc:
        fail(f"Cannot read the signing key {path}: {exc}")
    if len(seed) != signing.PRIVATE_SEED_BYTES:
        fail("Signing key seed must be exactly 32 bytes")
    if trust.trusted_key(key_id) is None:
        fail(
            f"Key {key_id} is not listed in TRUSTED_KEYS. Ship a build that trusts it "
            "before signing releases with it, or terminals will reject the package."
        )
    expected = trust.trusted_key(key_id).public_key
    if signing.public_key_from_seed(seed) != expected:
        fail(f"Private key does not match the trusted public key for id {key_id}")
    return seed, key_id


def signature_document(seed, key_id, payload: bytes):
    return {
        "schema_version": manifest.SCHEMA_VERSION,
        "algorithm": "ed25519",
        "key_id": key_id,
        "signature": base64.b64encode(signing.sign(seed, payload)).decode("ascii"),
    }


def encode(document) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def copy_release_notices(executable: Path, destination: Path):
    """Every redistributed binary keeps its license and dependency notices."""
    required = (
        "LICENSE",
        "SOFTWARE_INFORMATION_AND_NOTICES.txt",
        "SBOM.spdx.json",
        "VERSION",
    )
    for name in required:
        source = executable.parent / name
        if source.is_symlink() or not source.is_file():
            fail(f"Release is missing a regular {name} file beside the executable")
    for name in required:
        shutil.copyfile(executable.parent / name, destination / name)
        (destination / name).chmod(0o644)


def public_archive_member(info):
    """Do not distribute build-host account names or numeric ownership in tar."""
    if not info.isfile() and not info.isdir():
        fail("Update archives must contain only regular files and directories")
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.pax_headers = {}
    info.mtime = 0
    return info


def main():
    arguments = build_arguments()
    executable = Path(arguments.executable).expanduser().resolve()
    if not executable.is_file():
        fail(f"Executable not found: {executable}")
    try:
        release_version = str(version.parse(arguments.version))
    except version.VersionError as exc:
        fail(str(exc))
    notes = load_notes(Path(arguments.notes).expanduser())
    seed, key_id = load_key(arguments.key)
    released = arguments.released or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest, size = digest_file(executable)
    if not trust.MIN_ARTIFACT_BYTES <= size <= trust.MAX_ARTIFACT_BYTES:
        fail(f"Executable size {size} is outside the accepted range")
    if arguments.target.startswith("linux/"):
        with executable.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                fail("A linux target requires an ELF executable")

    release = {
        "version": release_version,
        "released_utc": released,
        "release_title": notes["release_title"],
        "release_summary": notes["release_summary"],
        "minimum_upgradable_version": str(
            version.parse(notes.get("minimum_upgradable_version", "1.0.0"))
        ),
        "artifact": {
            "name": trust.EXECUTABLE_NAME,
            "sha256": digest,
            "size_bytes": size,
        },
        "notes_url": notes.get(
            "notes_url", f"{trust.RELEASES_URL}/tag/v{release_version}"
        ),
        **{key: list(notes.get(key, [])) for key in LIST_FIELDS},
    }
    package_document = {
        "schema_version": manifest.SCHEMA_VERSION,
        "document_type": manifest.PACKAGE_DOCUMENT,
        "product_id": trust.PRODUCT_ID,
        "target": arguments.target,
        "release": release,
    }
    package_bytes = encode(package_document)
    package_signature = encode(signature_document(seed, key_id, package_bytes))

    output = Path(arguments.output).expanduser()
    if output.exists() and any(output.iterdir()):
        fail(f"Output directory is not empty: {output}")
    package_dir = output / "usb" / trust.UPDATE_PACKAGE_DIRNAME
    package_dir.mkdir(parents=True, exist_ok=True)
    copy_release_notices(executable, package_dir)
    (package_dir / trust.MANIFEST_NAME).write_bytes(package_bytes)
    (package_dir / trust.SIGNATURE_NAME).write_bytes(package_signature)
    shutil.copy2(executable, package_dir / trust.EXECUTABLE_NAME)
    (package_dir / trust.EXECUTABLE_NAME).chmod(0o755)
    (package_dir / "READ_ME_FIRST.txt").write_text(
        READ_ME.format(
            version=release_version,
            released=released,
            digest=digest,
            key_id=key_id,
            maintainer=trust.MAINTAINER_NAME,
            email=trust.MAINTAINER_EMAIL,
            project=trust.PROJECT_URL,
        ),
        encoding="utf-8",
    )
    rows = []
    for path in sorted(package_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            rows.append(f"{digest_file(path)[0]}  {path.name}")
    (package_dir / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")

    # Verify through exactly the code path a terminal uses before publishing.
    verified = manifest.load_verified_package(package_bytes, package_signature)
    if verified.release.artifact_sha256 != digest or verified.signing_key_id != key_id:
        fail("Self-verification of the generated package failed")

    # One archive an end user downloads and extracts at the root of the update
    # drive. Modes are preserved so the executable stays executable.
    archive_stem = f"floorterminal-v{release_version}-update-linux-arm64"
    archive_path = output / f"{archive_stem}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(
            package_dir,
            arcname=trust.UPDATE_PACKAGE_DIRNAME,
            filter=public_archive_member,
        )
    archive_digest = digest_file(archive_path)[0]
    (output / f"{archive_stem}.tar.gz.sha256").write_text(
        f"{archive_digest}  {archive_path.name}\n", encoding="utf-8"
    )

    if not arguments.skip_channel:
        archive_name = arguments.archive or (
            f"floorterminal-v{release_version}-linux-arm64.tar.gz"
        )
        archive_sha = arguments.archive_sha256
        if arguments.archive_path:
            archive_sha = digest_file(Path(arguments.archive_path).expanduser())[0]
        if not archive_sha:
            fail("Provide --archive-sha256 or --archive-path, or pass --skip-channel")
        channel_document = {
            "schema_version": manifest.SCHEMA_VERSION,
            "document_type": manifest.CHANNEL_DOCUMENT,
            "product_id": trust.PRODUCT_ID,
            "published_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "targets": [arguments.target],
            "archive": {"name": archive_name, "sha256": archive_sha},
            "release": release,
        }
        channel_bytes = encode(channel_document)
        channel_signature = encode(signature_document(seed, key_id, channel_bytes))
        manifest.load_verified_channel(channel_bytes, channel_signature)
        channel_dir = output / "update-channel"
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "latest.json").write_bytes(channel_bytes)
        (channel_dir / "latest.json.sig").write_bytes(channel_signature)

    print(f"Version            : {release_version}")
    print(f"Executable SHA-256 : {digest}")
    print(f"Executable size    : {size} bytes")
    print(f"Signed with key    : {key_id}")
    print(f"Update drive files : {package_dir}")
    print(f"Update drive archive: {archive_path}")
    print(f"Archive SHA-256    : {archive_digest}")
    if not arguments.skip_channel:
        print(f"Channel files      : {output / 'update-channel'}")
        print(
            "Commit the channel files to update-channel/ on the default branch so "
            "terminals can see the new version."
        )
    print()
    print(
        "Prepare the drive by formatting it with the volume label "
        f"{trust.UPDATE_VOLUME_LABELS[0]} and copying the whole "
        f"{trust.UPDATE_PACKAGE_DIRNAME} directory to its root."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
