# Raspberry Pi kiosk efficiency and hardening

This describes **v1.2.0**. The resource improvements preserve
the existing appearance, touch actions, grouping, timers, connector contract and
offline-delivery semantics. No additional runtime dependency is introduced.

## Resource behavior

- Fullscreen Information, failure, crew and other opaque pages draw only their
  visible content. The production map and conveyor are not drawn underneath them.
- A static dialog has a one-second fallback refresh instead of continuous polling
  at animation speed. Touches, keyboard input, resizing and asynchronous results
  still request immediate paint. Touch feedback wakes the existing animation
  timer; it cannot start parallel animation chains.
- The main-screen animation interval is unchanged. Busy dialogs keep a faster
  refresh, and brief touch rings use the normal configured animation interval.
  Animation phases use elapsed monotonic time; skipped frames do not accumulate.
- Audio has at most two workers. Repeated previews cannot create unlimited threads
  or players. Excess cues are dropped, never delivered late. Visual state remains
  authoritative.
- Failed HTTP responses are closed explicitly. Device-care exceptions and thread
  exhaustion do not permanently disable its next check or take the operator lock.
- Audit permission maintenance does not reopen already-private segments; shared
  date directories are checked once per pass. Actual repairs still verify the
  open file descriptor before changing its permissions.
- A history cleanup with no records or remote-ID links to acknowledge updates
  health without acquiring the operator-action lock or rewriting recovery state.
  Actual history batches keep their durable acknowledgement and retry behavior.

Tk's event loop is cooperative: blocking callbacks delay input and painting.
These changes reduce unnecessary work; they do not replace the existing durable
worker queues. See the [Tk threading model](https://docs.python.org/3/library/tkinter.html#threading-model)
and [measured rendering results](ui-performance.md#pi-kiosk-efficiency-review--27-october-2026).

## Local-file safeguards

Security/throttle files use bounded, strict JSON and checked regular-file reads.
Invalid data never enables a default-password fallback where a local credential
exists. Authentication throttling fails conservatively without preventing the
operator application from opening. Audit writes, rotation and permission repair
reject unsafe file types and hard links before modifying their content.

These checks protect against malformed data, accidental filesystem damage and
some unsafe local-file substitutions. They are **not** an OS sandbox or protection
against someone who controls the kiosk account, binary or parent directories.
Use a dedicated unprivileged account, restrict runtime-directory access, change
the public bootstrap password, keep OS packages patched, and protect removable
update media. See [security boundaries](security.md) and [Settings access](settings-access.md).

## Pi 5 commissioning

1. Use a supported 64-bit OS and the native build matching that architecture.
   Tk still needs a graphical session even when desktop panels are hidden.
2. Verify power and cooling under the actual enclosure/display load. Thermal or
   supply throttling can affect responsiveness; follow the
   [official Raspberry Pi hardware guidance](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#frequency-management-and-thermal-control).
   Do not disable hardware protection or overclock as a workaround for lag.
3. Confirm touch alignment, rotation, fullscreen startup, correct audio output and
   access to every action using the actual panel and any gloves used on site.
4. Check **Settings → System** for storage, audit and available health observations.
   Missing platform sensors do not stop reporting. Investigate warnings.
5. Check clock synchronization, backups and service restart behavior. Preserve
   incident state, pending delivery and the private history database; logs alone
   are not a recovery source.
6. Run a representative multi-day soak, disconnect/reconnect networking, restart
   with queued reports and exercise controlled storage/power-loss recovery on a
   nonproduction installation before deployment.

The application does not change Pi power governors, cooling settings, compositor
configuration, OS passwords or touchscreen calibration automatically.

### Checking a physical panel safely

Use a spare terminal or an explicitly authorized maintenance window. The following
opt-in driver takes over the display briefly; do not run it over an active operator
session. Run it from the Pi's graphical terminal, using the existing display
session credentials (do not disable X11 access control to make SSH tests work):

```bash
umask 077
FLOORTERMINAL_DISABLE_NETWORK=1 PYTHONPATH=src python3 tests/unit/panel_ui_driver.py --capture /tmp/floorterminal-panel-captures
FLOORTERMINAL_DISABLE_NETWORK=1 PYTHONPATH=src python3 tests/unit/touch_budget_driver.py --sizes 1920x1200
```

The first command uses the actual screen size, verifies fullscreen startup,
Information/password pages and all six Settings pages, and measures short
event-loop/render timings. The second accepts the panel's resolution through
`--sizes`; replace the example dimensions with your display's dimensions. It
exercises durable workflows through generated touch events, including crew edits
and handover. **Generated events do not verify finger/glove input or calibration.**

Both use disposable runtime data and deny network connections. They never read
the production connector, install a release, restart the production service or
change monitor settings. Close other test instances before running another GUI
driver. Review captures privately; remove the capture directory when finished.
Pillow is optional for captures; Pi Wayland sessions additionally need `grim` if
Pillow cannot capture the XWayland surface. Screenshot helpers restrict capture to
the requested window, bound the fallback wait, and reject blank/incomplete frames.
They do not add any dependency to the application itself.

### A service is present but the installed application is missing

A service definition alone is not an installed release. First inspect:

```bash
systemctl --user status floorterminal.service --no-pager
ls -ld /opt/floorterminal /opt/floorterminal/bin/floorterminal-launch
journalctl --user -u floorterminal.service -n 30 --no-pager
```

If the deployment directory has been removed, `ReadWritePaths` can fail before the
launcher executes, producing `226/NAMESPACE`. This exit code has other possible
causes too; inspect paths and available logs before drawing a conclusion. Do not
remove sandbox directives or create empty directories merely to hide the error.
Restore a verified release with the documented installer and recover site data
from its backup where necessary. Installing an unreleased development snapshot is
a separate decision, not an automatic repair to a production terminal. A user
without journal access may need an administrator to inspect the system journal.

## Evidence and limits

The 27 October 2026 review runs the complete offline suite on a Pi 5 ARM64 private
display: **588 tests pass, no skips**. Existing 65 short-touch paths, 4,632 adaptive
layout cases, independent-group and offline-delivery tests remain covered.

A same-device before/after comparison rendered 24,000 measured dialog frames.
The tested dialog p95 rendering times fell by approximately **80–92%**, not the
entire application's CPU utilization. A native 800×480 Information-page capture
is pixel-identical before and after. A further 9,000 grouped main-screen frames
showed bounded item/image counts and 0–16 KiB RSS change after warm-up.

These are synthetic offline checks, not months of continuous operation, a physical
touch latency guarantee, a penetration-test certification or proof that no bugs
remain. No provider API, customer credential, signing private key or installed
kiosk was used or changed. See [verification](verification.md) for details.

A subsequent check used an attached 1920×1200 panel under the Pi's actual Wayland
session rather than a virtual display. See the separate
[physical-panel results](verification.md#physical-panel-check--27-october-2026)
for its scope and limits; it does not change the earlier virtual-display evidence.
