# Accessibility and human-factors evidence

This document distinguishes automated geometry/contrast checks from physical
usability that must be checked at the installation. See [release verification](verification.md)
for the current tested version, platforms and limitations.

It supports the human-centred-design guidance referenced in
[industrial deployment](industrial-deployment.md) (ISO 9241-210) and uses
[WCAG 2.1](https://www.w3.org/TR/WCAG21/) contrast arithmetic as an objective
yardstick. Neither reference is a certification claim, and neither replaces site
usability validation on the commissioned display, at the real viewing distance,
with the gloves and lighting the operators actually have.

## How to reproduce

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_accessibility -v
PYTHONPATH=src python3 -m unittest tests.unit.test_ui_smoke -v
```

The GUI drivers render workflow states and read the registered touch targets, not
just the intended rectangles in a design drawing. Version 1.2 uses a reflowing
viewport, not a fixed 800×480 picture enlarged to fill every screen. Its density
depends on available pixels and orientation; text measurement and available space
also affect control layout. See [adaptive kiosk layouts](adaptive-kiosk.md).

## Touch targets

The normal control design uses approximately **48 logical units**; geometry
regressions check minimum **44-unit** targets on the operational paths they cover.
Settings footer checks also verify that Save and Cancel are mapped, on-screen and
actually receive input rather than being covered by another widget. Large reason
catalogues use bounded pages/search instead of shrinking every option to fit.

These are not guaranteed millimetre measurements. Two displays with the same
resolution can have different physical sizes, and reported DPI is not reliable
enough to certify finger or glove usability. To measure an installed control:

```text
control width in mm = rendered width in pixels × active panel width in mm / panel width in pixels
```

Use the actual active display area, account for compositor scaling, and measure
height separately. Test the smallest controls, spacing and accidental-touch rate
with the site's gloves, lighting and viewing distance before production. The
old fixed-layout millimetre table is not applicable to the adaptive 1.2 interface.
See [industrial deployment](industrial-deployment.md) for the site checklist.

## Layout integrity

The supported usable viewport starts at **320×400 pixels**. Larger landscape,
portrait and wide panels reflow; a list may use paging/search rather than exposing
unreachable controls. Tests exercise several pixel sizes rather than assuming
that a diagonal measurement determines layout. Font rounding can still affect
text bounds, so `test_ui_smoke`, `test_adaptive_layout`, `test_quick_actions` and
the group/failure GUI drivers check their respective states for:

- Text collisions within the same layer and text hidden by later opaque shapes.
- Text and control bounds outside the viewport.
- Overlapping or undersized operational hit targets.
- Settings actions covered by another widget or pushed off-screen.

Transient feedback uses a reserved status area rather than covering the station
map or action buttons. Compact layouts may shorten secondary wording or move
additional actions into a dedicated page. Tested bounds and collision checks do
not prove every arbitrary configuration or compositor behaves identically.

## Colour and contrast

Colour is never the only signal anywhere in the interface: status is carried
simultaneously by wording, an animated face glyph, a station glyph, border weight,
and motion. The contrast figures below therefore describe legibility, not the
integrity of the status indication.

A palette colour has to do two different jobs, and one value cannot do both:

* **as a fill** it must stay distinguishable from the other status fills, which
  needs the palette to keep a spread of lightness;
* **as small text** on a light surface it must reach 4.5:1, which pushes every
  colour towards the same darkness.

Darkening a whole palette to satisfy the text rule was measured and rejected: it
collapses the lightness spread of the five status colours to a pairwise contrast of
1.00, which removes exactly the redundancy a colour-blind-safe palette exists to
provide. `tests/unit/test_accessibility.py` locks that spread so the mistake cannot
be reintroduced.

### What is enforced

* Status-button label colour selection targets at least 3:1 against its fill.
  Tests cover the packaged palettes and representative pale custom fills.
  `ui/contrast.py` keeps the
  established white label wherever it is readable and substitutes the dark text
  colour only where white would fail — which is what happens on amber, and matches
  the dark-on-amber convention used for caution signage.
* The five status fills keep a measurable lightness separation in both palettes.
* Every status fill stays visible against both surfaces behind it.
* A compliant darker text variant of the same hue exists for every palette role.

These internal colour tests are not a complete WCAG audit: physical text size,
every custom surface, focus visibility and assistive-technology support need
separate assessment. Review custom palettes on the actual display.

### Measured contrast

**standard** — measured against the page background `#F3F5F9`:

| Role | Colour | As small text | As a button fill (chosen label) |
|---|---|---|---|
| text | `#14213D` | 14.63 — meets 4.5:1 | 15.97 with the white label |
| muted | `#718096` | 3.68 — large text only | 4.02 with the white label |
| red | `#E84855` | 3.50 — large text only | 3.83 with the white label |
| green | `#16A36A` | 2.97 — below 3:1 | 3.24 with the white label |
| blue | `#246BFD` | 4.19 — large text only | 4.57 with the white label |
| orange | `#F09A3E` | 2.05 — below 3:1 | 7.15 with the dark label |
| purple | `#7956D8` | 4.65 — meets 4.5:1 | 5.08 with the white label |

**colorblind_safe** — measured against the page background `#F3F5F9`:

| Role | Colour | As small text | As a button fill (chosen label) |
|---|---|---|---|
| text | `#14213D` | 14.63 — meets 4.5:1 | 15.97 with the white label |
| muted | `#64748B` | 4.36 — large text only | 4.76 with the white label |
| red | `#D55E00` | 3.54 — large text only | 3.87 with the white label |
| green | `#0072B2` | 4.75 — meets 4.5:1 | 5.19 with the white label |
| blue | `#56B4E9` | 2.11 — below 3:1 | 6.92 with the dark label |
| orange | `#E69F00` | 2.06 — below 3:1 | 7.09 with the dark label |
| purple | `#CC79A7` | 2.80 — below 3:1 | 3.06 with the white label |

### Small coloured text

Coloured text below 10 points is drawn in a darker variant of its own hue, computed
at runtime by `ui/view.readable_text()` from `ui/contrast.text_variant()`. The fill
values in the table above are unchanged — only the text role moves — so status
colours keep their meaning and their separation while captions and status words
reach the small-text threshold.

The substitution is deliberately limited to the five status colours and the muted
colour. White on a filled control, the dark text colour, and one-off tints are drawn
exactly as asked, because only the caller knows what surface they sit on.

## Redundant status encoding

| Signal | Carried by |
|---|---|
| Words | Status title and subtitle on the machine card and the primary control |
| Glyph | Animated status face, per-station state glyph, vector button icons |
| Shape | Station/group boundaries, selected outlines and press feedback |
| Motion | Conveyor, rollers, drive elements and products move only while running |
| Colour | Palette role, chosen last and never alone |

The software-update indicator follows the same rule: it carries a distinct vector
glyph per state — a tick, a download arrow, or an alert mark — and adds a second
corner marker whenever it is not green, so it is identifiable without colour.

## Language

English is the packaged and verified interface language. Existing catalogue-based
labels have an English fallback; tests check referenced catalogue keys and the
established Settings/update labels. Some newer operational captions, validation
messages and diagnostics remain English literals. Adding a catalogue alone does
**not** translate every screen or establish complete localization support.

The graphical suites open all six protected Settings categories across compact,
portrait and desktop viewports, checking navigation and footer reachability.
Any additional locale needs a full wording, text-overflow and operator-usability
review. Right-to-left layout is not supported.

## Known limits

* Figures are geometric and colorimetric. They do not measure legibility at a given
  viewing distance, under plant lighting, through a protective screen, or for a
  specific operator population.
* Typography is small in absolute terms on a 7-inch panel; validate it at the real
  viewing distance before commissioning.
* No screen-reader or switch-access support is claimed. This is a fixed-function
  touchscreen, not a general-purpose computing device.
