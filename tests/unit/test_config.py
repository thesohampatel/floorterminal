import copy
import json
import tempfile
import unittest
from pathlib import Path

from floorterminal.core.config import (
    DEFAULT_CONFIG,
    DEFAULT_ZONES,
    ConfigurationError,
    validate_config,
    write_json,
)


class ConfigurationTests(unittest.TestCase):
    def test_production_configuration_loads(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        validate_config(config)
        self.assertEqual(config["zones"], DEFAULT_ZONES)
        self.assertEqual(set(config["zones"]), set(config["station_failure_types"]))
        self.assertFalse(any(key.endswith("provider") for key in config))
        self.assertNotIn("settings_password_sha256", config)
        self.assertNotIn("settings_password_hash", config)
        self.assertTrue(config["sound_enabled"])
        self.assertEqual(config["sound_volume"], 70)

    def test_asset_tracking_requires_asset_id(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config.update(asset_status_tracking=True, asset_id="")
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_sound_configuration_is_strictly_validated(self):
        for key, value in (
            ("sound_enabled", "yes"),
            ("sound_volume", 101),
            ("sound_cooldown_ms", -1),
        ):
            config = copy.deepcopy(DEFAULT_CONFIG)
            config[key] = value
            with self.subTest(key=key), self.assertRaises(ConfigurationError):
                validate_config(config)

    def test_atomic_json_rewrite_preserves_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            path.write_text("{}")
            path.chmod(0o644)
            write_json(path, {"internal": "value"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {"internal": "value"})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
