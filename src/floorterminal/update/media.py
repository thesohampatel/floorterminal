"""Removable-media discovery, verification, and staging.

An update drive is hostile input. Nothing on it is ever executed, no path on it is
followed through a symbolic link, no file on it is read without a size bound, and
its metadata is rejected outright unless a detached Ed25519 signature made by a key
compiled into this build covers the exact manifest bytes. Only after the signature,
the product identity, the target, the version ordering, and the streamed SHA-256 of
the executable all agree is a byte copied onto the terminal.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import shutil
import socket
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..core.config import write_json, write_private
from . import journal, manifest, trust, version
from .layout import InstallLayout

MAX_MEDIA_ENTRIES = 64
ELF_MAGIC = b"\x7fELF"


class MediaError(RuntimeError):
    """Raised when a candidate update medium cannot be trusted or used."""


@dataclass(frozen=True)
class MediaPackage:
    """A cryptographically verified update package resting on removable media."""

    mount: Path
    package_dir: Path
    artifact: Path
    package: manifest.UpdatePackage
    manifest_bytes: bytes
    signature_bytes: bytes

    @property
    def release(self):
        return self.package.release

    @property
    def version(self):
        return self.package.release.version


def _normalised_label(name):
    return str(name).strip().upper()


def _safe_child(parent: Path, name: str) -> Path:
    """Resolve one child without following a symbolic link out of ``parent``."""
    child = parent / name
    if child.is_symlink():
        raise MediaError(f"Update medium uses a symbolic link for {name}; refusing")
    return child


def _listdir(path: Path):
    try:
        entries = sorted(path.iterdir())
    except OSError:
        return ()
    return tuple(entries[:MAX_MEDIA_ENTRIES])


def candidate_mounts(labelled_only=True, roots=None):
    """Return mounted volumes that may carry an update package.

    ``labelled_only`` implements the documented automatic trigger: only a volume
    whose label is one of the hardcoded update labels is picked up on its own. The
    Software Update panel can request a wider scan for an operator who prepared a
    drive whose filesystem could not keep the label.
    """
    accepted = {_normalised_label(label) for label in trust.UPDATE_VOLUME_LABELS}
    found = []
    for root_name in roots or trust.MEDIA_ROOTS:
        root = Path(root_name)
        if not root.is_dir():
            continue
        for entry in _listdir(root):
            if not entry.is_dir():
                continue
            levels = (
                [entry] if entry.name.upper() in accepted or not labelled_only else []
            )
            # Desktop sessions mount removable media under /media/<user>/<LABEL>,
            # so one extra level is inspected before giving up.
            for nested in _listdir(entry):
                if nested.is_dir() and (
                    not labelled_only or nested.name.upper() in accepted
                ):
                    levels.append(nested)
            for mount in levels:
                package_dir = mount / trust.UPDATE_PACKAGE_DIRNAME
                if package_dir.is_dir() and mount not in found:
                    found.append(mount)
    return tuple(found)


def _read_bounded(path: Path, maximum: int, description: str) -> bytes:
    if path.is_symlink():
        raise MediaError(f"{description} is a symbolic link; refusing to read it")
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise MediaError(f"{description} must be a regular file")
        if path.stat().st_size > maximum:
            raise MediaError(f"{description} exceeds the {maximum}-byte safety limit")
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
    except OSError as exc:
        raise MediaError(f"Cannot read {description}: {exc}") from exc
    if len(data) > maximum:
        raise MediaError(f"{description} exceeds the {maximum}-byte safety limit")
    return data


def digest_file(path: Path, maximum=trust.MAX_ARTIFACT_BYTES) -> tuple[str, int]:
    """Stream a file through SHA-256, refusing anything above the size bound."""
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise MediaError("Update artifact must be a regular file, not a symbolic link")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(trust.COPY_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise MediaError("Update artifact exceeds the configured size limit")
            digest.update(chunk)
    return digest.hexdigest(), total


def read_package(mount) -> MediaPackage:
    """Verify the package on ``mount`` and return it, or raise :class:`MediaError`."""
    mount = Path(mount)
    package_dir = _safe_child(mount, trust.UPDATE_PACKAGE_DIRNAME)
    return read_package_directory(package_dir, mount=mount)


def read_package_directory(package_dir, *, mount=None) -> MediaPackage:
    """Authenticate a USB, staging or installed directory with the same policy."""
    package_dir = Path(package_dir)
    if package_dir.is_symlink():
        raise MediaError("Refusing symbolic link for update package directory")
    if not package_dir.is_dir():
        raise MediaError(
            f"No {trust.UPDATE_PACKAGE_DIRNAME} directory was found on the medium"
        )
    document = _read_bounded(
        _safe_child(package_dir, trust.MANIFEST_NAME),
        trust.MAX_MANIFEST_BYTES,
        "the update manifest",
    )
    signature = _read_bounded(
        _safe_child(package_dir, trust.SIGNATURE_NAME),
        trust.MAX_SIGNATURE_BYTES,
        "the update signature",
    )
    try:
        package = manifest.load_verified_package(document, signature)
    except manifest.ManifestError as exc:
        raise MediaError(str(exc)) from exc
    artifact = _safe_child(package_dir, package.release.artifact_name)
    if not artifact.is_file():
        raise MediaError(
            f"The manifest names {package.release.artifact_name}, "
            "but that file is missing from the medium"
        )
    return MediaPackage(
        Path(mount) if mount is not None else package_dir.parent,
        package_dir,
        artifact,
        package,
        document,
        signature,
    )


def verify_artifact(media_package: MediaPackage):
    """Confirm the executable on the medium matches the signed manifest exactly."""
    release = media_package.release
    try:
        actual, size = digest_file(media_package.artifact)
    except OSError as exc:
        raise MediaError(f"Cannot read the update artifact: {exc}") from exc
    if size != release.artifact_size_bytes:
        raise MediaError(
            f"Update artifact is {size} bytes but the signed manifest declares "
            f"{release.artifact_size_bytes}"
        )
    if actual != release.artifact_sha256:
        raise MediaError(
            "Update artifact checksum does not match the signed manifest; the file "
            "is damaged or was replaced"
        )
    return actual


def verify_local_package(directory, expected_version):
    """Recheck persisted signatures and payload before displaying or activating."""
    package = read_package_directory(directory)
    if package.version != str(expected_version):
        raise MediaError("Signed update version does not match its local slot")
    verify_artifact(package)
    return package


def check_installable(media_package: MediaPackage, installed_version):
    """Return why the package cannot be installed here, or an empty string."""
    release = media_package.release
    try:
        candidate = version.parse(release.version)
        installed = version.parse(installed_version)
        minimum = version.parse(release.minimum_upgradable_version)
    except version.VersionError as exc:
        return str(exc)
    if candidate.release_rank == 0 and installed.release_rank == 1:
        return f"Version {candidate} is a release candidate; stable terminals require a stable release"
    if candidate == installed:
        return f"Version {candidate} is already installed"
    if candidate < installed:
        return f"Version {candidate} is older than the installed version; use authorized rollback"
    if installed < minimum:
        return (
            f"Version {candidate} can only be installed over {minimum} or newer; "
            f"this terminal runs {installed}"
        )
    return ""


def candidate_package_directories(mount):
    """Accept a legacy single package or bounded canonical version subfolders."""
    root = _safe_child(Path(mount), trust.UPDATE_PACKAGE_DIRNAME)
    if root.is_symlink():
        raise MediaError("Update package directory must not be a symbolic link")
    if (root / trust.MANIFEST_NAME).exists() or (root / trust.SIGNATURE_NAME).exists():
        return (root,)
    directories = []
    try:
        entries = list(itertools.islice(root.iterdir(), MAX_MEDIA_ENTRIES + 1))
    except OSError as exc:
        raise MediaError(f"Cannot list versioned update packages: {exc}") from exc
    if len(entries) > MAX_MEDIA_ENTRIES:
        raise MediaError("Too many entries in the update folder; keep at most 64")
    for child in sorted(entries):
        parsed = version.try_parse(child.name)
        if parsed and str(parsed) == child.name:
            directories.append(child)
    if not directories:
        raise MediaError("No update manifest or versioned package directory was found")
    return tuple(directories)


def stage(layout: InstallLayout, media_package: MediaPackage, expect_executable=True):
    """Publish a completely verified staging slot; failed copies preserve earlier ones."""
    layout.ensure_directories()
    release = media_package.release
    verify_artifact(media_package)
    destination_dir = layout.staging_dir / release.version
    if destination_dir.is_symlink():
        raise MediaError("Staging slot must not be a symbolic link")
    if destination_dir.exists():
        try:
            existing = verify_local_package(destination_dir, release.version)
        except (MediaError, OSError):
            # Invalid partial staging has no authority. A verified drive may repair it.
            shutil.rmtree(destination_dir)
        else:
            if (
                existing.release != release
                or existing.package.target != media_package.package.target
            ):
                raise MediaError(
                    "Conflicting signed packages use the same version; review the media"
                )
            return existing.artifact
    try:
        free = shutil.disk_usage(layout.staging_dir).free
    except OSError as exc:
        raise MediaError(f"Cannot inspect free space for staging: {exc}") from exc
    required = release.artifact_size_bytes + trust.STAGING_HEADROOM_BYTES
    if free < required:
        raise MediaError(
            f"{free // (1024 * 1024)} MB free is not enough to stage this update; "
            f"{required // (1024 * 1024)} MB is required"
        )
    temporary = Path(tempfile.mkdtemp(prefix=".copy-", dir=layout.staging_dir))
    target = temporary / release.artifact_name
    try:
        copied = 0
        with media_package.artifact.open("rb") as source, target.open("xb") as sink:
            while chunk := source.read(trust.COPY_CHUNK_BYTES):
                copied += len(chunk)
                if copied > release.artifact_size_bytes:
                    raise MediaError("Update artifact grew while it was being copied")
                sink.write(chunk)
            sink.flush()
            os.fsync(sink.fileno())
        target.chmod(0o700)
        write_private(temporary / trust.MANIFEST_NAME, media_package.manifest_bytes)
        write_private(temporary / trust.SIGNATURE_NAME, media_package.signature_bytes)
        _write_package_record(temporary, media_package)
        verify_local_package(temporary, release.version)
        if expect_executable:
            with target.open("rb") as stream:
                header = stream.read(20)
            if (
                len(header) != 20
                or header[:6] != b"\x7fELF\x02\x01"
                or int.from_bytes(header[18:20], "little") != 183
            ):
                raise MediaError("Staged artifact is not a Linux executable for ARM64")
        os.replace(temporary, destination_dir)
        descriptor = os.open(layout.staging_dir, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise MediaError(f"Cannot stage the update artifact: {exc}") from exc
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return destination_dir / release.artifact_name


def _write_package_record(destination_dir: Path, media_package: MediaPackage):
    """Keep the verified release description beside the staged executable."""
    release = media_package.release
    write_json(
        destination_dir / "release.json",
        {
            "schema_version": manifest.SCHEMA_VERSION,
            "version": release.version,
            "released_utc": release.released_utc,
            "release_title": release.release_title,
            "release_summary": release.release_summary,
            "minimum_upgradable_version": release.minimum_upgradable_version,
            "artifact_sha256": release.artifact_sha256,
            "artifact_size_bytes": release.artifact_size_bytes,
            "notes_url": release.notes_url,
            "features": list(release.features),
            "fixes": list(release.fixes),
            "security": list(release.security),
            "signing_key_id": media_package.package.signing_key_id,
            "staged_at_utc": journal.utc_now(),
        },
    )


def terminal_identity():
    """Return a short, non-sensitive terminal name used in the medium's log file."""
    try:
        name = socket.gethostname().split(".")[0]
    except OSError:
        name = "terminal"
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in name
    )
    return (cleaned.strip("-") or "terminal")[:32]


def mirror_log(mount, event, level="INFO", **details):
    """Append one update event to the medium so the record travels with the drive."""
    try:
        directory = Path(mount) / trust.MEDIA_LOG_DIRNAME
        if directory.is_symlink():
            return False
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{terminal_identity()}.jsonl"
    except OSError:
        return False
    return journal.append_log(
        path, event, level, terminal=terminal_identity(), **details
    )
