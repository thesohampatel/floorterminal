#!/usr/bin/env python3
"""Offline publication gate. Never signs, publishes, contacts a service, or reads keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from floorterminal import __version__
from floorterminal.core.config import validate_config
from floorterminal.integration.definition import IntegrationDefinition
from floorterminal.update import manifest, trust
from scripts.build.build import source_input_manifest

INSTALL_FILES = frozenset(
    {
        "DEPLOYMENT.txt",
        "LICENSE",
        "SBOM.spdx.json",
        "SHA256SUMS",
        "SOFTWARE_INFORMATION_AND_NOTICES.txt",
        "VERSION",
        "config.json",
        "connector.json",
        "floorterminal",
        "floorterminal-icon.png",
        "floorterminal-launch",
        "floorterminal.desktop",
        "floorterminal.service",
        "install.sh",
    }
)
UPDATE_FILES = frozenset(
    {
        "LICENSE",
        "SBOM.spdx.json",
        "SHA256SUMS",
        "SOFTWARE_INFORMATION_AND_NOTICES.txt",
        "VERSION",
        "READ_ME_FIRST.txt",
        "floorterminal",
        trust.MANIFEST_NAME,
        trust.SIGNATURE_NAME,
    }
)
PRIVATE_NAMES = frozenset(
    {
        "config.json",
        "connector.json",
        "project_profile.json",
        "settings_auth.json",
        "response_state.json",
        "auth_throttle.json",
        "BUILD_HISTORY.jsonl",
        ".env",
    }
)
PRIVATE_PARTS = frozenset(
    {".venv", "logs", "pi_build_output", "dist", "floorterminal_key"}
)


class AuditError(ValueError):
    """One publication requirement was not met."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_paths(paths):
    """Check names only; never open an accidentally tracked private file."""
    for name in paths:
        path = PurePosixPath(name)
        require(
            not PRIVATE_PARTS.intersection(path.parts)
            and (not path.parts or path.parts[0] != "build")
            and ("build_history" not in path.parts or name == "build_history/README.md")
            and path.name not in PRIVATE_NAMES
            and not path.name.endswith(
                (
                    ".private.json",
                    ".pem",
                    ".key",
                    ".pyc",
                    ".pyo",
                    ".jsonl",
                    ".log",
                    ".spec",
                )
            )
            and not path.name.startswith(".env."),
            f"Private/runtime file is included in publication: {name}",
        )


def check_source_metadata(root):
    """Verify immutable identity, examples, and the exact signed announcement."""
    root = Path(root)
    package = tomllib.loads((root / "pyproject.toml").read_text())
    require(
        package["project"]["version"] == __version__,
        "Package/application version mismatch",
    )
    validate_config(json.loads((root / "config.example.json").read_text()))
    connector = IntegrationDefinition(root / "connector.example.json")
    require(
        not connector.enabled and not any(connector.credentials.values()),
        "Public connector template must be disabled and credential-free",
    )
    channel = manifest.load_verified_channel(
        (root / "update-channel/latest.json").read_bytes(),
        (root / "update-channel/latest.json.sig").read_bytes(),
    )
    require(
        channel.release.version == __version__,
        "Signed channel/application version mismatch",
    )
    require(
        channel.release.notes_url == f"{trust.RELEASES_URL}/tag/v{__version__}",
        "Signed release notes do not point to the canonical release",
    )
    keys = json.loads(
        (
            root
            / "maintainer_keys"
            / f"update-signing-{channel.signing_key_id}.public.json"
        ).read_text()
    )
    require(
        "private_seed_base64" not in keys, "Private material in public key descriptor"
    )
    require(
        keys["public_key_base64"]
        == trust.trusted_key(channel.signing_key_id).public_key_base64,
        "Public signing descriptor does not match the pinned key",
    )
    return channel


def check_actions(root):
    for path in (Path(root) / ".github/workflows").glob("*.yml"):
        for action in re.findall(r"uses:\s*([^\s#]+)", path.read_text()):
            require(
                re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) is not None,
                f"Action is not pinned to a full commit SHA: {path.name}",
            )
        require(
            "pull_request_target:" not in path.read_text(),
            f"Privileged pull-request workflow requires separate review: {path.name}",
        )


def checksum_rows(payload):
    rows = {}
    for line in payload.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\s\\]+)", line)
        require(match is not None, "Malformed checksum manifest")
        value, name = match.groups()
        require(name not in rows, "Duplicate checksum entry")
        rows[name] = value
    return rows


def audit_archive(path, prefix, expected):
    """Stream a bounded archive without extracting or executing its contents."""
    hashes, small, modes, headers = {}, {}, {}, {}
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for index, member in enumerate(archive):
            require(index <= len(expected), "Too many archive members")
            name = PurePosixPath(member.name)
            require(
                member.name == name.as_posix() and ".." not in name.parts,
                "Non-canonical or traversal path in archive",
            )
            require(
                member.uid == member.gid == 0 and not member.uname and not member.gname,
                "Archive contains build-host ownership",
            )
            if member.isdir():
                require(member.name == prefix, "Unexpected archive directory")
                continue
            require(
                member.isfile() and not member.issparse(),
                "Links/special files are forbidden",
            )
            require(
                len(name.parts) == 2
                and name.parts[0] == prefix
                and name.name in expected,
                "Unexpected archive file",
            )
            require(name.name not in hashes, "Duplicate archive file")
            maximum = (
                trust.MAX_ARTIFACT_BYTES
                if name.name == "floorterminal"
                else 4 * 1024**2
            )
            require(0 <= member.size <= maximum, "Archive member exceeds size bound")
            total += member.size
            require(
                total <= trust.MAX_ARTIFACT_BYTES + 16 * 1024**2,
                "Archive exceeds size bound",
            )
            stream = archive.extractfile(member)
            checksum = hashlib.sha256()
            content, size = bytearray(), 0
            with stream:
                while chunk := stream.read(1024 * 1024):
                    if not size:
                        headers[name.name] = chunk[:20]
                    size += len(chunk)
                    checksum.update(chunk)
                    if name.name != "floorterminal":
                        content.extend(chunk)
            require(size == member.size, "Truncated archive file")
            hashes[name.name], modes[name.name] = checksum.hexdigest(), member.mode
            if name.name != "floorterminal":
                small[name.name] = bytes(content)
    require(set(hashes) == set(expected), "Archive file set is incomplete")
    require(
        checksum_rows(small["SHA256SUMS"])
        == {name: value for name, value in hashes.items() if name != "SHA256SUMS"},
        "Internal checksums do not match the archive",
    )
    header = headers["floorterminal"]
    require(
        len(header) >= 20
        and header[:6] == b"\x7fELF\x02\x01"
        and int.from_bytes(header[18:20], "little") == 183,
        "Release executable is not Linux ARM64",
    )
    for name in {"floorterminal", "floorterminal-launch", "install.sh"} & set(expected):
        require(modes[name] & 0o111, "An executable lost its execute permission")
    require(
        small["VERSION"].decode().strip() == __version__, "Archive version mismatch"
    )
    return hashes, small


def check_artifacts(folder, channel, root=ROOT):
    folder = Path(folder)
    stem = f"floorterminal-v{__version__}"
    installation = folder / f"{stem}-linux-arm64.tar.gz"
    update = folder / f"{stem}-update-linux-arm64.tar.gz"
    for archive in (installation, update):
        rows = checksum_rows(archive.with_name(archive.name + ".sha256").read_bytes())
        require(
            rows == {archive.name: digest(archive)},
            "External archive checksum mismatch",
        )
    require(
        channel.archive_name == installation.name
        and channel.archive_sha256 == digest(installation),
        "Signed channel does not bind this installation archive",
    )
    installed, data = audit_archive(installation, f"{stem}-linux-arm64", INSTALL_FILES)
    require(
        installed["floorterminal"] == channel.release.artifact_sha256,
        "Installed executable does not match the signed channel",
    )
    require(
        data["LICENSE"] == (Path(root) / "LICENSE").read_bytes(), "License mismatch"
    )
    connector = json.loads(data["connector.json"])
    require(
        connector.get("enabled") is False
        and not any(connector.get("credentials", {}).values()),
        "Release connector is enabled or contains credentials",
    )
    updated, update_data = audit_archive(
        update, trust.UPDATE_PACKAGE_DIRNAME, UPDATE_FILES
    )
    package = manifest.load_verified_package(
        update_data[trust.MANIFEST_NAME], update_data[trust.SIGNATURE_NAME]
    )
    require(
        package.release == channel.release
        and package.signing_key_id == channel.signing_key_id,
        "USB package and channel describe different releases",
    )
    require(
        updated["floorterminal"] == installed["floorterminal"],
        "USB and installation executables differ",
    )
    for name in (
        "LICENSE",
        "VERSION",
        "SOFTWARE_INFORMATION_AND_NOTICES.txt",
        "SBOM.spdx.json",
    ):
        require(data[name] == update_data[name], "Installation/USB notices differ")


def check_build_record(path, channel):
    path = Path(path)
    record = json.loads(path.read_text())
    inputs = json.loads((path.parent / "source_manifest.json").read_text())
    require(record.get("outcome") == "success", "Build record is not successful")
    require(
        record.get("artifact_sha256") == channel.release.artifact_sha256,
        "Build record and signed executable differ",
    )
    require(
        record.get("source_inputs_sha256") == inputs.get("sha256")
        and inputs == source_input_manifest(),
        "Reviewed source differs from compiled inputs",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts", type=Path, help="private folder with the four release files"
    )
    parser.add_argument(
        "--build-record",
        type=Path,
        help="private build_record.json for these artifacts",
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", help="review uncommitted changes too"
    )
    args = parser.parse_args()
    try:
        names = (
            subprocess.check_output(
                ["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"], cwd=ROOT
            )
            .decode()
            .split("\0")
        )
        check_paths(name for name in names if name)
        if not args.allow_dirty:
            require(
                not subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=ROOT
                ).strip(),
                "Working tree is dirty; commit reviewed changes or use --allow-dirty",
            )
        channel = check_source_metadata(ROOT)
        check_actions(ROOT)
        if args.artifacts:
            require(
                args.build_record is not None, "--artifacts requires --build-record"
            )
            check_artifacts(args.artifacts, channel)
            check_build_record(args.build_record, channel)
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
        tarfile.TarError,
    ) as exc:
        print(f"PUBLICATION AUDIT FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        "Publication audit passed: reviewed file set, version, examples, pinned actions, signed channel"
        + (" and source-matched ARM64 archives" if args.artifacts else "")
    )
    print(
        "Offline only. Run the test suite and secret/history scanner separately; "
        "hosted CI and deployment commissioning remain owner checks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
