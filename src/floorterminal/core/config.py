"""Configuration paths, defaults, loading, and atomic persistence."""

from __future__ import annotations

import json
import os
import re
import string
import tempfile
from pathlib import Path

from ..i18n import available_languages
from .paths import RUNTIME_ROOT

PROJECT_DIR = RUNTIME_ROOT
CONFIG_FILE = PROJECT_DIR / "config.json"
STATE_FILE = PROJECT_DIR / "response_state.json"
DEFAULT_ZONES = [
    "Station 1",
    "Station 2",
    "Station 3",
    "Station 4",
    "Station 5",
    "Station 6",
]
STATION_FAILURE_FALLBACK = [
    "Mechanical",
    "Electrical",
    "Material / Flow",
    "Sensor / Control",
]
COLORBLIND_SAFE_COLORS = {
    "background": "#F3F5F9",
    "card": "#FFFFFF",
    "text": "#14213D",
    "muted": "#64748B",
    "red": "#D55E00",
    "green": "#0072B2",
    "blue": "#56B4E9",
    "orange": "#E69F00",
    "purple": "#CC79A7",
    "border": "#D9E2EC",
}


class ConfigurationError(ValueError):
    """Raised when production configuration is unsafe or incomplete."""


DEFAULT_CONFIG = {
    "line_name": "Line 1",
    "location_id": "",
    "asset_id": "",
    "engineering_team_name": "",
    "engineering_chat_name": "",
    "quality_chat_name": "",
    "production_chat_name": "",
    "common_activity_chat_name": "",
    "escalation_chat_name": "",
    "station_failure_types": {
        zone: list(STATION_FAILURE_FALLBACK) for zone in DEFAULT_ZONES
    },
    "zones": list(DEFAULT_ZONES),
    "response_record_priority": "HIGH",
    "response_record_type": "REACTIVE",
    "planned_work_priority": "MEDIUM",
    "asset_status_tracking": False,
    "fullscreen_on_linux": True,
    "animation_interval_ms": 80,
    "sound_enabled": True,
    "sound_volume": 70,
    "sound_cooldown_ms": 750,
    "software_update_check_enabled": True,
    "directory_max_pages": 3,
    "escalation_minutes": 15,
    "micro_stop_threshold_minutes": 5,
    "ui_language": "en",
    "ui_color_preset": "standard",
    "log_directory": "logs",
    "log_retention_days": 183,
    "log_level": "INFO",
    "log_storage_reserve_mb": 512,
    "log_daily_growth_floor_mb": 2,
    "downtime_title_template": "UNPLANNED DOWNTIME • {line} • {zones} • {time}",
    "downtime_description_template": "Unplanned downtime reported from the {line} touchscreen at {timestamp}. Line response required.",
    "help_message_template": "🚨 {department} assistance requested at {line}. Stations: {zones}. Line-side support is needed; {condition}. Request sent from the line terminal at {timestamp}. Please respond in chat.",
    "planned_work_title_template": "PLANNED • {work_label} • {line} • {zones} • {time}",
    "planned_work_description_template": "Engineering took control of {line} for {work_label} at {timestamp}. Production is paused until Engineering releases the line.",
    "ui_colors": {
        "background": "#F3F5F9",
        "card": "#FFFFFF",
        "text": "#14213D",
        "muted": "#718096",
        "red": "#E84855",
        "green": "#16A36A",
        "blue": "#246BFD",
        "orange": "#F09A3E",
        "purple": "#7956D8",
        "border": "#E3E8F1",
    },
}

CONFIG_KEYS = (
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
)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default.copy()


def restrict_file(path: Path):
    """Best-effort repair for private runtime files created by older releases."""
    try:
        path.chmod(0o600)
    except OSError:
        pass


def write_private(path: Path, content: bytes, validator=None):
    """Atomically persist owner-only data through an unpredictable temp file."""
    descriptor = None
    tmp = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        tmp = Path(name)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if validator:
            validator(tmp)
        os.replace(tmp, path)
        restrict_file(path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        except OSError:
            pass


def write_json(path: Path, value):
    """Atomically persist private JSON with owner-only permissions."""
    encoded = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    write_private(path, encoded)


def load_config():
    if not CONFIG_FILE.exists():
        write_config(DEFAULT_CONFIG)
    restrict_file(CONFIG_FILE)
    try:
        loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"Cannot read {CONFIG_FILE.name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in {CONFIG_FILE.name} at line {exc.lineno}, column {exc.colno}."
        ) from exc
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"{CONFIG_FILE.name} must contain one JSON object.")
    # Pre-release compatibility for installations created before the setting was
    # accurately named. The old value is consumed once and never written again.
    if "directory_max_pages" not in loaded and "engineering_member_max_pages" in loaded:
        loaded["directory_max_pages"] = loaded.pop("engineering_member_max_pages")
    loaded_colors = loaded.get("ui_colors", {})
    if not isinstance(loaded_colors, dict):
        raise ConfigurationError("ui_colors must be an object.")
    result = {
        **DEFAULT_CONFIG,
        **loaded,
        "ui_colors": {**DEFAULT_CONFIG["ui_colors"], **loaded_colors},
    }
    validate_config(result)
    result["zones"] = [str(zone).strip() for zone in result["zones"]]
    result["station_failure_types"] = {
        zone: [str(value).strip() for value in result["station_failure_types"][zone]]
        for zone in result["zones"]
    }
    return result


def validate_station_failures(config):
    """Require one independent four-choice list for every configured station."""
    zones = config.get("zones")
    if not isinstance(zones, list) or not zones:
        raise ConfigurationError("'zones' must be a non-empty list of station names.")
    names = [str(zone).strip() for zone in zones]
    if any(not name for name in names):
        raise ConfigurationError("Every entry in 'zones' must have a station name.")
    folded = [name.casefold() for name in names]
    if len(folded) != len(set(folded)):
        raise ConfigurationError("Station names in 'zones' must be unique.")
    failures = config.get("station_failure_types")
    if not isinstance(failures, dict):
        raise ConfigurationError(
            "'station_failure_types' must be an object keyed by station name."
        )
    missing = [name for name in names if name not in failures]
    extra = [str(name) for name in failures if str(name) not in names]
    problems = []
    if missing:
        problems.append("missing failure lists: " + ", ".join(missing))
    if extra:
        problems.append("unknown station mappings: " + ", ".join(extra))
    for name in names:
        if name not in failures:
            continue
        values = failures[name]
        if not isinstance(values, list) or not 1 <= len(values) <= 4:
            problems.append(
                f"{name} must contain between one and four custom failure names"
            )
            continue
        labels = [str(value).strip() for value in values]
        if any(not label for label in labels):
            problems.append(f"{name} contains an empty failure name")
        if any(label.casefold() in ("other", "others") for label in labels):
            problems.append(
                f"{name} must not include Others; it is added automatically"
            )
        if len({label.casefold() for label in labels}) != len(labels):
            problems.append(f"{name} failure names must be unique")
    if problems:
        raise ConfigurationError(
            "Station failure configuration is invalid:\n• " + "\n• ".join(problems)
        )


def validate_config(config):
    """Validate every operator-editable production setting."""
    validate_station_failures(config)
    if not str(config.get("line_name", "")).strip():
        raise ConfigurationError("Line / machine name cannot be empty.")
    if str(config.get("response_record_priority", "")).upper() not in (
        "NONE",
        "LOW",
        "MEDIUM",
        "HIGH",
    ):
        raise ConfigurationError("response_record_priority is invalid.")
    if str(config.get("planned_work_priority", "")).upper() not in (
        "NONE",
        "LOW",
        "MEDIUM",
        "HIGH",
    ):
        raise ConfigurationError("planned_work_priority is invalid.")
    if str(config.get("response_record_type", "")).upper() not in (
        "REACTIVE",
        "PREVENTIVE",
        "OTHER",
    ):
        raise ConfigurationError("response_record_type is invalid.")
    if not isinstance(config.get("asset_status_tracking"), bool):
        raise ConfigurationError("asset_status_tracking must be true or false.")
    if (
        config.get("asset_status_tracking")
        and not str(config.get("asset_id", "")).strip()
    ):
        raise ConfigurationError(
            "Asset ID is required when asset status tracking is enabled."
        )
    ranges = {
        "animation_interval_ms": (30, 1000),
        "sound_volume": (0, 100),
        "sound_cooldown_ms": (0, 5000),
        "directory_max_pages": (1, 20),
        "log_retention_days": (1, 730),
        "log_storage_reserve_mb": (128, 102400),
        "log_daily_growth_floor_mb": (1, 1024),
        "micro_stop_threshold_minutes": (1, 1440),
    }
    for key, (minimum, maximum) in ranges.items():
        value = config.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not minimum <= value <= maximum
        ):
            raise ConfigurationError(
                f"{key.replace('_', ' ')} must be a whole number from {minimum} to {maximum}."
            )
    escalation = config.get("escalation_minutes")
    if (
        isinstance(escalation, bool)
        or not isinstance(escalation, int)
        or not 0 <= escalation <= 1440
    ):
        raise ConfigurationError(
            "escalation minutes must be a whole number from 0 to 1440"
        )
    if str(config.get("ui_language", "en")) not in available_languages():
        raise ConfigurationError(
            "ui_language is not installed; available: "
            + ", ".join(available_languages())
        )
    if config.get("ui_color_preset") not in {
        "standard",
        "colorblind_safe",
        "custom",
    }:
        raise ConfigurationError("ui_color_preset is invalid")
    if not isinstance(config.get("fullscreen_on_linux"), bool):
        raise ConfigurationError("fullscreen_on_linux must be true or false.")
    if not isinstance(config.get("sound_enabled"), bool):
        raise ConfigurationError("sound_enabled must be true or false.")
    if not isinstance(config.get("software_update_check_enabled"), bool):
        raise ConfigurationError("software_update_check_enabled must be true or false.")
    if str(config.get("log_level", "")).upper() not in (
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ):
        raise ConfigurationError("log_level is invalid.")
    if not str(config.get("log_directory", "")).strip():
        raise ConfigurationError("log_directory cannot be empty.")
    allowed = {
        "line",
        "zones",
        "timestamp",
        "time",
        "department",
        "condition",
        "work_label",
    }
    template_keys = (
        "downtime_title_template",
        "downtime_description_template",
        "help_message_template",
        "planned_work_title_template",
        "planned_work_description_template",
    )
    for key in template_keys:
        value = str(config.get(key, "")).strip()
        if not value:
            raise ConfigurationError(f"{key.replace('_', ' ')} cannot be empty.")
        try:
            fields = {name for _, name, _, _ in string.Formatter().parse(value) if name}
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid braces in {key.replace('_', ' ')}: {exc}"
            ) from exc
        unknown = fields - allowed
        if unknown:
            raise ConfigurationError(
                f"Unsupported placeholder in {key.replace('_', ' ')}: {', '.join(sorted(unknown))}"
            )
    colors = config.get("ui_colors")
    if not isinstance(colors, dict):
        raise ConfigurationError("ui_colors must be an object.")
    for key in DEFAULT_CONFIG["ui_colors"]:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(colors.get(key, ""))):
            raise ConfigurationError(f"Invalid UI color: {key}.")


def write_config(config):
    write_json(CONFIG_FILE, {key: config[key] for key in CONFIG_KEYS if key in config})
