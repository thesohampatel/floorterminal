import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class OpenSourceReadinessTests(unittest.TestCase):
    def test_project_uses_neutral_profile_contract(self):
        profile = json.loads((ROOT / "project_profile.example.json").read_text())
        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["product_name"], "FloorTerminal")
        self.assertEqual(profile["product_short_name"], "FloorTerminal")
        self.assertEqual(profile["maintainer_name"], "Soham Patel")
        self.assertEqual(profile["support_contact"], "sohampatel1782@gmail.com")
        self.assertEqual(
            profile["settings_password"],
            "admin@123",
        )

    def test_tracked_templates_contain_no_enabled_credentials(self):
        connector = json.loads((ROOT / "connector.example.json").read_text())
        self.assertFalse(connector["enabled"])
        self.assertFalse(
            any(str(value).strip() for value in connector["credentials"].values())
        )

    def test_live_deployment_files_are_not_tracked_templates(self):
        ignore = (ROOT / ".gitignore").read_text()
        for name in ("config.json", "connector.json", "project_profile.json"):
            self.assertIn(name, ignore)

    def test_open_source_governance_files_exist(self):
        for name in (
            "LICENSE",
            "README.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "CHANGELOG.md",
            "docs/prebuilt-raspberry-pi.md",
        ):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_public_sources_use_provider_neutral_domain_language(self):
        text_suffixes = {
            ".bat", ".desktop", ".json", ".md", ".py", ".service",
            ".sh", ".toml", ".txt", ".yaml", ".yml",
        }
        forbidden = re.compile(
            r"work[ _-]?orders?|work" + r"orders?|\bW" + r"O\b|sequential" + r"Id|"
            r"maintain" + r"x|\bAP" + r"AG\b|\bA" + r"CA\b|downtime[ _-]?tracker|"
            r"line[ _-]response[ _-]console|\bL" + r"RC(?:[_-]|\b)|"
            r"ops[ _-]?cue|line[ _-]mantx",
            re.IGNORECASE,
        )
        excluded_parts = {".git", "build", "dist", "pi_build_output", "build_history"}
        findings = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            if excluded_parts.intersection(path.relative_to(ROOT).parts):
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if forbidden.search(line):
                    findings.append(f"{path.relative_to(ROOT)}:{line_number}")
        self.assertEqual(findings, [], "provider-shaped terms found: " + ", ".join(findings))


if __name__ == "__main__":
    unittest.main()
