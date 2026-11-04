"""Offline upgrade/downgrade data preservation and actual headless probes."""

import contextlib
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from floorterminal import __version__
from floorterminal.app import FloorTerminalApp
from floorterminal.core import config
from floorterminal.storage.state import INITIAL_STATE, StateStore
from floorterminal.update import compatibility as compat
from floorterminal.update import installer, journal, media, trust
from floorterminal.update.layout import InstallLayout

from .update_fixtures import build_installation, make_key, write_update_drive

ROOT = Path(__file__).resolve().parents[2]


class RuntimeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.layout = InstallLayout(build_installation(self.work / "app", "1.2.0"))
        installer.initialise(self.layout, "1.2.0")
        self.root = self.layout.root
        self.config_file = self.root / "config.json"
        self.connector = json.loads((ROOT / "connector.example.json").read_text())
        self.connector["credentials"]["access_token"] = "offline-fixture-not-a-real-key"
        self.save("connector.json", self.connector)
        guard = mock.patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network forbidden")
        )
        guard.start()
        self.addCleanup(guard.stop)

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_current_schema_and_all_connectors_are_preserved_byte_for_byte(self):
        self.save("spare.connector.json", self.connector)
        (self.root / ".active_connector").write_text("spare.connector.json\n")
        before = compat.runtime_files(self.root)
        report = compat.inspect_runtime(self.root)
        checkpoint = compat.checkpoint(self.layout, "1.2.0")
        self.assertEqual(report["connector_count"], 2)
        self.assertEqual(before, compat.runtime_files(self.root))
        for name, payload in before.items():
            self.assertEqual((checkpoint / name).read_bytes(), payload)
            self.assertEqual(stat.S_IMODE((checkpoint / name).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(checkpoint.stat().st_mode), 0o700)
        metadata = (checkpoint / "checkpoint.json").read_text()
        self.assertNotIn("offline-fixture-not-a-real-key", metadata)

    def test_inspection_does_not_even_change_file_permissions(self):
        state = self.root / "response_state.json"
        state.chmod(0o640)
        compat.inspect_runtime(self.root)
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o640)

    def test_unknown_settings_survive_save_and_alias_migrates_only_in_memory(self):
        raw = {"engineering_member_max_pages": 2, "future_extension": {"keep": [1, 2]}}
        self.save("config.json", raw)
        with mock.patch.object(config, "CONFIG_FILE", self.config_file):
            loaded = config.load_config()
            self.assertEqual(loaded["directory_max_pages"], 2)
            self.assertEqual(json.loads(self.config_file.read_text()), raw)
            loaded["line_name"] = "Changed safely"
            config.write_config(loaded)
        self.assertEqual(
            json.loads(self.config_file.read_text())["future_extension"],
            {"keep": [1, 2]},
        )

    def test_legacy_save_then_return_restores_extensions_not_old_user_values(self):
        self.save(
            "config.json", {"line_name": "Before", "future_extension": {"keep": True}}
        )
        compat.checkpoint(self.layout, "1.1.0")
        # The old Settings writer saves only fields it understands.
        self.save("config.json", {"line_name": "Edited while downgraded"})
        self.connector["credentials"]["access_token"] = "rotated-offline-fixture"
        self.save("connector.json", self.connector)
        with mock.patch.object(config, "CONFIG_FILE", self.config_file):
            loaded = config.load_config()
        self.assertEqual(loaded["line_name"], "Edited while downgraded")
        self.assertEqual(loaded["future_extension"], {"keep": True})
        self.assertFalse((self.layout.update_dir / compat.CARRY_FILE).exists())
        self.assertEqual(
            json.loads((self.root / "connector.json").read_text()), self.connector
        )
        self.assertIn("future_extension", json.loads(self.config_file.read_text()))

    def test_carry_never_overwrites_an_extension_edited_since_checkpoint(self):
        self.save("config.json", {"future_extension": "old"})
        compat.checkpoint(self.layout, "1.1.0")
        self.save("config.json", {"future_extension": "new"})
        with mock.patch.object(config, "CONFIG_FILE", self.config_file):
            self.assertEqual(config.load_config()["future_extension"], "new")

    def test_failed_carry_save_keeps_both_original_and_recovery(self):
        self.save("config.json", {"future_extension": "kept"})
        compat.checkpoint(self.layout, "1.1.0")
        self.save("config.json", {"line_name": "New label"})
        before = self.config_file.read_bytes()
        with (
            mock.patch.object(config, "CONFIG_FILE", self.config_file),
            mock.patch.object(config, "write_json", side_effect=OSError("full")),
            self.assertRaises(config.ConfigurationError),
        ):
            config.load_config()
        self.assertEqual(self.config_file.read_bytes(), before)
        self.assertTrue((self.layout.update_dir / compat.CARRY_FILE).is_file())

    def test_downgrade_rejects_groups_local_reporting_and_changed_request_budget(self):
        groups = [
            {
                "id": "assembly",
                "name": "Assembly",
                "stations": list(config.DEFAULT_ZONES),
                "stop_scope": "group",
            }
        ]
        for values in (
            {"reporting_mode": "local"},
            {"api_requests_per_minute": 24},
            {"station_groups": groups},
        ):
            with self.subTest(values=values):
                self.save("config.json", values)
                with self.assertRaises(compat.CompatibilityError):
                    compat.inspect_runtime(self.root, "1.1.0")

    def test_future_configuration_schema_is_preserved_and_refused(self):
        raw = {"schema_version": 2, "line_name": "Future format"}
        self.save("config.json", raw)
        with (
            mock.patch.object(config, "CONFIG_FILE", self.config_file),
            self.assertRaises(config.ConfigurationError),
        ):
            config.load_config()
        self.assertEqual(json.loads(self.config_file.read_text()), raw)

    def test_oversized_extension_merge_is_refused_without_replacing_config(self):
        self.save("config.json", {"old_extension": "a" * (3 * 1024 * 1024)})
        compat.checkpoint(self.layout, "1.1.0")
        self.save("config.json", {"new_extension": "b" * (2 * 1024 * 1024)})
        before = self.config_file.read_bytes()
        with (
            mock.patch.object(config, "CONFIG_FILE", self.config_file),
            self.assertRaises(config.ConfigurationError),
        ):
            config.load_config()
        self.assertEqual(self.config_file.read_bytes(), before)
        self.assertTrue((self.layout.update_dir / compat.CARRY_FILE).exists())

    def test_boolean_schema_and_known_values_in_carry_are_refused(self):
        carry = self.layout.update_dir / compat.CARRY_FILE
        for payload in (
            {"schema_version": True, "values": {}, "checkpoint": "change-test"},
            {
                "schema_version": 1,
                "values": {"line_name": "obsolete"},
                "checkpoint": "change-test",
            },
        ):
            carry.write_text(json.dumps(payload))
            with self.assertRaises(compat.CompatibilityError):
                compat.restore_config_extensions(self.root, {"line_name": "current"})

    def test_external_version_slot_is_not_a_managed_installation(self):
        external = self.work / "external" / "versions" / "1.2.0"
        external.mkdir(parents=True)
        (external / trust.EXECUTABLE_NAME).write_bytes(b"fixture")
        self.layout.active_link.unlink()
        self.layout.active_link.symlink_to(external / trust.EXECUTABLE_NAME)
        self.assertFalse(self.layout.managed)

    def test_new_delivery_policy_cannot_be_silently_downgraded(self):
        operation = self.connector["operations"]["response_record.create"]
        operation.pop("idempotency")
        operation["delivery"] = {"ambiguous_result": "hold"}
        self.save("connector.json", self.connector)
        compat.inspect_runtime(self.root)
        with self.assertRaisesRegex(compat.CompatibilityError, "delivery policy"):
            compat.inspect_runtime(self.root, "1.1.0")

    def test_future_state_is_not_erased_to_allow_rollback(self):
        self.save("response_state.json", {"status": "RUNNING", "roster_cache": {}})
        before = (self.root / "response_state.json").read_bytes()
        with self.assertRaisesRegex(compat.CompatibilityError, "newer fields"):
            compat.inspect_runtime(self.root, "1.1.0")
        self.assertEqual((self.root / "response_state.json").read_bytes(), before)

    def test_old_reader_cannot_silently_ignore_new_incident_mappings(self):
        original = deepcopy(self.connector["workflow"]["fields"])
        for fields in (
            {"team_assignee_id": "team_id", "user_assignee_id": "person_id"},
            {"failure_details": "station_details"},
            {"location_ids": "affected_locations"},
        ):
            with self.subTest(fields=fields):
                self.connector["workflow"]["fields"] = {**original, **fields}
                path = self.save("connector.json", self.connector)
                before = path.read_bytes()
                compat.inspect_runtime(self.root)
                with self.assertRaisesRegex(compat.CompatibilityError, "mappings"):
                    compat.inspect_runtime(self.root, "1.1.0")
                self.assertEqual(path.read_bytes(), before)

    def test_live_response_and_pending_deliveries_block_changes(self):
        state = StateStore(self.root / "response_state.json")
        state.data["status"] = "DOWN"
        state.data["started_at"] = 1000
        state.save()
        with self.assertRaisesRegex(compat.CompatibilityError, "active responses"):
            compat.checkpoint(self.layout, "1.2.0")
        state.data = deepcopy(INITIAL_STATE)
        state.data["asset_status_sync_pending"] = True
        state.save()
        with self.assertRaisesRegex(compat.CompatibilityError, "synchronization"):
            compat.checkpoint(self.layout, "1.2.0")

    def test_missing_explicit_selection_does_not_fall_back_to_another_connector(self):
        (self.root / ".active_connector").write_text("absent.connector.json")
        with self.assertRaisesRegex(
            compat.CompatibilityError, "selected connector is missing"
        ):
            compat.inspect_runtime(self.root)

    def test_bad_json_and_future_schema_remain_untouched(self):
        for data in (b'{"secret":"do-not-echo",', b'{"schema_version":99}'):
            (self.root / "connector.json").write_bytes(data)
            with self.assertRaises(compat.CompatibilityError) as caught:
                compat.inspect_runtime(self.root)
            self.assertNotIn("do-not-echo", str(caught.exception))
            self.assertEqual((self.root / "connector.json").read_bytes(), data)

    def test_linked_connector_checkpoint_directory_and_excess_inventory_are_refused(
        self,
    ):
        (self.root / "connector.json").unlink()
        external = self.save("outside.json", self.connector)
        (self.root / "connector.json").symlink_to(external)
        with self.assertRaises(compat.CompatibilityError):
            compat.inspect_runtime(self.root)
        (self.root / "connector.json").unlink()
        self.save("connector.json", self.connector)
        self.layout.update_dir.joinpath("data-checkpoints").symlink_to(
            self.work, target_is_directory=True
        )
        with self.assertRaisesRegex(compat.CompatibilityError, "directories"):
            compat.checkpoint(self.layout, "1.2.0")
        for index in range(33):
            self.save(f"extra-{index}.connector.json", self.connector)
        with self.assertRaisesRegex(compat.CompatibilityError, "Too many"):
            compat.inspect_runtime(self.root)

    def test_low_space_refuses_without_touching_runtime_or_activation(self):
        before = compat.runtime_files(self.root)
        with (
            mock.patch.object(
                shutil, "disk_usage", return_value=SimpleNamespace(free=100)
            ),
            self.assertRaisesRegex(compat.CompatibilityError, "free storage"),
        ):
            compat.checkpoint(self.layout, "1.2.0")
        self.assertEqual(compat.runtime_files(self.root), before)
        self.assertEqual(self.layout.active_version(), "1.2.0")

    def test_checkpoint_retention_is_bounded_even_before_confirmation(self):
        for _ in range(6):
            compat.checkpoint(self.layout, "1.2.0")
        self.assertEqual(
            len(list((self.layout.update_dir / "data-checkpoints").iterdir())), 3
        )

    def test_changed_live_file_during_probe_refuses_activation(self):
        with (
            mock.patch.object(
                compat,
                "probe_target",
                side_effect=lambda *args: self.save(
                    "config.json", {"line_name": "Changed externally"}
                ),
            ),
            self.assertRaisesRegex(compat.CompatibilityError, "changed during"),
        ):
            compat.checkpoint(self.layout, "1.3.0")
        self.assertEqual(self.layout.active_version(), "1.2.0")
        self.assertEqual(
            list((self.layout.update_dir / "data-checkpoints").iterdir()), []
        )

    def executable(self, body):
        path = self.work / "probe"
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o700)
        return path

    def test_real_headless_candidate_probe_and_source_cli_are_read_only(self):
        executable = self.executable(
            f"import sys, os\nsys.path.insert(0, {str(ROOT / 'src')!r})\n"
            "from floorterminal.update.compatibility import cli\n"
            "raise SystemExit(cli(os.environ['FLOORTERMINAL_HOME']))\n"
        )
        before = compat.runtime_files(self.root)
        compat.probe_target(executable, self.root, __version__)
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), compat.CHECK_ARGUMENT],
            env={
                **os.environ,
                "FLOORTERMINAL_HOME": str(self.root),
                "FLOORTERMINAL_DISABLE_NETWORK": "1",
            },
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["compatible"])
        self.assertNotIn("offline-fixture", result.stdout)
        self.assertEqual(compat.runtime_files(self.root), before)

    def test_probe_rejects_wrong_version_failure_timeout_and_large_output(self):
        for body in (
            "raise SystemExit(78)\n",
            "print('{}')\n",
            "print('x' * 70000)\n",
            "import time; time.sleep(3)\n",
        ):
            with (
                self.subTest(body=body),
                mock.patch.object(compat, "CHECK_TIMEOUT", 0.2),
                self.assertRaises(compat.CompatibilityError),
            ):
                compat.probe_target(self.executable(body), self.root, "1.3.0")

    def test_probe_refuses_candidate_that_modifies_the_checkpoint(self):
        body = (
            f"import sys, os\nsys.path.insert(0, {str(ROOT / 'src')!r})\n"
            "from pathlib import Path\nfrom floorterminal.update.compatibility import cli\n"
            "root=Path(os.environ['FLOORTERMINAL_HOME'])\n"
            "(root/'config.json').write_text('{}')\nraise SystemExit(cli(root))\n"
        )
        with self.assertRaises(compat.CompatibilityError):
            compat.probe_target(self.executable(body), self.root, __version__)

    def test_cli_rejection_is_generic_and_secret_free(self):
        (self.root / "connector.json").write_text('{"password":"never-print-me",')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(compat.cli(self.root), 78)
        self.assertFalse(json.loads(out.getvalue())["compatible"])
        self.assertNotIn("never-print-me", out.getvalue())

    def test_data_refusal_keeps_signed_package_staged_and_running_version(self):
        seed, key, anchor = make_key()
        mount = self.work / "usb"
        with mock.patch.object(trust, "TRUSTED_KEYS", (anchor,)):
            write_update_drive(mount, seed, key, "1.3.0")
            media.stage(self.layout, media.read_package(mount), expect_executable=True)
            with self.assertRaises(installer.ActivationError):
                installer.activate(self.layout, "1.3.0")
        self.assertEqual(self.layout.active_version(), "1.2.0")
        self.assertTrue(
            (self.layout.staging_dir / "1.3.0" / trust.EXECUTABLE_NAME).is_file()
        )
        self.assertEqual(
            journal.read_journal(self.layout.journal).state, journal.STATE_CONFIRMED
        )

    def test_probation_with_invalid_connector_requests_supervised_recovery(self):
        record = journal.read_journal(self.layout.journal)
        record.state = journal.STATE_PROBATION
        journal.write_boot_state(self.layout.boot_state, record)
        (self.root / "connector.json").write_text("{}")
        with (
            mock.patch.dict(os.environ, {"FLOORTERMINAL_SUPERVISED": "1"}),
            self.assertRaises(compat.CompatibilityError),
        ):
            compat.probation_startup_check(self.root)

    def test_legacy_update_with_active_or_pending_work_recovers_without_mutation(self):
        record = journal.read_journal(self.layout.journal)
        record.state = journal.STATE_PROBATION
        journal.write_boot_state(self.layout.boot_state, record)
        for fields in (
            {"status": "DOWN"},
            {"pending_response_status": {"record_id": 17, "status": "DONE"}},
        ):
            with self.subTest(fields=fields):
                self.save("response_state.json", {**INITIAL_STATE, **fields})
                StateStore(self.root / "response_state.json", read_only=True)
                before = compat.runtime_files(self.root)
                with (
                    mock.patch.dict(os.environ, {"FLOORTERMINAL_SUPERVISED": "1"}),
                    self.assertRaises(compat.CompatibilityError),
                ):
                    compat.probation_startup_check(self.root)
                self.assertEqual(compat.runtime_files(self.root), before)

    def test_idle_probation_startup_is_read_only(self):
        record = journal.read_journal(self.layout.journal)
        record.state = journal.STATE_PROBATION
        journal.write_boot_state(self.layout.boot_state, record)
        before = compat.runtime_files(self.root)
        with mock.patch.dict(os.environ, {"FLOORTERMINAL_SUPERVISED": "1"}):
            self.assertTrue(compat.probation_startup_check(self.root))
        self.assertEqual(compat.runtime_files(self.root), before)


class VersionChangeOrderingTests(unittest.TestCase):
    def app(self):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.state = deepcopy(INITIAL_STATE)
        app.busy = False
        app.logger = SimpleNamespace(log=lambda *a, **k: None)
        app.notify = mock.Mock()
        app.finish_version_change = mock.Mock()
        return app

    def test_save_precedes_switch_and_failed_save_never_switches(self):
        for fail in (False, True):
            app = self.app()
            events = []

            def save(events=events, fail=fail):
                events.append("save")
                if fail:
                    raise OSError("storage failed")

            def change(events=events):
                events.append("switch")
                return SimpleNamespace(from_version="1.1.0", to_version="1.2.0")

            def perform(_message, function, done, **options):
                self.assertFalse(options["transactional"])
                try:
                    result = function()
                except OSError:
                    options["on_error"](None)
                else:
                    done(result)
                return True

            app.save_state, app.perform = save, perform
            app.run_version_change(change, "Test administrator")
            self.assertEqual(events, ["save"] if fail else ["save", "switch"])
            self.assertEqual(app.finish_version_change.call_count, 0 if fail else 1)
            if fail:
                self.assertFalse(app._version_change_pending)

    def test_background_sender_and_queues_block_version_change(self):
        app = self.app()
        app.delivery = SimpleNamespace(active="in-flight")
        self.assertIn("background", app.version_change_blocker())
        app.delivery.active = None
        app.state["pending_messages"] = ["held"]
        self.assertIn("saved updates", app.version_change_blocker())

    def test_trial_reporting_operations_are_refused_without_starting_worker(self):
        app = self.app()
        app.update_service = SimpleNamespace(
            status=lambda: SimpleNamespace(state="probation")
        )
        action = mock.Mock()
        self.assertFalse(app.perform("Report", action))
        action.assert_not_called()
