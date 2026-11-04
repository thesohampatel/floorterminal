import importlib
import tomllib
import unittest
from pathlib import Path


class EntrypointTests(unittest.TestCase):
    def test_production_package_imports(self):
        app = importlib.import_module("floorterminal.app")
        self.assertTrue(callable(app.main))

    def test_package_version_matches_project_metadata(self):
        package = importlib.import_module("floorterminal")
        metadata = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
        self.assertEqual(package.__version__, metadata["project"]["version"])

    def test_gui_layers_import_without_creating_window(self):
        for name in (
            "floorterminal.ui.view",
            "floorterminal.ui.settings",
            "floorterminal.ui.responsive",
        ):
            self.assertIsNotNone(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
