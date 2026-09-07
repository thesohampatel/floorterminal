# Accessibility and human-factors evidence

This document records what has been **measured**, not what is intended. Every figure
below is reproducible from the repository, and the rules that are enforced are
enforced by tests rather than by review.

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

Touch-target figures come from the live application: the sweep renders every
workflow state and dialog, reads the touch targets the controller actually
registered, and converts logical units to millimetres using the active area of each
panel. The interface is a fixed 800 x 480 logical design scaled uniformly, so a
larger panel enlarges every control by the same factor.

## Touch targets

| Control | Logical | 7-inch 800x480 | 10.1-inch 1280x800 |
|---|---|---|---|
| Primary action (report / repair / complete) | 479 x 60 | 92.3 x 11.6 mm | 129.9 x 16.3 mm |
| Station select | 56 x 78 | 10.8 x 15.0 mm | 15.2 x 21.2 mm |
| Whole-line select | 212 x 47 | 40.8 x 9.1 mm | 57.5 x 12.7 mm |
| Failure choice | 276 x 54 | 53.2 x 10.4 mm | 74.9 x 14.6 mm |
| Failure dialog controls | 112 x 47 | 21.6 x 9.1 mm | 30.4 x 12.7 mm |
| Responder row | 540 x 47 | 104.0 x 9.1 mm | 146.4 x 12.7 mm |
| Confirm / save in a dialog | 360 x 47 | 69.3 x 9.1 mm | 97.6 x 12.7 mm |
| Settings gear | 48 x 48 | 9.2 x 9.2 mm | 13.0 x 13.0 mm |
| Information | 48 x 48 | 9.2 x 9.2 mm | 13.0 x 13.0 mm |
| Software update indicator | 48 x 48 | 9.2 x 9.2 mm | 13.0 x 13.0 mm |
| On-screen keyboard key | 48 x 47 | 9.2 x 9.1 mm | 13.0 x 12.7 mm |
| Update panel tab | 161 x 47 | 31.0 x 9.1 mm | 43.7 x 12.7 mm |
| Update panel action | 128 x 47 | 24.7 x 9.1 mm | 34.7 x 12.7 mm |

71 distinct controls measured. Every control clears 9 mm on both supported panels except 0 on the 7-inch panel. The smallest control anywhere is 9.1 mm.

**What this means.** Every registered control clears the 9 mm guidance on both
supported panels. The figures come from the running application, not from the source,
so a layout change that shrinks a control is visible immediately.

**Open decision for the deployment owner.** Nine millimetres is common guidance for an
ungloved fingertip; heavy gloves are usually given 15 mm or more, which the primary
action, station selection, whole-line selection and failure choices already exceed on
both panels. [Industrial deployment](industrial-deployment.md) step 8 requires this to
be confirmed with the site's real gloves before production.

## Layout integrity

The interface is one 800 x 480 logical design scaled uniformly, but font sizes are
rounded per scale, so a label can outgrow its container at one panel size and not
another. `tests/unit/test_ui_smoke.py` therefore renders every workflow state and
dialog at **7-inch, 10.1-inch and desktop** sizes and fails on:

* any two pieces of text whose bounding boxes overlap within the same layer;
* any text painted over by a shape drawn after it — the collision an operator
  actually notices, because the label is simply not there;
* any text drawn outside the canvas.

Transient feedback owns the centre of the header by design. While a message is
showing, the ambient chips step aside rather than being drawn underneath it; the
clock, the update indicator, Information and Settings always remain available.

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

* Every control label reaches at least 3:1 against its own fill, in both packaged
  palettes and in any deployment-chosen custom palette. `ui/contrast.py` keeps the
  established white label wherever it is readable and substitutes the dark text
  colour only where white would fail — which is what happens on amber, and matches
  the dark-on-amber convention used for caution signage.
* The five status fills keep a measurable lightness separation in both palettes.
* Every status fill stays visible against both surfaces behind it.
* A compliant darker text variant of the same hue exists for every palette role.

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
| Shape | Border weight and the animated focus ring around the next valid control |
| Motion | Conveyor, rollers, drive elements and products move only while running |
| Colour | Palette role, chosen last and never alone |

The software-update indicator follows the same rule: it carries a distinct vector
glyph per state — a tick, a download arrow, or an alert mark — and adds a second
corner marker whenever it is not green, so it is identifiable without colour.

## Language

The interface is drawn from a packaged locale catalogue with a guaranteed English
fallback. The catalogue holds 155 keys and covers the operator screen, the Software
Update panel, and the protected Settings window. Two tests enforce this:
`test_accessibility` fails if any user-facing wording in Settings is a source
literal or if a key is used without a catalogue entry, and `test_update_application`
fails if any update-panel label does not resolve.

The graphical smoke suite opens protected Settings at the minimum 800×480 viewport,
selects each of its six tabs, and fails if a tab is unreachable or outside the
visible notebook bounds.

Diagnostic text produced by the update service and by configuration validation is
English by design, as error text is elsewhere in the console. A site deploying in
another language adds one JSON catalogue at build time and selects it with
`ui_language`. Right-to-left layout is not supported.

## Known limits

* Figures are geometric and colorimetric. They do not measure legibility at a given
  viewing distance, under plant lighting, through a protective screen, or for a
  specific operator population.
* Typography is small in absolute terms on a 7-inch panel; validate it at the real
  viewing distance before commissioning.
* No screen-reader or switch-access support is claimed. This is a fixed-function
  touchscreen, not a general-purpose computing device.
