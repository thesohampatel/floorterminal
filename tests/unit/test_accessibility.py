import json
import re
import unittest
from pathlib import Path

from floorterminal.core.config import COLORBLIND_SAFE_COLORS, DEFAULT_CONFIG
from floorterminal.ui.contrast import (
    LABEL_MINIMUM,
    TEXT_MINIMUM,
    WHITE,
    contrast_ratio,
    readable_label,
    relative_luminance,
    separation,
    text_variant,
)

ROOT = Path(__file__).resolve().parents[2]

PALETTES = {
    "standard": DEFAULT_CONFIG["ui_colors"],
    "colorblind_safe": COLORBLIND_SAFE_COLORS,
}
STATUS_ROLES = ("red", "green", "blue", "orange", "purple")
#: Every surface a status colour is drawn on or against.
SURFACES = ("card", "background")


class ContrastArithmeticTests(unittest.TestCase):
    def test_matches_the_wcag_reference_values(self):
        self.assertAlmostEqual(relative_luminance("#FFFFFF"), 1.0, places=6)
        self.assertAlmostEqual(relative_luminance("#000000"), 0.0, places=6)
        self.assertAlmostEqual(contrast_ratio("#000000", "#FFFFFF"), 21.0, places=4)
        self.assertAlmostEqual(contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0, places=6)
        # A published worked example: #777777 on white is 4.48:1, just under AA.
        self.assertAlmostEqual(contrast_ratio("#777777", WHITE), 4.48, places=2)
        self.assertEqual(contrast_ratio("#123456", "#654321"), contrast_ratio("#654321", "#123456"))

    def test_rejects_malformed_colour_input(self):
        for value in ("", "#FFF", "not-a-colour", "#GGGGGG"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                relative_luminance(value)


class ControlLabelReadabilityTests(unittest.TestCase):
    """Every button label must clear the large-bold-text threshold on its fill."""

    def test_each_palette_produces_readable_labels_on_every_status_fill(self):
        for name, palette in PALETTES.items():
            for role in STATUS_ROLES:
                fill = palette[role]
                chosen = readable_label(fill, palette["text"])
                with self.subTest(palette=name, role=role):
                    self.assertGreaterEqual(
                        contrast_ratio(chosen, fill),
                        LABEL_MINIMUM,
                        f"{name}/{role} label {chosen} on {fill} is unreadable",
                    )

    def test_the_established_white_label_is_kept_wherever_it_is_readable(self):
        palette = PALETTES["standard"]
        for role in ("green", "blue", "purple", "red"):
            with self.subTest(role=role):
                self.assertEqual(readable_label(palette[role], palette["text"]), WHITE)

    def test_the_amber_surface_switches_to_the_dark_label(self):
        """White on amber measures 2.23:1; the dark label reaches 7.15:1."""
        palette = PALETTES["standard"]
        self.assertLess(contrast_ratio(WHITE, palette["orange"]), LABEL_MINIMUM)
        chosen = readable_label(palette["orange"], palette["text"])
        self.assertEqual(chosen, palette["text"])
        self.assertGreater(contrast_ratio(chosen, palette["orange"]), 7.0)

    def test_a_pale_custom_palette_still_gets_a_readable_label(self):
        """Deployments may choose their own colours; white must not be assumed."""
        for pale in ("#FFF3E5", "#EDF3FF", "#F4F6FA", "#FFFFFF"):
            with self.subTest(fill=pale):
                chosen = readable_label(pale, "#14213D")
                self.assertGreaterEqual(contrast_ratio(chosen, pale), LABEL_MINIMUM)


class StatusSeparationTests(unittest.TestCase):
    """Status colours are told apart by lightness as well as hue.

    Flattening a palette so every colour reaches the small-text threshold would
    give all five status colours the same luminance and remove that redundancy,
    which is the opposite of an accessibility improvement. This locks the spread.
    """

    MINIMUM_SEPARATION = 0.01

    def test_status_fills_keep_a_usable_lightness_spread(self):
        for name, palette in PALETTES.items():
            fills = [palette[role] for role in STATUS_ROLES]
            with self.subTest(palette=name):
                self.assertGreaterEqual(
                    separation(fills),
                    self.MINIMUM_SEPARATION,
                    f"{name} status fills are too close in lightness to tell apart",
                )

    def test_every_status_fill_is_distinguishable_from_both_surfaces(self):
        for name, palette in PALETTES.items():
            for role in STATUS_ROLES:
                for surface in SURFACES:
                    with self.subTest(palette=name, role=role, surface=surface):
                        self.assertGreaterEqual(
                            contrast_ratio(palette[role], palette[surface]),
                            1.5,
                            "a status fill must be visible against the surface behind it",
                        )


class TextVariantTests(unittest.TestCase):
    """Small coloured text needs a darker variant of the same hue."""

    def test_a_compliant_text_variant_exists_for_every_palette_role(self):
        for name, palette in PALETTES.items():
            for role in (*STATUS_ROLES, "muted"):
                for surface in SURFACES:
                    variant = text_variant(palette[role], palette[surface])
                    with self.subTest(palette=name, role=role, surface=surface):
                        self.assertGreaterEqual(
                            contrast_ratio(variant, palette[surface]), TEXT_MINIMUM
                        )

    def test_an_already_compliant_colour_is_returned_unchanged(self):
        palette = PALETTES["standard"]
        self.assertEqual(text_variant(palette["text"], palette["card"]), palette["text"])

    def test_the_variant_only_moves_lightness(self):
        """The hue must survive so the colour keeps its meaning."""
        import colorsys

        for original in ("#F09A3E", "#16A36A", "#246BFD", "#CC79A7"):
            variant = text_variant(original)
            with self.subTest(colour=original):
                def hue(value):
                    red, green, blue = (int(value[i : i + 2], 16) / 255 for i in (1, 3, 5))
                    return colorsys.rgb_to_hls(red, green, blue)[0]

                self.assertAlmostEqual(hue(original), hue(variant), places=2)
                # Already-compliant colours come back untouched; the rest darken.
                self.assertLessEqual(
                    relative_luminance(variant), relative_luminance(original)
                )
                self.assertGreaterEqual(contrast_ratio(variant, WHITE), TEXT_MINIMUM)


if __name__ == "__main__":
    unittest.main()


class LocaleCoverageTests(unittest.TestCase):
    """User-facing wording must resolve through the catalogue, not be baked in."""

    UI = ROOT / "src" / "floorterminal" / "ui"
    #: Text the console deliberately keeps in English, as it does for error text:
    #: colour role names, and hexadecimal colour examples.
    ALLOWED = frozenset({"#246BFD"})

    def _literals(self, path):
        source = path.read_text(encoding="utf-8")
        found = set()
        for pattern in (
            r'text="((?:[^"\\]|\\.)+)"',
            r'_section\(\s*\n?\s*\w+,\s*\n?\s*"((?:[^"\\]|\\.)+)"',
            r'_field\(\s*\n?\s*\w+,\s*\n?\s*[\w\s+]+,\s*\n?\s*"((?:[^"\\]|\\.)+)"',
            r'_button\(\s*\n?\s*\w+,\s*\n?\s*"((?:[^"\\]|\\.)+)"',
            r'\(\s*"((?:[^"\\]|\\.)+)",\s*"[a-z_0-9]+"\s*\)',
        ):
            found.update(match.group(1) for match in re.finditer(pattern, source))
        return {value for value in found if value not in self.ALLOWED and len(value) > 1}

    def test_the_settings_window_carries_no_untranslated_wording(self):
        leftover = self._literals(self.UI / "settings.py")
        self.assertEqual(leftover, set(), f"untranslated Settings wording: {leftover}")

    def test_the_catalogue_has_an_english_entry_for_every_key_in_use(self):
        catalogue = json.loads(
            (ROOT / "src" / "floorterminal" / "i18n" / "en.json").read_text(
                encoding="utf-8"
            )
        )
        used = set()
        for path in sorted(self.UI.glob("*.py")):
            used.update(re.findall(r'self\.t\(\s*"([a-z0-9_]+)"', path.read_text()))
        missing = sorted(used - set(catalogue))
        self.assertEqual(missing, [], f"catalogue keys used but not defined: {missing}")
        self.assertGreater(len(catalogue), 140)
