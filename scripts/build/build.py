#!/usr/bin/env python3
"""Reproducible native release builder for Linux, macOS, and Windows."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

PYINSTALLER_VERSION = "6.21.0"
BUILDER_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BUILDER_DIR.parents[1]
SOURCE_DIR = PROJECT_DIR / "src"
WORK_DIR = PROJECT_DIR / "build"
OUTPUT_ROOT = PROJECT_DIR / "dist"
RELEASE_DIR = OUTPUT_ROOT / "releases" / "unconfigured" / "floorterminal"
ASSETS_DIR = PROJECT_DIR / "packaging" / "linux"
PROJECT_PROFILE_FILE = (
    Path(
        os.environ.get(
            "FLOORTERMINAL_PROJECT_PROFILE_FILE", PROJECT_DIR / "project_profile.json"
        )
    )
    .expanduser()
    .resolve()
)
RELEASE_NOTICES = "SOFTWARE_INFORMATION_AND_NOTICES.txt"
SBOM_FILE = "SBOM.spdx.json"
EMBEDDED_PROJECT_PROFILE_FILE = WORK_DIR / "project_profile.json"
BUILD_HISTORY_INDEX = PROJECT_DIR / "BUILD_HISTORY.jsonl"
BUILD_HISTORY_DIR = PROJECT_DIR / "build_history"


def source_input_manifest():
    """Fingerprint reviewed inputs, excluding live configuration and release metadata.

    Docs and the signed channel are completed after compilation. Their later Git
    commit must not obscure which application/packaging/test bytes were built.
    Private runtime inputs have separate digests in the owner-only build record.
    """
    candidates = [
        PROJECT_DIR / name
        for name in (
            "main.py",
            "pyproject.toml",
            "LICENSE",
            "config.example.json",
            "connector.example.json",
            "project_profile.example.json",
        )
    ]
    for directory in ("src", "packaging", "scripts", "tests"):
        candidates.extend((PROJECT_DIR / directory).rglob("*"))
    files = {}
    for path in sorted(candidates):
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise BuildError(
                "Symbolic link in build inputs: " + str(path.relative_to(PROJECT_DIR))
            )
        if path.is_file():
            files[path.relative_to(PROJECT_DIR).as_posix()] = sha256_file(path)
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": 1,
        "files": files,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


class TeeStream:
    """Write console output to both the terminal and the private build log."""

    def __init__(self, terminal, log):
        self.terminal = terminal
        self.log = log

    def write(self, data):
        self.terminal.write(data)
        self.log.write(data)
        self.log.flush()
        return len(data)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def isatty(self):
        return False


class BuildRecorder:
    """Persist one owner-side record for every attempted build."""

    @staticmethod
    def _private_directory(path, *, exist_ok=True):
        if path.is_symlink():
            raise BuildError(f"Refusing symbolic-link build-history directory: {path}")
        path.mkdir(mode=0o700, parents=False, exist_ok=exist_ok)
        path.chmod(0o700)

    def __init__(self):
        self.source_inputs = source_input_manifest()
        self.build_id = str(uuid.uuid4())
        self.started = datetime.now(UTC)
        date_path = self.started.strftime("%Y/%m/%d")
        BUILD_HISTORY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        if BUILD_HISTORY_DIR.is_symlink():
            raise BuildError(
                f"Refusing symbolic-link build-history root: {BUILD_HISTORY_DIR}"
            )
        BUILD_HISTORY_DIR.chmod(0o700)
        cursor = BUILD_HISTORY_DIR
        for part in Path(date_path).parts:
            cursor /= part
            self._private_directory(cursor)
        self.directory = cursor / self.build_id
        self._private_directory(self.directory, exist_ok=False)
        self.log_path = self.directory / "build.log"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.log_path, flags, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        self._log = os.fdopen(descriptor, "w", encoding="utf-8", buffering=1)
        source_path = self.directory / "source_manifest.json"
        source_path.write_text(
            json.dumps(self.source_inputs, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        source_path.chmod(0o600)
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = TeeStream(self._stdout, self._log)
        sys.stderr = TeeStream(self._stderr, self._log)

    @property
    def started_at(self):
        return self.started.isoformat(timespec="seconds").replace("+00:00", "Z")

    def verify_source_inputs(self):
        if source_input_manifest() != self.source_inputs:
            raise BuildError(
                "Source inputs changed during the build; discard this output and rebuild."
            )

    def _project_profile(self):
        try:
            data = json.loads(PROJECT_PROFILE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        fields = (
            "product_name",
            "maintainer_name",
            "distribution_name",
            "support_contact",
            "license_name",
            "license_identifier",
            "license_version",
        )
        return {field: data.get(field) for field in fields}

    @staticmethod
    def _git_dirty():
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        return bool(result.stdout.strip()) if result.returncode == 0 else None

    @staticmethod
    def _git_revision():
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def finish(self, outcome, error=None, system=None, architecture=None):
        finished = datetime.now(UTC)
        project_profile = self._project_profile()
        artifact = None
        try:
            artifact = native_artifact(system) if outcome == "success" else None
        except BuildError:
            artifact = None
        notices = RELEASE_DIR / RELEASE_NOTICES
        manifest = RELEASE_DIR / "SHA256SUMS"
        completed_release = outcome == "success"
        record = {
            "schema_version": 1,
            "build_id": self.build_id,
            "description": os.environ.get(
                "FLOORTERMINAL_BUILD_DESCRIPTION", "Native production build"
            ),
            "purpose": os.environ.get("FLOORTERMINAL_BUILD_PURPOSE", "production"),
            "outcome": outcome,
            "error": error,
            "started_at_utc": self.started_at,
            "finished_at_utc": finished.isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "duration_seconds": round((finished - self.started).total_seconds(), 3),
            "product_name": project_profile.get("product_name"),
            "maintainer_name": project_profile.get("maintainer_name"),
            "distribution_name": project_profile.get("distribution_name"),
            "support_contact": project_profile.get("support_contact"),
            "license_name": project_profile.get("license_name"),
            "license_identifier": project_profile.get("license_identifier"),
            "license_version": project_profile.get("license_version"),
            "platform": system or platform.system().lower(),
            "architecture": architecture or platform.machine().lower(),
            "python_version": platform.python_version(),
            "pyinstaller_version": PYINSTALLER_VERSION,
            "git_revision": self._git_revision(),
            "git_worktree_dirty": self._git_dirty(),
            "source_inputs_sha256": self.source_inputs["sha256"],
            "source_manifest": "source_manifest.json",
            "operating_system_release": platform.release(),
            "operating_system_version": platform.version(),
            "deployment_profile": str(PROJECT_PROFILE_FILE),
            "project_profile_sha256": sha256_file(PROJECT_PROFILE_FILE)
            if PROJECT_PROFILE_FILE.is_file()
            else None,
            "embedded_project_profile_sha256": sha256_file(
                EMBEDDED_PROJECT_PROFILE_FILE
            )
            if completed_release and EMBEDDED_PROJECT_PROFILE_FILE.is_file()
            else None,
            "config_sha256": sha256_file(PROJECT_DIR / "config.json")
            if (PROJECT_DIR / "config.json").is_file()
            else None,
            "connector_template_sha256": sha256_file(PROJECT_DIR / "connector.json")
            if (PROJECT_DIR / "connector.json").is_file()
            else None,
            "artifact_name": artifact.name if artifact else None,
            "artifact_sha256": artifact_sha256(artifact) if artifact else None,
            "release_notices_sha256": sha256_file(notices)
            if completed_release and notices.is_file()
            else None,
            "release_manifest_sha256": sha256_file(manifest)
            if completed_release and manifest.is_file()
            else None,
            "sbom_sha256": sha256_file(RELEASE_DIR / SBOM_FILE)
            if completed_release and (RELEASE_DIR / SBOM_FILE).is_file()
            else None,
            "release_profile": safe_slug(
                project_profile.get("distribution_name") or "unconfigured"
            ),
            "release_directory": str(RELEASE_DIR.relative_to(PROJECT_DIR)),
            "record_directory": str(self.directory.relative_to(PROJECT_DIR)),
            "build_log": str(self.log_path.relative_to(PROJECT_DIR)),
        }
        record_path = self.directory / "build_record.json"
        record_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        record_path.chmod(0o600)
        if completed_release and notices.is_file():
            retained_notices = self.directory / RELEASE_NOTICES
            shutil.copy2(notices, retained_notices)
            retained_notices.chmod(0o600)
        index_flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            index_flags |= os.O_NOFOLLOW
        index_descriptor = os.open(BUILD_HISTORY_INDEX, index_flags, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(index_descriptor, 0o600)
        with os.fdopen(index_descriptor, "a", encoding="utf-8") as index:
            index.write(json.dumps(record, sort_keys=True) + "\n")
            index.flush()
            os.fsync(index.fileno())
        print(f"Build history record: {record_path}")
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        self._log.close()
        return record_path


class BuildError(RuntimeError):
    pass


def info(message):
    print(f"\n==> {message}", flush=True)


def run(command, **kwargs):
    print("   $ " + " ".join(str(part) for part in command), flush=True)
    try:
        process = subprocess.Popen(
            [str(part) for part in command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **kwargs,
        )
        if process.stdout is not None:
            for line in process.stdout:
                print(line, end="", flush=True)
        return_code = process.wait()
    except OSError as exc:
        raise BuildError(f"Command failed to start: {command[0]} ({exc})") from exc
    if return_code != 0:
        raise BuildError(f"Command failed with exit code {return_code}: {command[0]}")
    return process


def safe_slug(value):
    """Create a stable cross-platform directory name from a profile label."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")
    return slug[:64] or "unnamed-profile"


def release_directory_for(
    project_profile,
    build_id,
    output_root=None,
):
    """Give every build an immutable directory under its distribution profile."""
    output_root = Path(output_root or OUTPUT_ROOT)
    return (
        output_root
        / "releases"
        / safe_slug(project_profile.distribution_name)
        / build_id
        / "floorterminal"
    )


def configure_release_directory(project_profile, build_id):
    global RELEASE_DIR
    RELEASE_DIR = release_directory_for(project_profile, build_id)
    return RELEASE_DIR


def host():
    system = platform.system().lower()
    if system not in {"linux", "darwin", "windows"}:
        raise BuildError(f"Unsupported build system: {platform.system()}")
    machine = platform.machine().lower()
    aliases = {"arm64": "aarch64", "amd64": "x86_64", "x64": "x86_64"}
    return system, aliases.get(machine, machine)


def validate_host(system, architecture):
    info(f"Detected {system} / {architecture} / Python {platform.python_version()}")
    if sys.version_info < (3, 11):  # noqa: UP036 - direct-script runtime guard
        raise BuildError("Python 3.11 or newer is required.")
    required = (
        PROJECT_DIR / "main.py",
        PROJECT_DIR / "config.json",
        PROJECT_DIR / "LICENSE",
        PROJECT_PROFILE_FILE,
        SOURCE_DIR / "floorterminal",
    )
    missing = [str(path.name) for path in required if not path.exists()]
    if missing:
        raise BuildError("Missing required project items: " + ", ".join(missing))
    if system == "darwin":
        native_machine = (
            subprocess.run(["uname", "-m"], capture_output=True, text=True, check=False)
            .stdout.strip()
            .lower()
        )
        aliases = {"arm64": "aarch64", "amd64": "x86_64", "x64": "x86_64"}
        native_architecture = aliases.get(native_machine, native_machine)
        if native_architecture and architecture != native_architecture:
            raise BuildError(
                f"Python architecture {architecture} does not match this Mac "
                f"({native_architecture}). Run scripts/build/build.sh so it can "
                "select a native Tk-capable interpreter."
            )
    try:
        import _tkinter  # noqa: F401
        import tkinter  # noqa: F401
    except ImportError:
        hint = (
            " Install python3-tk with the system package manager."
            if system == "linux"
            else " Install a native Tk-enabled Python with: brew install python python-tk"
        )
        raise BuildError("Tkinter is unavailable." + hint)
    free = shutil.disk_usage(PROJECT_DIR).free
    if free < 2 * 1024**3:
        raise BuildError(
            f"At least 2 GB free space is required; found {free / 1024**3:.1f} GB."
        )


def validate_project():
    info("Validating production configuration and Python sources")
    sys.path.insert(0, str(SOURCE_DIR))
    try:
        from floorterminal.core.config import load_config
        from floorterminal.core.project_profile import load_project_profile
        from floorterminal.integration import IntegrationDefinition

        project_profile = load_project_profile(PROJECT_PROFILE_FILE)
        config = load_config()
        connector = IntegrationDefinition(PROJECT_DIR / "connector.json")
        sources = (PROJECT_DIR / "main.py", *SOURCE_DIR.rglob("*.py"))
        for path in sources:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
    except Exception as exc:
        raise BuildError(
            f"Application or configuration validation failed: {exc}"
        ) from exc
    print(
        f"   Project profile valid: {project_profile.product_name} / distribution profile {project_profile.distribution_name}"
    )
    print(f"   Configuration valid: {len(config['zones'])} stations")
    print(
        f"   Connector template valid: {connector.display_name}; enabled={connector.enabled}"
    )
    return project_profile


def validate_tests(system):
    """Run the offline release gate before freezing any executable."""
    info("Running offline release tests")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SOURCE_DIR)
    environment["FLOORTERMINAL_DISABLE_NETWORK"] = "1"
    run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            PROJECT_DIR / "tests",
            "-q",
        ],
        cwd=PROJECT_DIR,
        env=environment,
    )
    if system == "linux":
        run(["sh", "-n", PROJECT_DIR / "packaging/linux/floorterminal-launch"])
        run(
            [
                "bash",
                "-n",
                PROJECT_DIR / "packaging/linux/install.sh",
                PROJECT_DIR / "scripts/install/prepare_release_on_pi.sh",
            ]
        )


def prepare_tools(system):
    """Require a pre-provisioned, exact build tool without downloading packages."""
    info(f"Checking system PyInstaller {PYINSTALLER_VERSION}")
    probe = subprocess.run(
        [sys.executable, "-c", "import PyInstaller; print(PyInstaller.__version__)"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or probe.stdout.strip() != PYINSTALLER_VERSION:
        raise BuildError(
            f"PyInstaller {PYINSTALLER_VERSION} is required in {sys.executable}. "
            "Provision and verify the build environment before running the builder; "
            "the release process never downloads or installs packages automatically."
        )
    return Path(sys.executable)


def create_embedded_project_profile():
    """Create the secret-sanitized deployment profile embedded in the application."""
    from floorterminal.core.project_profile import load_project_profile

    project_profile = load_project_profile(PROJECT_PROFILE_FILE)
    data = json.loads(PROJECT_PROFILE_FILE.read_text(encoding="utf-8"))
    data.pop("settings_password", None)
    data["settings_password_hash"] = project_profile.settings_password_hash
    EMBEDDED_PROJECT_PROFILE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if "settings_password" in EMBEDDED_PROJECT_PROFILE_FILE.read_text(
        encoding="utf-8"
    ).replace("settings_password_hash", ""):
        raise BuildError(
            "Plaintext Settings password leaked into embedded project profile"
        )
    return EMBEDDED_PROJECT_PROFILE_FILE


def clean():
    info("Cleaning previous build and release artifacts")
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    shutil.rmtree(RELEASE_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True)
    RELEASE_DIR.mkdir(parents=True)


def build(system, python):
    info("Compiling native standalone application")
    embedded_project_profile = create_embedded_project_profile()
    staging = WORK_DIR / "native"
    mode = "--onedir" if system == "darwin" else "--onefile"
    args = [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        mode,
        "--name",
        "floorterminal",
        "--paths",
        SOURCE_DIR,
        "--add-data",
        f"{embedded_project_profile}{os.pathsep}.",
        "--distpath",
        staging,
        "--workpath",
        WORK_DIR / "pyinstaller",
        "--specpath",
        WORK_DIR,
    ]
    locales = sorted((SOURCE_DIR / "floorterminal" / "i18n").glob("*.json"))
    if not locales:
        raise BuildError("No packaged UI locale catalogs were found.")
    for locale in locales:
        args.extend(["--add-data", f"{locale}{os.pathsep}floorterminal/i18n"])
    sounds = sorted((SOURCE_DIR / "floorterminal" / "assets" / "sounds").glob("*.wav"))
    if not sounds:
        raise BuildError("No packaged operational sound assets were found.")
    for sound in sounds:
        args.extend(
            [
                "--add-data",
                f"{sound}{os.pathsep}floorterminal/assets/sounds",
            ]
        )
    brand_images = sorted(
        (SOURCE_DIR / "floorterminal" / "assets" / "branding").glob("*.png")
    )
    if not brand_images:
        raise BuildError("No packaged FloorTerminal identity assets were found.")
    for image in brand_images:
        args.extend(
            [
                "--add-data",
                f"{image}{os.pathsep}floorterminal/assets/branding",
            ]
        )
    if system in {"windows", "darwin"}:
        args.append("--windowed")
    args.append(PROJECT_DIR / "main.py")
    run(args, cwd=PROJECT_DIR)
    if system == "windows":
        source = staging / "floorterminal.exe"
    elif system == "darwin":
        source = staging / "floorterminal.app"
    else:
        source = staging / "floorterminal"
    if not source.exists():
        raise BuildError("PyInstaller did not produce the expected native application.")
    target = RELEASE_DIR / source.name
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact_sha256(path):
    """Hash one executable or a complete application directory deterministically."""
    path = Path(path)
    if path.is_file():
        return sha256_file(path)
    digest = hashlib.sha256()
    for item in sorted(
        candidate for candidate in path.rglob("*") if candidate.is_file()
    ):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def render_release_notices(
    project_profile,
    version,
    system,
    architecture,
    artifact_name,
    artifact_hash,
    project_profile_hash,
    config_hash,
    build_id,
    built_at,
    license_text,
):
    """Generate the mandatory open-source notices and reproducible build record."""
    return f"""OPEN-SOURCE SOFTWARE INFORMATION, NOTICES, AND BUILD RECORD
===========================================================

KEEP THIS FILE WITH THE SOFTWARE
This document is generated for one compiled build copy. It must remain beside
the executable or application bundle and be retained with backups and transfers
permitted by the open-source license.

1. PROJECT, MAINTAINER, DISTRIBUTION, AND SUPPORT
Product: {project_profile.product_name}
Product version: {version}
Maintainer / copyright holder: {project_profile.maintainer_name}
Distribution profile: {project_profile.distribution_name}
Support contact: {project_profile.support_contact}
Copyright: {project_profile.copyright_notice}

2. BUILD COPY IDENTIFICATION
Build ID: {build_id}
Built at (UTC): {built_at}
Native target: {system} / {architecture}
Artifact: {artifact_name}
Artifact SHA-256: {artifact_hash}
Embedded project-profile SHA-256: {project_profile_hash}
Operational config-template SHA-256: {config_hash}

The hashes identify this delivered build and its non-secret templates. connector.json is
disabled and credential-free at build time. Runtime logs and saved workflow
state are not included in this document.

3. LICENSE MODEL
License: {project_profile.license_name}
License version: {project_profile.license_version}
SPDX license identifier: {project_profile.license_identifier}
Summary: {project_profile.license_summary}

This project is open-source software. The MIT License permits use, copying,
modification, merging, publication, distribution, sublicensing, and sale, subject
to retaining its copyright and permission notice. Read the complete license below.

4. OPEN-SOURCE USE AND CONTRIBUTIONS
Users may build, operate, study, modify, and redistribute the software under the
MIT License. Contributions should avoid credentials, personal data, proprietary
API material, and deployment-specific secrets. Third-party connectors remain subject
to the connected service's own authorization, documentation, and terms.

5. OPERATIONAL, SAFETY, AND HUMAN-DECISION NOTICE
This software supports downtime reporting, maintenance coordination, response-record
updates, messaging, timers, and operational records. It does not replace trained
operators, engineering judgment, machine guarding, emergency stops, lockout/
tagout, permit systems, quality controls, regulatory duties, risk assessments,
or site safety procedures. People remain responsible for verifying equipment is
safe before work starts and before production resumes.

6. DATA, SECURITY, NETWORK, AND THIRD-PARTY NOTICE
The deployer controls API credentials, accounts, permissions, devices, networks,
backups, log retention, personal data, and lawful processing. The deployer must
protect connector.json and config.json, restrict device access, keep
system time accurate, monitor storage, and validate external-service permissions.
Maintenance platforms, APIs, operating systems, libraries, networks, and other
third-party services have separate terms, limits, availability, security, and
charges. The project maintainers do not control those services.

7. SUPPORT, UPDATES, AND COMPATIBILITY
The MIT License provides the software as-is without warranty. Community or
maintainer support is not guaranteed. Test each build and connector in a controlled
environment before production deployment.

8. DOCUMENT SCOPE
The complete MIT License appended below controls copyright permissions. Safety,
privacy, security, operational, and third-party-service responsibilities are
practical notices and do not modify the MIT License.

9. RELEASE VERIFICATION
Keep LICENSE, this notice, DEPLOYMENT.txt, and SHA256SUMS with the artifact.
Use SHA256SUMS to verify that release files are unchanged. The artifact hash above
identifies the executable or complete application bundle before this notice and
release checksum manifest were generated.

10. COMPLETE CONTROLLING LICENSE
----- BEGIN LICENSE -----
{license_text.rstrip()}
----- END LICENSE -----
"""


def _tk_version():
    """Report the Tk build the frozen application will carry, or NOASSERTION."""
    try:
        import tkinter

        return str(tkinter.TkVersion)
    except Exception:
        return "NOASSERTION"


def write_sbom(
    project_profile, version, system, architecture, artifact, build_id, built_at
):
    """Write a deterministic SPDX 2.3 inventory for the application and build tool."""
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{project_profile.product_name} {version}",
        "documentNamespace": f"urn:uuid:{build_id}",
        "creationInfo": {
            "created": built_at,
            "creators": [
                f"Organization: {project_profile.maintainer_name}",
                "Tool: floorterminal-release-builder",
            ],
        },
        "packages": [
            {
                "name": project_profile.product_name,
                "SPDXID": "SPDXRef-Package-Application",
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": project_profile.license_identifier,
                "licenseDeclared": project_profile.license_identifier,
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": artifact_sha256(artifact),
                    }
                ],
                "comment": f"Native target: {system}/{architecture}",
            },
            {
                "name": "PyInstaller",
                "SPDXID": "SPDXRef-Package-PyInstaller",
                "versionInfo": PYINSTALLER_VERSION,
                "downloadLocation": "https://pypi.org/project/pyinstaller/",
                "filesAnalyzed": False,
                "licenseConcluded": "GPL-2.0-or-later WITH Bootloader-exception",
                "licenseDeclared": "GPL-2.0-or-later WITH Bootloader-exception",
            },
            {
                # The interpreter and its standard library are frozen into the
                # artifact, so they are part of what is shipped and must appear
                # in the inventory an operator or assessor reads.
                "name": "CPython",
                "SPDXID": "SPDXRef-Package-CPython",
                "versionInfo": platform.python_version(),
                "downloadLocation": "https://www.python.org/downloads/",
                "filesAnalyzed": False,
                "licenseConcluded": "PSF-2.0",
                "licenseDeclared": "PSF-2.0",
                "comment": (
                    f"Embedded runtime and standard library; "
                    f"{platform.python_implementation()} as built for {system}/{architecture}"
                ),
            },
            {
                "name": "Tcl/Tk",
                "SPDXID": "SPDXRef-Package-TclTk",
                "versionInfo": _tk_version(),
                "downloadLocation": "https://www.tcl-lang.org/",
                "filesAnalyzed": False,
                "licenseConcluded": "TCL",
                "licenseDeclared": "TCL",
                "comment": "Toolkit providing the touchscreen surface",
            },
        ],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package-Application",
            },
            {
                "spdxElementId": "SPDXRef-Package-PyInstaller",
                "relationshipType": "BUILD_DEPENDENCY_OF",
                "relatedSpdxElement": "SPDXRef-Package-Application",
            },
            {
                "spdxElementId": "SPDXRef-Package-CPython",
                "relationshipType": "CONTAINED_BY",
                "relatedSpdxElement": "SPDXRef-Package-Application",
            },
            {
                "spdxElementId": "SPDXRef-Package-TclTk",
                "relationshipType": "CONTAINED_BY",
                "relatedSpdxElement": "SPDXRef-Package-Application",
            },
        ],
    }
    (RELEASE_DIR / SBOM_FILE).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def copy_runtime(system, architecture, build_id, built_at):
    info("Creating minimal production runtime bundle")
    from floorterminal import __version__
    from floorterminal.core.project_profile import load_project_profile

    project_profile = load_project_profile(PROJECT_PROFILE_FILE)
    shutil.copy2(PROJECT_DIR / "config.json", RELEASE_DIR / "config.json")
    shutil.copy2(PROJECT_DIR / "LICENSE", RELEASE_DIR / "LICENSE")
    # The installer reads VERSION to name this release's immutable version slot.
    (RELEASE_DIR / "VERSION").write_text(f"{__version__}\n", encoding="utf-8")
    integration = RELEASE_DIR / "connector.json"
    shutil.copy2(PROJECT_DIR / "connector.json", integration)
    if system != "windows":
        integration.chmod(stat.S_IRUSR | stat.S_IWUSR)
    if system == "linux":
        desktop = (ASSETS_DIR / "floorterminal.desktop").read_text(encoding="utf-8")
        desktop = desktop.replace(
            "Name=FloorTerminal", f"Name={project_profile.product_short_name}", 1
        )
        (RELEASE_DIR / "floorterminal.desktop").write_text(desktop, encoding="utf-8")
        shutil.copy2(ASSETS_DIR / "install.sh", RELEASE_DIR / "install.sh")
        (RELEASE_DIR / "install.sh").chmod(0o755)
        shutil.copy2(
            ASSETS_DIR / "floorterminal-launch", RELEASE_DIR / "floorterminal-launch"
        )
        (RELEASE_DIR / "floorterminal-launch").chmod(0o755)
        shutil.copy2(
            ASSETS_DIR / "floorterminal.service",
            RELEASE_DIR / "floorterminal.service",
        )
        shutil.copy2(
            ASSETS_DIR / "floorterminal-icon.png",
            RELEASE_DIR / "floorterminal-icon.png",
        )
    deployment = RELEASE_DIR / "DEPLOYMENT.txt"
    artifact = (
        "floorterminal.exe"
        if system == "windows"
        else ("floorterminal.app" if system == "darwin" else "floorterminal")
    )
    artifact_path = RELEASE_DIR / artifact
    if system == "linux":
        install_steps = """INSTALL ON 64-BIT RASPBERRY PI OS
1. Read this file, LICENSE, and SOFTWARE_INFORMATION_AND_NOTICES.txt.
2. Run: sha256sum -c SHA256SUMS
3. Confirm: file floorterminal  (must report ELF 64-bit ARM aarch64)
4. Run: chmod +x install.sh floorterminal-launch floorterminal
5. Run: ./install.sh
6. Reboot into the graphical session: sudo reboot

The bundle is an application, not a Raspberry Pi OS disk image. A graphical
display session is required. The installer deploys to /opt/floorterminal,
preserves existing config.json and connector.json on upgrade, and enables a
supervised per-user fullscreen startup.

MANAGED VERSION SLOTS AND OFFLINE UPDATES
Each release is installed under versions/<version>/ and the running version is
selected by one symbolic link, so switching versions replaces nothing else.
floorterminal-launch is the supervised launcher: it counts start attempts for a newly
activated version and restores the previous one automatically if the new version
cannot start. Later versions are installed offline from a USB drive labelled
FLOORTERM after an administrator authorizes the change on the touchscreen; see
docs/update-user-guide.md in the public source repository.
"""
    elif system == "darwin":
        install_steps = """INSTALL ON MACOS
Verify SHA256SUMS, keep every delivered file together, and launch the application
bundle on a compatible Mac. macOS builds are for development/acceptance and do not
run on Raspberry Pi.
"""
    else:
        install_steps = """INSTALL ON WINDOWS
Verify SHA256SUMS, keep every delivered file together, and launch the executable on
a compatible Windows system. Windows builds do not run on Raspberry Pi.
"""
    notices = render_release_notices(
        project_profile,
        __version__,
        system,
        architecture,
        artifact,
        artifact_sha256(artifact_path),
        sha256_file(EMBEDDED_PROJECT_PROFILE_FILE),
        sha256_file(PROJECT_DIR / "config.json"),
        build_id,
        built_at,
        (PROJECT_DIR / "LICENSE").read_text(encoding="utf-8"),
    )
    (RELEASE_DIR / RELEASE_NOTICES).write_text(notices, encoding="utf-8")
    write_sbom(
        project_profile,
        __version__,
        system,
        architecture,
        artifact_path,
        build_id,
        built_at,
    )
    deployment.write_text(
        f"{project_profile.product_name.upper()}\n"
        f"Distribution profile: {project_profile.distribution_name}\n"
        f"Maintainer: {project_profile.maintainer_name}\n"
        f"Support: {project_profile.support_contact}\n"
        f"License: {project_profile.license_name} {project_profile.license_version}\n"
        f"License ID: {project_profile.license_identifier}\n"
        f"License summary: {project_profile.license_summary}\n"
        f"Build ID: {build_id}\n"
        f"Software notices: {RELEASE_NOTICES}\n\n"
        f"Native target: {system} / {architecture}\n"
        f"Application: {artifact}\n\n"
        f"{install_steps}\n"
        "FIRST CONFIGURATION\n"
        "The standard release initial Settings password is admin@123 (public).\n"
        "A custom build may use a different initial password from its distributor.\n"
        "Open Settings > System > Change Settings password before production use.\n"
        "Verify the current password, enter a new one, and confirm it. The old\n"
        "password then stops working; there is no master-password override.\n"
        "Only a salted verifier is saved in private settings_auth.json at the\n"
        "runtime root. Preserve it during upgrades and keep it out of Git/releases.\n"
        "Configure the line, stations, per-station failures, workflow, accessibility,\n"
        "sound, storage, and retention in protected Settings.\n\n"
        "connector.json is the only external integration contract. It is disabled and\n"
        "contains no credential in the release template. Local reporting works without\n"
        "it. Complete Connector v1 through protected Settings or managed deployment only\n"
        "when authorized, then restart and acceptance-test each enabled capability.\n\n"
        "config.json contains runtime configuration. Logs and response_state.json\n"
        "are created automatically beside the installed application. For detailed\n"
        "installation, operation, upgrade, rollback, and troubleshooting instructions,\n"
        "see docs/prebuilt-raspberry-pi.md in the public source repository.\n",
        encoding="utf-8",
    )


def native_artifact(system):
    if system == "windows":
        candidates = [RELEASE_DIR / "floorterminal.exe"]
    elif system == "darwin":
        candidates = [
            RELEASE_DIR / "floorterminal.app",
            RELEASE_DIR / "floorterminal",
        ]
    else:
        candidates = [RELEASE_DIR / "floorterminal"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise BuildError("PyInstaller did not produce the expected native application.")


def checksum_tree():
    rows = []
    for path in sorted(RELEASE_DIR.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(f"{digest}  {path.relative_to(RELEASE_DIR).as_posix()}")
    (RELEASE_DIR / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")


def audit(system, architecture):
    info("Auditing release contents")
    from floorterminal import __version__
    from floorterminal.core.project_profile import load_project_profile

    project_profile = load_project_profile(PROJECT_PROFILE_FILE)
    project_profile_value = lambda name: str(getattr(project_profile, name))
    artifact = native_artifact(system)
    forbidden_names = {"response_state.json", "settings_auth.json", "auth_throttle.json", ".DS_Store"}
    notices = RELEASE_DIR / RELEASE_NOTICES
    if not notices.is_file():
        raise BuildError(f"Release is missing mandatory {RELEASE_NOTICES}.")
    notices_text = notices.read_text(encoding="utf-8")
    required_notice_values = (
        "BEGIN LICENSE",
        "END LICENSE",
        project_profile_value("product_name"),
        project_profile_value("maintainer_name"),
        project_profile_value("distribution_name"),
        project_profile_value("support_contact"),
        project_profile_value("copyright_notice"),
        project_profile_value("license_name"),
        project_profile_value("license_identifier"),
        project_profile_value("license_version"),
        project_profile_value("license_summary"),
        __version__,
        f"{system} / {architecture}",
        artifact.name,
        artifact_sha256(artifact),
        sha256_file(EMBEDDED_PROJECT_PROFILE_FILE),
        sha256_file(PROJECT_DIR / "config.json"),
        (PROJECT_DIR / "LICENSE").read_text(encoding="utf-8").rstrip(),
    )
    build_record_patterns = (
        r"Build ID: [0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}",
        r"Built at \(UTC\): \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
    )
    if any(value not in notices_text for value in required_notice_values) or any(
        re.search(pattern, notices_text) is None for pattern in build_record_patterns
    ):
        raise BuildError(
            f"{RELEASE_NOTICES} is incomplete or does not match this build."
        )
    if not (RELEASE_DIR / "LICENSE").is_file():
        raise BuildError("Release is missing the required LICENSE file.")
    if (RELEASE_DIR / "LICENSE").read_bytes() != (PROJECT_DIR / "LICENSE").read_bytes():
        raise BuildError("Release LICENSE does not match the audited project license.")
    try:
        sbom = json.loads((RELEASE_DIR / SBOM_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(f"Release is missing a valid {SBOM_FILE}: {exc}") from exc
    if (
        sbom.get("spdxVersion") != "SPDX-2.3"
        or sbom.get("documentNamespace") is None
        or not any(
            package.get("SPDXID") == "SPDXRef-Package-Application"
            and package.get("checksums", [{}])[0].get("checksumValue")
            == artifact_sha256(artifact)
            for package in sbom.get("packages", [])
        )
    ):
        raise BuildError(f"{SBOM_FILE} does not match this build.")
    if (RELEASE_DIR / "project_profile.json").exists():
        raise BuildError(
            "Project profile must be embedded, not copied beside the executable."
        )
    forbidden_suffixes = {".py", ".pyc", ".spec", ".jsonl"}
    for path in RELEASE_DIR.rglob("*"):
        if path.name in forbidden_names or (
            path.is_file() and path.suffix.lower() in forbidden_suffixes
        ):
            raise BuildError(
                f"Forbidden build/runtime file leaked into release: {path.relative_to(RELEASE_DIR)}"
            )
    integration_data = json.loads(
        (RELEASE_DIR / "connector.json").read_text(encoding="utf-8")
    )
    if integration_data.get("enabled") or any(
        str(value).strip() for value in integration_data.get("credentials", {}).values()
    ):
        raise BuildError(
            "Release connector.json must be disabled and contain no credentials."
        )
    source_profile = json.loads(PROJECT_PROFILE_FILE.read_text(encoding="utf-8"))
    plaintext_password = source_profile.get("settings_password")
    password_candidates = [plaintext_password]
    if plaintext_password == "${FLOORTERMINAL_SETTINGS_PASSWORD}":
        password_candidates.append(os.environ.get("FLOORTERMINAL_SETTINGS_PASSWORD"))
    for password in password_candidates:
        # Only this deliberately published bootstrap value is not a secret.
        # Private build passwords must still never appear in release files.
        if not isinstance(password, str) or not password or password == "admin@123":
            continue
        password_bytes = password.encode("utf-8")
        for path in RELEASE_DIR.rglob("*"):
            if path.is_file() and password_bytes in path.read_bytes():
                raise BuildError(
                    "Plaintext Settings password leaked into release file: "
                    f"{path.relative_to(RELEASE_DIR)}"
                )
    if system == "windows":
        binary = artifact.read_bytes()[:2]
        if binary != b"MZ":
            raise BuildError("Windows executable has an invalid header.")
    elif system == "linux":
        if artifact.read_bytes()[:4] != b"\x7fELF":
            raise BuildError("Linux executable has an invalid ELF header.")
        if architecture == "aarch64" and shutil.which("file"):
            output = subprocess.check_output(["file", str(artifact)], text=True)
            if "aarch64" not in output.lower() and "arm64" not in output.lower():
                raise BuildError("Linux executable architecture is not ARM64.")
    elif system == "darwin":
        binary = (
            artifact / "Contents/MacOS/floorterminal" if artifact.is_dir() else artifact
        )
        if not binary.exists():
            raise BuildError("macOS application contains no executable.")
    checksum_tree()
    count = sum(1 for path in RELEASE_DIR.rglob("*") if path.is_file())
    print(
        f"   Release audit passed: {count} files; neutral connector template; no source/log/state files"
    )


def main():
    recorder = BuildRecorder()
    system = None
    architecture = None
    outcome = "failed"
    error_message = None
    try:
        info(f"Build ID: {recorder.build_id}")
        system, architecture = host()
        validate_host(system, architecture)
        project_profile = validate_project()
        validate_tests(system)
        configure_release_directory(project_profile, recorder.build_id)
        info(f"Release destination: {RELEASE_DIR.relative_to(PROJECT_DIR)}")
        python = prepare_tools(system)
        clean()
        build(system, python)
        copy_runtime(system, architecture, recorder.build_id, recorder.started_at)
        audit(system, architecture)
        recorder.verify_source_inputs()
        outcome = "success"
        info("BUILD COMPLETE")
        print(f"Release folder: {RELEASE_DIR}")
        print("No ZIP was created. Review the folder and create the archive yourself.")
        return 0
    except BuildError as exc:
        error_message = str(exc)
        print(f"\nBUILD FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        error_message = f"Unexpected {type(exc).__name__}: {exc}"
        print(f"\nBUILD FAILED: {error_message}", file=sys.stderr)
        return 1
    finally:
        recorder.finish(outcome, error_message, system, architecture)


if __name__ == "__main__":
    raise SystemExit(main())
