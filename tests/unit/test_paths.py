import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class RuntimePathTests(unittest.TestCase):
    def test_source_runtime_root_is_repository_root(self):
        from floorterminal.core.paths import RUNTIME_ROOT

        self.assertEqual(RUNTIME_ROOT, Path(__file__).resolve().parents[2])

    def test_managed_frozen_launches_keep_data_out_of_version_slots(self):
        from floorterminal.core import paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "versions" / "1.0.0" / "floorterminal"
            executable.parent.mkdir(parents=True)
            executable.touch()
            active = root / "floorterminal"
            active.symlink_to(executable)
            for path in (executable, active):
                with (
                    self.subTest(path=path.name),
                    mock.patch.dict(os.environ, {}, clear=True),
                    mock.patch.object(sys, "frozen", True, create=True),
                    mock.patch.object(sys, "executable", str(path)),
                ):
                    self.assertEqual(paths._runtime_root(), root)

    def test_portable_and_macos_bundles_keep_the_existing_runtime_roots(self):
        from floorterminal.core import paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for executable in (
                root / "floorterminal",
                root / "FloorTerminal.app" / "Contents" / "MacOS" / "floorterminal",
            ):
                with (
                    self.subTest(path=executable.name),
                    mock.patch.dict(os.environ, {}, clear=True),
                    mock.patch.object(sys, "frozen", True, create=True),
                    mock.patch.object(sys, "executable", str(executable)),
                ):
                    self.assertEqual(paths._runtime_root(), root)

    def test_environment_override_is_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                **os.environ,
                "FLOORTERMINAL_HOME": directory,
                "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            }
            result = subprocess.check_output(
                [
                    sys.executable,
                    "-c",
                    "from floorterminal.core.paths import RUNTIME_ROOT; print(RUNTIME_ROOT)",
                ],
                text=True,
                env=environment,
            ).strip()
            self.assertEqual(Path(result), Path(directory).resolve())


if __name__ == "__main__":
    unittest.main()
