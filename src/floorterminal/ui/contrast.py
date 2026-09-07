"""Contrast arithmetic for readable status colour on a factory touchscreen.

A palette colour serves two different jobs, and one value cannot do both well:

* **as a fill** behind a status shape it must stay distinguishable from the other
  status fills, which requires the palette to keep a spread of lightness;
* **as small text** on a light surface it must reach a high contrast ratio, which
  pushes every colour towards the same darkness.

Darkening a whole palette to satisfy the text rule collapses that lightness spread
and destroys the very separation a colour-blind-safe palette exists to provide, so
the two roles are handled separately: fills keep their palette value, and text
derives a darker variant of the same hue.

Ratios follow the WCAG 2.1 relative-luminance definition. The thresholds used here
are 3:1 for a large bold control label or a graphical object, and 4.5:1 for normal
body text.
"""

from __future__ import annotations

import colorsys
from itertools import pairwise

WHITE = "#FFFFFF"
#: Minimum acceptable ratio for a bold control label sitting on a filled button.
LABEL_MINIMUM = 3.0
#: Minimum acceptable ratio for small text on a surface.
TEXT_MINIMUM = 4.5


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def _components(colour):
    text = str(colour).strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Expected a six-digit hexadecimal colour, got {colour!r}")
    return tuple(int(text[index : index + 2], 16) / 255 for index in (0, 2, 4))


def relative_luminance(colour) -> float:
    """Return the WCAG relative luminance of a ``#RRGGBB`` colour."""
    red, green, blue = (_channel(value) for value in _components(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first, second) -> float:
    """Return the WCAG contrast ratio between two colours, from 1.0 to 21.0."""
    a, b = relative_luminance(first), relative_luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def readable_label(fill, dark, light=WHITE, minimum=LABEL_MINIMUM) -> str:
    """Choose a control-label colour that stays legible on ``fill``.

    ``light`` is preferred so the established look is kept wherever it is already
    readable; ``dark`` is used only when the light label would fall below the
    threshold. This also protects deployment-chosen custom palettes, where a pale
    fill would otherwise be given white text.
    """
    if contrast_ratio(light, fill) >= minimum:
        return light
    return dark if contrast_ratio(dark, fill) > contrast_ratio(light, fill) else light


def text_variant(colour, surface=WHITE, minimum=TEXT_MINIMUM, steps=200) -> str:
    """Return the same hue darkened until it is readable as text on ``surface``.

    Hue and saturation are preserved so the colour keeps its meaning; only
    lightness moves. The original is returned when it already qualifies.
    """
    if contrast_ratio(colour, surface) >= minimum:
        return _normalise(colour)
    red, green, blue = _components(colour)
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    for step in range(1, steps + 1):
        candidate = _from_hls(hue, lightness * (1 - step / steps), saturation)
        if contrast_ratio(candidate, surface) >= minimum:
            return candidate
    return "#000000"


def _from_hls(hue, lightness, saturation) -> str:
    red, green, blue = colorsys.hls_to_rgb(hue, max(0.0, lightness), saturation)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def _normalise(colour) -> str:
    return "#" + str(colour).strip().lstrip("#").upper()


def separation(colours):
    """Return the smallest luminance gap between any two colours in ``colours``.

    Status fills are told apart by lightness as well as hue, which is what keeps
    them usable for an operator with impaired colour vision. A palette change that
    collapses this value has removed that redundancy.
    """
    values = sorted(relative_luminance(colour) for colour in colours)
    if len(values) < 2:
        return 0.0
    return min(second - first for first, second in pairwise(values))
