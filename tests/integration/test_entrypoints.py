import importlib
import unittest


class EntrypointTests(unittest.TestCase):
    def test_production_package_imports(self):
        app = importlib.import_module("floorterminal.app")
        self.assertTrue(callable(app.main))

    def test_package_version_matches_release(self):
        package = importlib.import_module("floorterminal")
        self.assertEqual(package.__version__, "1.0.0")

    def test_gui_layers_import_without_creating_window(self):
        for name in (
            "floorterminal.ui.view",
            "floorterminal.ui.settings",
            "floorterminal.ui.responsive",
        ):
            self.assertIsNotNone(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
