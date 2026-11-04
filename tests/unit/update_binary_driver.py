"""Opt-in native executable acceptance in a disposable managed installation.

The old slot is a fixture, not a certified old binary. The real candidate is
signed with a throwaway in-memory key; installed software and release keys are
never used. No real connector calls or GUI interaction occur here.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from floorterminal import __version__
from floorterminal.core import config
from floorterminal.update import compatibility, installer, media, trust
from floorterminal.update.layout import InstallLayout
from tests.unit.update_fixtures import (
    build_installation,
    make_key,
    write_update_drive,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    candidate = args.executable.resolve()
    with tempfile.TemporaryDirectory(
        prefix="floorterminal-binary-update-"
    ) as directory:
        work = Path(directory)
        layout = InstallLayout(build_installation(work / "installation", "1.1.0"))
        installer.initialise(layout, "1.1.0")
        raw = {
            "line_name": "Offline update acceptance",
            "future_extension": {"kept": True},
        }
        runtime = layout.root / "config.json"
        runtime.write_text(json.dumps(raw))
        for name in ("connector.json", "spare.connector.json"):
            (layout.root / name).write_bytes(
                (ROOT / "connector.example.json").read_bytes()
            )
        (layout.root / ".active_connector").write_text("spare.connector.json\n")
        before = compatibility.runtime_files(layout.root)
        seed, key, anchor = make_key()
        with mock.patch.object(trust, "TRUSTED_KEYS", (anchor,)):
            mount = write_update_drive(
                work / "usb", seed, key, __version__, artifact=candidate.read_bytes()
            )
            media.stage(layout, media.read_package(mount), expect_executable=True)
            # Exercise the actual candidate subprocess as a different-version
            # parent would. Only the parent's advertised version is substituted.
            with mock.patch.object(compatibility, "__version__", "1.1.0"):
                installer.activate(layout, __version__, authorized_by="Offline test")
            compatibility.probe_target(layout.active_link, layout.root, __version__)
            installer.confirm(layout)
            installer.rollback(layout, "1.1.0", authorized_by="Offline test")
            assert compatibility.runtime_files(layout.root) == before
            runtime.write_text(json.dumps({"line_name": "Edited on older version"}))
            installer.rollback(layout, __version__, authorized_by="Offline test")
            with mock.patch.object(config, "CONFIG_FILE", runtime):
                restored = config.load_config()
            assert restored["future_extension"] == {"kept": True}
            assert restored["line_name"] == "Edited on older version"
            for name, payload in before.items():
                if name != "config.json":
                    assert (layout.root / name).read_bytes() == payload
            compatibility.probe_target(layout.active_link, layout.root, __version__)
        print(
            json.dumps(
                {
                    "native_candidate": __version__,
                    "authenticated_activation": True,
                    "actual_headless_probes": True,
                    "rollback_round_trip": True,
                    "connectors_unchanged": True,
                    "legacy_extensions_restored": True,
                    "newer_edits_preserved": True,
                    "real_service_calls": 0,
                    "old_slot_is_fixture": True,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
