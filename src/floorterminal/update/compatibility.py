"""Read-only runtime-data checks and private version-change checkpoints.

No URL, credential, remote enum or retry guarantee is invented by a migration.
Schema 1 remains the on-disk interchange format. New readers supply defaults in
memory; old readers are permitted only when their known limitations are satisfied.
Future executables must answer the bounded, network-free compatibility protocol.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .. import __version__
from ..core.config import prepare_config, write_private
from ..core.json_file import decode_strict_json, read_bounded_bytes, read_bounded_json
from ..integration.definition import IntegrationDefinition
from ..integration.discovery import MAX_CONNECTORS, PATTERNS
from ..storage.state import StateStore
from . import version

CHECK_ARGUMENT = "--check-update-data"
PROTOCOL = 1
MAX_BYTES = 104 * 1024 * 1024
RESERVE_BYTES = 256 * 1024 * 1024
CHECK_TIMEOUT = 30
CARRY_FILE = "config-carry.json"
V12_STATE = {
    "incident_id",
    "incident_scope",
    "parked_incidents",
    "history_pending",
    "history_links",
    "operator_response",
    "delivery_outbox",
    "delivery_pause_until",
    "roster_cache",
    "roster_refresh",
}
V11_STATE = {
    "work_label",
    "work_type",
    "completion_confirmed_at",
    "pending_record_updates",
    "pending_messages",
}
# Exact keys the published 1.0/1.1 Settings writer does not understand. Unknown
# extensions are carried too, but never interpreted or silently substituted.
LEGACY_CONFIG_KEYS = {
    "line_name",
    "location_id",
    "asset_id",
    "zones",
    "engineering_team_name",
    "engineering_chat_name",
    "quality_chat_name",
    "production_chat_name",
    "common_activity_chat_name",
    "escalation_chat_name",
    "station_failure_types",
    "response_record_priority",
    "response_record_type",
    "planned_work_priority",
    "asset_status_tracking",
    "fullscreen_on_linux",
    "animation_interval_ms",
    "sound_enabled",
    "sound_volume",
    "sound_cooldown_ms",
    "software_update_check_enabled",
    "directory_max_pages",
    "escalation_minutes",
    "micro_stop_threshold_minutes",
    "ui_language",
    "ui_color_preset",
    "log_directory",
    "log_level",
    "log_retention_days",
    "log_storage_reserve_mb",
    "log_daily_growth_floor_mb",
    "downtime_title_template",
    "downtime_description_template",
    "help_message_template",
    "planned_work_title_template",
    "planned_work_description_template",
    "ui_colors",
}


class CompatibilityError(ValueError):
    """The running version must be retained; no deployment data may be guessed."""


def runtime_files(root):
    """Read an exact, bounded set; never follow connector aliases or truncate it."""
    root = Path(root)
    names = {"config.json", "response_state.json", ".active_connector"}
    connectors = {path.name for pattern in PATTERNS for path in root.glob(pattern)}
    if len(connectors) > MAX_CONNECTORS:
        raise CompatibilityError(
            "Too many connector files; review the connector inventory first"
        )
    names.update(connectors)
    result, total = {}, 0
    for name in sorted(names):
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        limit = (
            32 * 1024 * 1024
            if name == "response_state.json"
            else 4 * 1024 * 1024
            if name == "config.json"
            else 4096
            if name == ".active_connector"
            else 2 * 1024 * 1024
        )
        try:
            payload = read_bounded_bytes(path, max_bytes=limit)
        except (OSError, ValueError) as exc:
            raise CompatibilityError(
                "A runtime file is unreadable, linked or outside its safety limit"
            ) from exc
        total += len(payload)
        if total > MAX_BYTES:
            raise CompatibilityError(
                "Runtime data exceeds the update checkpoint safety limit"
            )
        result[name] = payload
    return result


def fingerprint(files):
    digest = hashlib.sha256()
    for name, payload in sorted(files.items()):
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def _sync_directory(path):
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _legacy_connector(data):
    """Refuse semantics the published legacy readers cannot preserve."""
    workflow = data["workflow"]
    mappings = workflow.get("operations", {})
    messages = {"send_conversation_message", "send_user_message"} & set(mappings)
    if messages and len(messages) != 2:
        raise CompatibilityError(
            "The older version needs both messaging routes; keep this version for partial messaging"
        )
    for raw in data["operations"].values():
        if raw.get("delivery") or raw.get("idempotency", {}).get("location") == "path":
            raise CompatibilityError(
                "The older version cannot preserve this connector's safe delivery policy"
            )
        if raw.get("directory"):
            raise CompatibilityError(
                "The older version cannot preserve per-operation directory limits"
            )
    fields = workflow.get("fields", {})
    if {
        "team_assignee_id",
        "user_assignee_id",
        "failure_details",
        "location_ids",
    } & fields.keys():
        raise CompatibilityError(
            "The older version cannot preserve the configured assignment or incident-detail mappings"
        )
    if any("." in str(field) for field in fields.values()):
        raise CompatibilityError(
            "The older version cannot preserve nested response field mappings"
        )


def inspect_runtime(root, target=__version__):
    """Check all connector files and saved state, without modifying any bytes."""
    root = Path(root)
    try:
        files = runtime_files(root)
        raw_config = decode_strict_json(files.get("config.json", b"{}"))
        config = prepare_config(raw_config)
        StateStore(root / "response_state.json", read_only=True)
        definitions = {}
        for name, payload in files.items():
            if name not in {"config.json", "response_state.json", ".active_connector"}:
                definitions[name] = IntegrationDefinition.from_document(
                    decode_strict_json(payload), name
                )
        selection = files.get(".active_connector", b"").decode("utf-8").strip()
        if selection and selection not in definitions:
            raise CompatibilityError(
                "The selected connector is missing; restore it or choose another in Settings"
            )
    except CompatibilityError:
        raise
    except (ValueError, OSError, TypeError, UnicodeError) as exc:
        # Validation diagnostics can contain deployment-owned values. Keep the
        # update log/media mirror free of those values and of all credentials.
        raise CompatibilityError(
            "Runtime data did not pass local validation; review Settings and the connector file before changing versions"
        ) from exc
    parsed = version.parse(target)
    if parsed < version.parse("1.2.0"):
        if parsed not in (version.parse("1.0.0"), version.parse("1.1.0")):
            raise CompatibilityError(
                "This older version has no reviewed runtime-data compatibility contract"
            )
        if config.get("station_groups") or config.get("reporting_mode") == "local":
            raise CompatibilityError(
                "The older version cannot operate independent groups or local-only reporting; keep this version"
            )
        if any(
            not 1 <= len(values) <= 4
            for values in config["station_failure_types"].values()
        ):
            raise CompatibilityError(
                "The older version requires one to four custom failure reasons per station; keep this version"
            )
        if config.get("api_requests_per_minute") not in (None, 10):
            raise CompatibilityError(
                "The older version cannot preserve this configured request budget"
            )
        if any(
            str(config.get(key, "")).startswith(("conversation:", "user:"))
            for key in (
                "engineering_chat_name",
                "quality_chat_name",
                "production_chat_name",
                "common_activity_chat_name",
                "escalation_chat_name",
            )
        ):
            raise CompatibilityError(
                "The older version cannot preserve qualified chat recipients"
            )
        unsupported = V12_STATE | (
            V11_STATE if parsed < version.parse("1.1.0") else set()
        )
        saved = decode_strict_json(files.get("response_state.json", b"{}"))
        # Older readers reject even empty unknown fields. Do not erase history,
        # caches or queued work just to make a rollback appear successful.
        if unsupported & saved.keys():
            raise CompatibilityError(
                "Saved workflow data uses newer fields; keep this version until a reviewed backward migration is available"
            )
        for definition in definitions.values():
            _legacy_connector(definition.data)
    return {
        "protocol": PROTOCOL,
        "version": str(target),
        "compatible": True,
        "fingerprint": fingerprint(files),
        "connector_count": len(definitions),
    }


def require_quiet_state(root):
    """A version change is a maintenance action, never a live-incident shortcut."""
    try:
        state = StateStore(Path(root) / "response_state.json", read_only=True).data
    except (ValueError, OSError) as exc:
        raise CompatibilityError(
            "Saved workflow state must be repaired before changing versions"
        ) from exc
    if state.get("status") != "RUNNING" or state.get("parked_incidents"):
        raise CompatibilityError(
            "Finish all active responses and resume production before changing versions"
        )
    pending = (
        "delivery_outbox",
        "pending_response_record",
        "pending_planned_work",
        "pending_response_status",
        "pending_participant_assignment",
        "pending_record_updates",
        "pending_messages",
        "asset_status_sync_pending",
        "history_pending",
        "history_links",
    )
    if any(state.get(key) for key in pending):
        raise CompatibilityError(
            "Finish synchronization and resolve saved updates before changing versions"
        )


def probe_target(executable, root, target):
    """Ask only an already authenticated, locally installed executable to check.

    The input is a private detached checkpoint, never the live deployment. Output
    and elapsed time are bounded; errors never echo a child's diagnostics/secrets.
    """
    environment = {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ
    }
    environment.update(
        FLOORTERMINAL_HOME=str(root), FLOORTERMINAL_DISABLE_NETWORK="1", HOME=str(root)
    )
    expected = fingerprint(runtime_files(root))
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                [str(executable), CHECK_ARGUMENT],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise CompatibilityError(
                "The selected version could not run its data-compatibility check on this device"
            ) from exc
        try:
            deadline = time.monotonic() + CHECK_TIMEOUT
            while process.poll() is None:
                if (
                    time.monotonic() >= deadline
                    or os.fstat(output.fileno()).st_size > 65536
                ):
                    raise CompatibilityError(
                        "The selected version did not complete its data-compatibility check"
                    )
                time.sleep(0.025)
            output.seek(0)
            payload = output.read(65537)
            if process.returncode != 0 or len(payload) > 65536:
                raise CompatibilityError(
                    "The selected version refused these runtime files; the running version is unchanged"
                )
            try:
                result = decode_strict_json(payload)
                valid = (
                    isinstance(result, dict)
                    and type(result.get("protocol")) is int
                    and result["protocol"] == PROTOCOL
                    and result.get("version") == target
                    and result.get("compatible") is True
                    and result.get("fingerprint") == expected
                    and fingerprint(runtime_files(root)) == expected
                )
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise CompatibilityError(
                    "The selected version returned an unsupported data-compatibility result"
                )
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def checkpoint(layout, target, *, executable=None):
    """Validate and preserve exact bytes before changing any activation intent."""
    source = layout.active_version()
    require_quiet_state(layout.root)
    files = runtime_files(layout.root)
    inspect_runtime(layout.root, min(version.parse(target), version.parse(__version__)))
    parent = layout.update_dir / "data-checkpoints"
    if layout.update_dir.is_symlink() or parent.is_symlink():
        raise CompatibilityError("Update checkpoint directories must not be linked")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent.chmod(0o700)
    if shutil.disk_usage(parent).free < sum(map(len, files.values())) + RESERVE_BYTES:
        raise CompatibilityError(
            "Not enough free storage for a private update checkpoint"
        )
    prune_checkpoints(layout, keep=2)
    path = Path(tempfile.mkdtemp(prefix="change-", dir=parent))
    try:
        for name, payload in files.items():
            write_private(path / name, payload)
        if target != __version__ and version.parse(target) >= version.parse("1.2.0"):
            probe_target(executable or layout.slot_executable(target), path, target)
        metadata = {
            "schema_version": 1,
            "from_version": source,
            "to_version": target,
            "created_at": time.time(),
            "fingerprint": fingerprint(files),
            "files": {
                name: hashlib.sha256(payload).hexdigest()
                for name, payload in files.items()
            },
        }
        write_private(
            path / "checkpoint.json", json.dumps(metadata, sort_keys=True).encode()
        )
        _sync_directory(path)
        _sync_directory(parent)
        if fingerprint(runtime_files(layout.root)) != metadata["fingerprint"]:
            raise CompatibilityError(
                "Runtime files changed during verification; retry the version change"
            )
        if version.parse(target) < version.parse("1.2.0"):
            raw = decode_strict_json(files.get("config.json", b"{}"))
            carried = {
                key: value
                for key, value in raw.items()
                if key not in LEGACY_CONFIG_KEYS
            }
            if carried:
                encoded = json.dumps(
                    {"schema_version": 1, "values": carried, "checkpoint": path.name},
                    allow_nan=False,
                ).encode()
                if len(encoded) > 4 * 1024 * 1024:
                    raise CompatibilityError(
                        "Configuration extensions exceed the recovery record capacity"
                    )
                write_private(
                    layout.update_dir / CARRY_FILE,
                    encoded,
                )
                _sync_directory(layout.update_dir)
        return path
    except BaseException:
        shutil.rmtree(path)
        raise


def assert_unchanged(layout, checkpoint_path):
    data = read_bounded_json(checkpoint_path / "checkpoint.json", max_bytes=65536)
    if fingerprint(runtime_files(layout.root)) != data.get("fingerprint"):
        raise CompatibilityError(
            "Runtime files changed before activation; retry the version change"
        )


def prune_checkpoints(layout, keep=3):
    """Bound private backups after healthy confirmation; never prune live files."""
    parent = layout.update_dir / "data-checkpoints"
    if not parent.is_dir() or parent.is_symlink():
        return
    paths = sorted(
        (p for p in parent.glob("change-*") if p.is_dir() and not p.is_symlink()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in paths[max(1, keep) :]:
        shutil.rmtree(path)


def restore_config_extensions(root, loaded):
    """Recover only keys a legacy Settings writer cannot retain; never overwrite.

    The caller persists the validated merged view, then retires the carry file.
    Connector credentials, active incidents, passwords and sent jobs are NEVER
    restored from an old checkpoint.
    """
    path = Path(root) / "update" / CARRY_FILE
    if path.parent.is_symlink():
        raise CompatibilityError(
            "Configuration compatibility directory must not be linked"
        )
    if not path.exists() and not path.is_symlink():
        return loaded, None
    data = read_bounded_json(path, max_bytes=4 * 1024 * 1024)
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or set(data) != {"schema_version", "values", "checkpoint"}
        or not isinstance(data.get("values"), dict)
    ):
        raise CompatibilityError("Configuration compatibility record is invalid")
    values = data["values"]
    if set(values) & LEGACY_CONFIG_KEYS:
        raise CompatibilityError(
            "Configuration compatibility record contains non-extension settings"
        )
    merged = {**values, **loaded}
    if (
        len(json.dumps(merged, indent=2, ensure_ascii=False, allow_nan=False).encode())
        + 1
        > 4 * 1024 * 1024
    ):
        raise CompatibilityError("Merged configuration exceeds the recovery capacity")
    return merged, path


def cli(root):
    try:
        result = inspect_runtime(root)
    except (CompatibilityError, OSError, ValueError):
        result = {"protocol": PROTOCOL, "version": __version__, "compatible": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["compatible"] else 78


def probation_startup_check(root):
    """Let the supervised watchdog recover instead of hanging on an error page."""
    from .journal import read_boot_state
    from .layout import InstallLayout

    layout = InstallLayout(Path(root))
    boot = read_boot_state(layout.boot_state)
    if (
        os.environ.get("FLOORTERMINAL_SUPERVISED") == "1"
        and boot.get("STATUS") == "probation"
        and layout.active_version() == __version__
    ):
        # Published older updaters did not require an idle, drained workflow.
        # Refuse before app construction can migrate an active legacy incident
        # or start delivery. Recovery must retain the previous reader's bytes.
        require_quiet_state(root)
        inspect_runtime(root)
        return True
    return False
