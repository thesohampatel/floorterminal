import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from floorterminal.update import trust

LAUNCHER = Path(__file__).resolve().parents[2] / "packaging" / "linux" / "floorterminal-launch"


class SupervisedLauncherTests(unittest.TestCase):
    """Exercise the POSIX-shell boot watchdog that guards a failed update."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "floorterminal"
        (self.root / "bin").mkdir(parents=True)
        (self.root / "update").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.root.parent, ignore_errors=True))
        shutil.copy(LAUNCHER, self.root / "bin" / "floorterminal-launch")
        (self.root / "bin" / "floorterminal-launch").chmod(0o755)
        for release in ("1.0.0", "1.1.0"):
            self.install(release)
        self.link("1.1.0")

    def install(self, release, body=None):
        slot = self.root / "versions" / release
        slot.mkdir(parents=True, exist_ok=True)
        script = slot / trust.EXECUTABLE_NAME
        script.write_text(
            body
            or f'#!/bin/sh\necho "started {release} home=$FLOORTERMINAL_HOME '
            'supervised=$FLOORTERMINAL_SUPERVISED"\n',
            encoding="utf-8",
        )
        script.chmod(0o755)
        return script

    def link(self, release):
        link = self.root / trust.EXECUTABLE_NAME
        if link.is_symlink() or link.exists():
            link.unlink()
        os.symlink(f"versions/{release}/{trust.EXECUTABLE_NAME}", link)

    def write_state(self, **values):
        defaults = {
            "SCHEMA": "1",
            "STATUS": "confirmed",
            "ACTIVE": "1.1.0",
            "PREVIOUS": "1.0.0",
            "ATTEMPTS": "0",
            "LIMIT": "3",
        }
        defaults.update({key: str(value) for key, value in values.items()})
        (self.root / "update" / "boot_state").write_text(
            "".join(f"{key}={value}\n" for key, value in defaults.items()), encoding="ascii"
        )

    def launch(self):
        return subprocess.run(
            [str(self.root / "bin" / "floorterminal-launch")],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )

    def state(self):
        path = self.root / "update" / "boot_state"
        values = {}
        for line in path.read_text(encoding="ascii").splitlines():
            key, _, value = line.partition("=")
            values[key] = value
        return values

    def active(self):
        return os.readlink(self.root / trust.EXECUTABLE_NAME).split("/")[1]

    # ------------------------------------------------------------------ tests

    def test_starts_the_active_version_with_the_deployment_root_exported(self):
        self.write_state()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("started 1.1.0", result.stdout)
        self.assertIn(f"home={self.root.resolve()}", result.stdout)
        self.assertIn("supervised=1", result.stdout)

    def test_counts_probation_starts_without_changing_the_version(self):
        self.write_state(STATUS="probation", ATTEMPTS=0)
        for expected in (1, 2, 3):
            result = self.launch()
            self.assertIn("started 1.1.0", result.stdout)
            self.assertEqual(self.state()["ATTEMPTS"], str(expected))
            self.assertEqual(self.active(), "1.1.0")

    def test_restores_the_previous_version_once_attempts_are_exhausted(self):
        self.write_state(STATUS="probation", ATTEMPTS=3)
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("started 1.0.0", result.stdout)
        self.assertEqual(self.active(), "1.0.0")
        values = self.state()
        self.assertEqual(values["STATUS"], "rolled_back")
        self.assertEqual(values["ACTIVE"], "1.0.0")
        self.assertEqual(values["PREVIOUS"], "1.1.0")
        self.assertEqual(values["ATTEMPTS"], "0")
        log = (self.root / "update" / "update-log.jsonl").read_text(encoding="utf-8")
        self.assertIn("update_watchdog_rollback", log)

    def test_a_recovered_terminal_stays_on_the_restored_version(self):
        self.write_state(STATUS="probation", ATTEMPTS=3)
        self.launch()
        for _ in range(3):
            result = self.launch()
            self.assertIn("started 1.0.0", result.stdout)
            self.assertEqual(self.active(), "1.0.0")

    def test_never_rolls_back_when_the_previous_slot_is_gone(self):
        shutil.rmtree(self.root / "versions" / "1.0.0")
        self.write_state(STATUS="probation", ATTEMPTS=9)
        result = self.launch()
        self.assertIn("started 1.1.0", result.stdout)
        self.assertEqual(self.active(), "1.1.0")

    def test_a_damaged_state_file_still_starts_the_terminal(self):
        (self.root / "update" / "boot_state").write_text(
            "STATUS=probation\nATTEMPTS=not-a-number\nPREVIOUS=../../etc\n"
            "ACTIVE=$(whoami)\nrm -rf /\n",
            encoding="ascii",
        )
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("started 1.1.0", result.stdout)
        self.assertEqual(self.active(), "1.1.0")

    def test_a_missing_state_file_still_starts_the_terminal(self):
        (self.root / "update" / "boot_state").unlink(missing_ok=True)
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("started 1.1.0", result.stdout)

    def test_never_treats_state_values_as_shell_commands(self):
        marker = self.root / "INJECTED"
        (self.root / "update" / "boot_state").write_text(
            f"STATUS=probation\nPREVIOUS=1.0.0; touch {marker}\nATTEMPTS=9\nLIMIT=1\n",
            encoding="ascii",
        )
        self.launch()
        self.assertFalse(marker.exists())
        self.assertEqual(self.active(), "1.1.0")

    def test_reports_a_clear_failure_when_no_application_is_present(self):
        (self.root / trust.EXECUTABLE_NAME).unlink()
        result = self.launch()
        self.assertEqual(result.returncode, 78)
        self.assertIn("no runnable application", result.stderr)

    def test_a_fixed_executable_installation_is_started_unchanged(self):
        link = self.root / trust.EXECUTABLE_NAME
        link.unlink()
        link.write_text('#!/bin/sh\necho "started flat"\n', encoding="utf-8")
        link.chmod(0o755)
        self.write_state(STATUS="probation", ATTEMPTS=9)
        result = self.launch()
        self.assertIn("started flat", result.stdout)


if __name__ == "__main__":
    unittest.main()
