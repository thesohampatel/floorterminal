# Image provenance

The main walkthrough images were regenerated from v1.2.0 on 3 November 2026 on
the attached Pi 5 graphical session, at native 1600×960 pixels. They show only
disposable offline data. Update examples derive the installed version from the
package and explicitly illustrate a hypothetical next release; they do not query
or announce a real future version.

The release images in this directory are captured from the running app
by [`scripts/docs/capture_images.py`](../../scripts/docs/capture_images.py), using
the neutral offline demonstration configuration and no connector. None contains a
manually redrawn application screen.

`v1.2-development/` retains the dated native previews captured while developing
v1.2.0; its directory name records provenance, not release availability.
The `saved-team-*` images are native 2 November 2026 captures of the Settings
roster section from `tests/unit/roster_ui_driver.py --capture DIR`, using the
attached Pi graphical session. The saved member count/time is disposable fixture
data; requests use an in-memory transport and sockets are blocked. The driver
also verifies button reachability, stable open pickers, unchanged connector/config
files and responsiveness during a blocked refresh. No installed kiosk data is used.

The `failure-reasons-*` files are native 2 November 2026 captures of app-owned
800×480 and 480×800 viewports on the attached Pi 5 graphical session. They come
from `tests/unit/variable_failure_ui_driver.py --capture DIR`, with a neutral
53-reason fixture, no credentials and socket connections blocked. The driver
waits for touch feedback/page transitions to finish before capturing. It also
checks 30 catalogue/viewport combinations, cross-page editor preservation and
refusal to edit recorded reasons during an active incident.

The `panel-*-1920x1200.png` files are native 29 October 2026 captures on an
attached Pi 5 / Wayland/labwc touchscreen. `panel-crew` and `panel-settings` use
`tests/unit/panel_ui_driver.py`; `panel-groups` uses the grouped rendering scene
from `tests/unit/render_stress_driver.py --groups --screenshots DIR`.
All are disposable neutral fixtures with network calls blocked. The grouped scene
illustrates stopped/responding/running groups; it is not a live production record.
No production desktop, credential or account data is shown, and no image is upscaled.
`panel-choice-800x480.png` is the corresponding native touch-option sheet from
`tests/unit/experience_ui_driver.py --capture DIR`, using the same blocked-network
fixture and an app-owned 800×480 viewport on that panel.

The `groups-*` and `group-overview.png` files were refreshed on 26 October 2026;
`group-settings.png` remains the 25 October capture. They are native Pi/Xvfb captures from
`tests/unit/group_ui_driver.py --capture DIR`. Neutral standalone fixtures show
two independently active incidents and a third running group. The actual touch
flow and Settings save/reload are exercised; sockets are denied before startup.
They contain no deployment data and are not upscaled.

The earlier `settings.png`, `connection.png` and `stations.png` are native
1600×960 Pi/Xvfb captures from
[`tests/unit/render_stress_driver.py`](../../tests/unit/render_stress_driver.py)
using `--screenshots`, the same neutral runtime, and no connector API calls. They
do not replace the published-release walkthroughs. See
[development UI verification](../ui-performance.md).

The `kiosk-*` and `settings-*-*` files in that folder are the newer 24 October
adaptive-layout captures from `tests/unit/adaptive_ui_driver.py --capture DIR`.
Their dimensions are in their filenames; they are not upscaled. This isolated
test enables UI capabilities with an in-memory descriptor to show action layouts,
but blocks socket connections and has no credentials. The visible “not configured”
status is intentional: these are layout previews, not live-service demonstrations.

The `operator-response-*` files were refreshed on 26 October 2026;
`kiosk-password.png` remains the 24 October capture. They are native 800×480
Pi/Xvfb captures produced by
`tests/unit/operator_ui_driver.py --capture DIR`. They show the actual offline
touch-through self-fix/handover workflow. All sockets are denied; operator/station
names are neutral fixtures. The driver verifies the whole window matches the
capture dimensions; no screen is cropped from an oversized window or upscaled.

The `touch-*` files are native 26 October 2026 Pi/Xvfb captures from
`tests/unit/touch_budget_driver.py --capture DIR`, showing the shortened report,
crew and release paths. Dimensions are in the filenames. This driver uses a
scripted transport, a synthetic roster and a fixture-only credential, with socket
connections blocked before app startup. A green Connected label is a fixture UI
state, not evidence of a live service connection. No fixture credential is visible.
See [operator touch flows](../operator-touch-flow.md).

The `delivery-*` files are native 21 October Pi/Xvfb captures from
`tests/unit/delivery_ui_driver.py --capture DIR`. They show a deliberately held
offline fixture in Saved updates at 800×480 and 1920×1080. Socket connections are
blocked; identifiers and messages are synthetic. No real credential, customer
information or provider response is included.

The update images use immutable, in-memory status snapshots that match the typed
`UpdateStatus` contract exercised by the test suite. This keeps documentation
generation network-free and prevents it from reading deployment or signing data.
Signature, manifest, media, staging, activation, rollback, and launcher behaviour
remain covered separately by the offline automated tests. The indicator reference
and `update-walkthrough.gif` are assembled from the same real interface captures.

The screenshots contain no production data, credentials, real API responses,
build-host account names, or desktop content. Soham Patel's approved public name
and support email are deliberately visible in Information. The update views use an
illustrative USB path and fictional future release states. These are MIT-licensed
documentation artifacts, not evidence of a live integration or published update.

Published-release main screens and dialogs are captured at **1600×960 native pixels**, and Settings
is captured at its own native fitted window dimensions. PNG is lossless. The
operator walkthrough uses lossless animated WebP. The live conveyor recording and
the update GIF are reduced to 1200×720 for download size. No screenshot is enlarged.
The logo has a separate [SVG master](../../branding/floorterminal/floorterminal-mark.svg).

Regenerate them whenever the interface or product identity changes; a stale
screenshot is a documentation defect. From a graphical desktop session:

```bash
python3 -m pip install Pillow
python3 scripts/docs/capture_images.py
```

On a Pi whose attached panel is only 800×480, render native HD in a private virtual
display instead of enlarging the panel's output:

```bash
sudo apt-get install xvfb xauth python3-pil fonts-dejavu-core
xvfb-run -a -s "-screen 0 1920x1200x24 -dpi 96 -nolisten tcp" \
  python3 scripts/docs/capture_images.py
```

The harness isolates all runtime files in a temporary directory, disables sounds
and network update checks, brings the application window forward, rejects a blank
frame or undersized capture, and verifies that all 22 expected assets were produced.
Windowed mode is forced for capture so kiosk fullscreen cannot silently shrink an
HD request to the attached panel's size. This is documentation tooling only, not a
production simulation mode. On current
Raspberry Pi OS Wayland/labwc sessions it automatically falls back from Pillow's
X11 capture path to the native `grim` region-capture utility.
