import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from floorterminal.update import journal, trust
from floorterminal.update.layout import InstallLayout

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "packaging" / "linux" / "install.sh"
PACKAGING = ROOT / "packaging" / "linux"

# Minimal stand-ins for the privileged and GNU-only commands the installer uses,
# so the real script can be executed unprivileged on any developer machine.
SHIMS = {
    "sudo": """#!/usr/bin/env python3
import os, re, sys
argv = sys.argv[1:]
while argv and argv[0] in {"-u", "-g"}:
    argv = argv[2:]
while argv and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
    name, value = argv.pop(0).split("=", 1)
    os.environ[name] = value
if not argv:
    raise SystemExit("sudo test shim received no command")
os.execvp(argv[0], argv)
""",
    "getent": """#!/usr/bin/env python3
import os, sys
user = sys.argv[2]
print(f"{user}:x:1000:1000::{os.environ['FAKE_HOME']}:/bin/sh")
""",
    "install": """#!/usr/bin/env python3
import os, shutil, sys
mode, directory, paths = 0o755, False, []
argv = sys.argv[1:]
while argv:
    token = argv.pop(0)
    if token == "-d":
        directory = True
    elif token == "-m":
        mode = int(argv.pop(0), 8)
    elif token in {"-o", "-g"}:
        argv.pop(0)
    else:
        paths.append(token)
if directory:
    for path in paths:
        os.makedirs(path, mode=mode, exist_ok=True)
        os.chmod(path, mode)
else:
    source, destination = paths[0], paths[-1]
    shutil.copyfile(source, destination)
    os.chmod(destination, mode)
""",
    "systemctl": "#!/bin/sh\nexit 0\n",
    "chown": "#!/bin/sh\nexit 0\n",
    "sha256sum": """#!/usr/bin/env python3
import hashlib, sys
if sys.argv[1:2] == ["-c"]:
    for row in open(sys.argv[2]):
        digest, name = row.strip().split("  ", 1)
        actual = hashlib.sha256(open(name, "rb").read()).hexdigest()
        print(f"{name}: {'OK' if actual == digest else 'FAILED'}")
        if actual != digest:
            raise SystemExit(1)
else:
    for name in sys.argv[1:]:
        print(f"{hashlib.sha256(open(name, 'rb').read()).hexdigest()}  {name}")
""",
}


def executable_bytes(marker):
    body = b"\x7fELF" + marker.encode("ascii")
    return body + b"\x00" * (4096 - len(body))


class InstallerScriptTests(unittest.TestCase):
    """Run the real Raspberry Pi installer against a sandboxed deployment root."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.work, ignore_errors=True))
        self.bin = self.work / "shims"
        self.bin.mkdir()
        for name, body in SHIMS.items():
            path = self.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        self.target = self.work / "opt" / "floorterminal"
        self.home = self.work / "home"
        self.home.mkdir()

    def release(self, version="1.1.0", marker=None):
        source = self.work / f"release-{version}"
        source.mkdir(parents=True, exist_ok=True)
        (source / trust.EXECUTABLE_NAME).write_bytes(executable_bytes(marker or version))
        (source / "VERSION").write_text(f"{version}\n", encoding="utf-8")
        for name in ("LICENSE", "SOFTWARE_INFORMATION_AND_NOTICES.txt", "SBOM.spdx.json"):
            (source / name).write_text(f"{name} for {version}\n", encoding="utf-8")
        for name in ("config.json", "connector.json"):
            (source / name).write_text(json.dumps({"from": version}), encoding="utf-8")
        for name in ("floorterminal-launch", "install.sh"):
            shutil.copy(PACKAGING / name, source / name)
            (source / name).chmod(0o755)
        for name in ("floorterminal.desktop", "floorterminal.service"):
            shutil.copy(PACKAGING / name, source / name)
        shutil.copy(PACKAGING / "floorterminal-icon.png", source)
        rows = []
        for path in sorted(source.iterdir()):
            if path.name != "SHA256SUMS":
                import hashlib

                rows.append(
                    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
                )
        (source / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")
        return source

    def run_installer(self, source):
        return subprocess.run(
            ["bash", str(source / "install.sh")],
            cwd=source,
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
                "HOME": str(self.home),
                "USER": os.environ.get("USER", "tester"),
                "FAKE_HOME": str(self.home),
                "FLOORTERMINAL_INSTALL_ROOT": str(self.target),
            },
        )

    def test_a_first_installation_creates_a_managed_layout(self):
        result = self.run_installer(self.release("1.0.0"))
        self.assertEqual(result.returncode, 0, result.stderr)
        layout = InstallLayout(self.target)
        self.assertTrue(layout.managed)
        self.assertEqual(layout.active_version(), "1.0.0")
        self.assertEqual(
            os.readlink(layout.active_link), "versions/1.0.0/floorterminal"
        )
        self.assertTrue(layout.slot_executable("1.0.0").is_file())
        self.assertTrue(layout.launcher.is_file())
        self.assertTrue(os.access(layout.launcher, os.X_OK))
        self.assertTrue(layout.staging_dir.is_dir())
        boot = journal.read_boot_state(layout.boot_state)
        self.assertEqual(boot["STATUS"], "confirmed")
        self.assertEqual(boot["ACTIVE"], "1.0.0")
        self.assertEqual(boot["PREVIOUS"], "")

    def test_deployment_data_survives_a_reinstallation(self):
        self.run_installer(self.release("1.0.0"))
        (self.target / "config.json").write_text('{"line_name": "Site owned"}', encoding="utf-8")
        (self.target / "connector.json").write_text('{"enabled": false}', encoding="utf-8")
        (self.target / "response_state.json").write_text('{"status": "DOWN"}', encoding="utf-8")
        result = self.run_installer(self.release("1.1.0"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preserved existing config.json", result.stdout)
        self.assertIn("Preserved existing connector.json", result.stdout)
        self.assertEqual(
            json.loads((self.target / "config.json").read_text())["line_name"], "Site owned"
        )
        self.assertEqual(
            json.loads((self.target / "response_state.json").read_text())["status"], "DOWN"
        )

    def test_an_upgrade_keeps_the_earlier_slot_available(self):
        self.run_installer(self.release("1.0.0"))
        self.run_installer(self.release("1.1.0"))
        layout = InstallLayout(self.target)
        self.assertEqual(layout.active_version(), "1.1.0")
        self.assertEqual(layout.installed_versions(), ("1.0.0", "1.1.0"))
        self.assertEqual(
            layout.slot_executable("1.0.0").read_bytes(), executable_bytes("1.0.0")
        )

    def test_an_earlier_flat_installation_is_migrated_and_preserved(self):
        self.target.mkdir(parents=True)
        legacy = self.target / trust.EXECUTABLE_NAME
        legacy.write_bytes(executable_bytes("legacy"))
        legacy.chmod(0o755)
        result = self.run_installer(self.release("1.1.0"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preserved the previously installed executable", result.stdout)
        layout = InstallLayout(self.target)
        self.assertTrue(layout.managed)
        preserved = list((self.target / "update").glob("replaced-executable-*"))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0].read_bytes(), executable_bytes("legacy"))

    def test_a_malformed_version_marker_stops_the_installation(self):
        source = self.release("1.1.0")
        (source / "VERSION").write_text("../../etc\n", encoding="utf-8")
        import hashlib

        rows = [
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
            for path in sorted(source.iterdir())
            if path.name != "SHA256SUMS"
        ]
        (source / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")
        result = self.run_installer(source)
        self.assertEqual(result.returncode, 1)
        self.assertIn("supported release identifier", result.stderr)
        self.assertFalse((self.target / "versions").exists())

    def test_a_failed_checksum_stops_the_installation(self):
        source = self.release("1.1.0")
        (source / trust.EXECUTABLE_NAME).write_bytes(executable_bytes("substituted"))
        result = self.run_installer(source)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.target / "versions").exists())

    def test_installed_files_are_owner_private(self):
        self.run_installer(self.release("1.0.0"))
        layout = InstallLayout(self.target)
        for path in (self.target, layout.versions_dir, layout.update_dir, layout.staging_dir):
            with self.subTest(path=path.name):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(layout.slot_executable("1.0.0").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(layout.boot_state.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.target / "config.json").stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
