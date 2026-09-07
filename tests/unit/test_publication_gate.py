"""Offline regression coverage for the maintainer's publication gate."""

import hashlib
import importlib.util
import io
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "publication_gate", ROOT / "scripts/release/verify_publication.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class PublicationGateTests(unittest.TestCase):
    def test_tracked_channel_is_authentic_and_matches_source_identity(self):
        channel = gate.check_source_metadata(ROOT)
        self.assertEqual(channel.release.version, gate.__version__)
        gate.check_actions(ROOT)

    def test_accidentally_included_runtime_or_private_files_are_rejected(self):
        for name in (
            "connector.json",
            "settings_auth.json",
            "release/key.private.json",
            "floorterminal_key/secret.json",
            "logs/activity.jsonl",
            "pi_build_output/archive.tar.gz",
            ".env.production",
            "private.pem",
        ):
            with self.subTest(path=name), self.assertRaises(gate.AuditError):
                gate.check_paths([name])
        gate.check_paths(
            ["connector.example.json", "maintainer_keys/release.public.json"]
        )

    def test_mutable_action_references_fail_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / ".github/workflows/check.yml"
            path.parent.mkdir(parents=True)
            path.write_text("steps:\n  - uses: actions/checkout@v6\n")
            with self.assertRaises(gate.AuditError):
                gate.check_actions(root)

    def test_duplicate_and_traversal_checksum_entries_are_rejected(self):
        value = "a" * 64
        for payload in (
            f"{value}  file\n{value}  file\n",
            f"{value}  ../file\n",
            f"{value}  /file\n",
            "invalid\n",
        ):
            with self.subTest(payload=payload), self.assertRaises(gate.AuditError):
                gate.checksum_rows(payload.encode())

    def test_edited_signed_channel_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "pyproject.toml",
                "config.example.json",
                "connector.example.json",
                "update-channel/latest.json",
                "update-channel/latest.json.sig",
            ):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            path = root / "update-channel/latest.json"
            body = json.loads(path.read_text())
            body["release"]["release_title"] += " changed"
            path.write_text(json.dumps(body))
            with self.assertRaises(ValueError):
                gate.check_source_metadata(root)

    def archive(self, root, *, mutate=None, extra=None):
        header = bytearray(b"\x7fELF\x02\x01" + bytes(14))
        header[18:20] = (183).to_bytes(2, "little")
        data = {name: name.encode() for name in gate.INSTALL_FILES}
        data["floorterminal"] = bytes(header)
        data["VERSION"] = (gate.__version__ + "\n").encode()
        data["SHA256SUMS"] = "".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}\n"
            for name, content in sorted(data.items())
            if name != "SHA256SUMS"
        ).encode()
        if mutate:
            mutate(data)
        path = root / "release.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, content in data.items():
                info = tarfile.TarInfo(f"release/{name}")
                info.size, info.mode = len(content), 0o755
                archive.addfile(info, io.BytesIO(content))
            if extra:
                archive.addfile(extra)
        return path

    def test_streaming_archive_check_passes_without_extracting_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.archive(root)
            gate.audit_archive(archive, "release", gate.INSTALL_FILES)
            self.assertEqual(list(root.iterdir()), [archive])

    def test_corrupt_payload_and_missing_files_fail_the_archive_gate(self):
        for mutate in (
            lambda data: data.update(floorterminal=b"changed"),
            lambda data: data.pop("LICENSE"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                archive = self.archive(Path(directory), mutate=mutate)
                with self.assertRaises(gate.AuditError):
                    gate.audit_archive(archive, "release", gate.INSTALL_FILES)

    def test_archive_symlinks_and_extra_files_are_rejected(self):
        for name, kind in (
            ("release/link", tarfile.SYMTYPE),
            ("../outside", tarfile.REGTYPE),
            ("release/unexpected.txt", tarfile.REGTYPE),
        ):
            extra = tarfile.TarInfo(name)
            extra.type, extra.linkname = (
                kind,
                "/outside" if kind == tarfile.SYMTYPE else "",
            )
            with tempfile.TemporaryDirectory() as directory:
                archive = self.archive(Path(directory), extra=extra)
                with self.assertRaises(gate.AuditError):
                    gate.audit_archive(archive, "release", gate.INSTALL_FILES)
