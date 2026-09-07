# Image provenance

Every interface image in this directory is generated from the running application
by [`scripts/docs/capture_images.py`](../../scripts/docs/capture_images.py), using
the neutral offline demonstration configuration and no connector. None contains a
manually redrawn application screen.

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

Main screens and dialogs are captured at **1600×960 native pixels**, and Settings
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
