import importlib.util
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/release/build_update_package.py"
SPEC = importlib.util.spec_from_file_location("update_packager", SCRIPT)
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


class UpdatePackagingTests(unittest.TestCase):
    def test_update_keeps_release_legal_and_dependency_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "update"
            output.mkdir()
            binary = root / "floorterminal"
            binary.write_bytes(b"executable")
            with self.assertRaises(SystemExit):
                packager.copy_release_notices(binary, output)
            required = (
                "LICENSE",
                "SOFTWARE_INFORMATION_AND_NOTICES.txt",
                "SBOM.spdx.json",
                "VERSION",
            )
            for name in required:
                (root / name).write_text(name)
            packager.copy_release_notices(binary, output)
            self.assertEqual({path.name for path in output.iterdir()}, set(required))
            for name in required:
                self.assertEqual(
                    (root / name).read_bytes(), (output / name).read_bytes()
                )

    def test_public_archive_strips_build_host_identity_and_rejects_links(self):
        member = tarfile.TarInfo("floorterminal")
        member.uname = "build-account"
        member.gname = "build-group"
        member.uid = member.gid = 1000
        member.mode = 0o755
        result = packager.public_archive_member(member)
        self.assertEqual(
            (result.uid, result.gid, result.uname, result.gname), (0, 0, "", "")
        )
        self.assertEqual(result.mode, 0o755)
        member.type = tarfile.SYMTYPE
        with self.assertRaises(SystemExit):
            packager.public_archive_member(member)
