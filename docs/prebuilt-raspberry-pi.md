# Prebuilt Raspberry Pi installation

This guide is for the source-free Linux ARM64 application bundle published on the
GitHub Releases page. It is not a bootable SD-card image and does not include
Raspberry Pi OS, desktop packages, credentials, production configuration, or an
external-system connector.

## Supported deployment baseline

- 64-bit Raspberry Pi OS on an AArch64 Raspberry Pi;
- Raspberry Pi 5 is the validated production target;
- a graphical desktop/compositor session because Tk needs a display server;
- 7-inch, 10.1-inch, or another commissioned touch display;
- at least 2 GB free during installation/acceptance testing;
- network and audio are optional for local-only reporting, but connector features
  require authorized HTTPS access and sounds require a working output device.

A native executable can depend on the operating-system ABI used by its build host.
Prefer the OS generation named in the GitHub Release notes. If the binary does not
start on an older image, update the supported OS or build from source on that target.

## 1. Download the release

Open the repository's **Releases** area and select the required version. For version
1.0.0, download both the Linux ARM64 archive and its separately published archive
digest/signature when available. Do not download source-code archives when you need
the ready-to-run executable.

Recommended asset names:

```text
floorterminal-v1.0.0-linux-arm64.tar.gz
floorterminal-v1.0.0-linux-arm64.tar.gz.sha256
```

Transfer the files to the Pi with a browser, managed deployment system, removable
media, or `scp`. Example from another computer:

```bash
scp floorterminal-v1.0.0-linux-arm64* pi@PI_ADDRESS:~/Downloads/
```

## 2. Verify before extraction

If an archive digest is supplied:

```bash
cd ~/Downloads
sha256sum -c floorterminal-v1.0.0-linux-arm64.tar.gz.sha256
```

Compare the displayed digest with the value shown on the trusted GitHub Release over
HTTPS. A mismatch means stop: delete the file and investigate the download/source.

Extract the versioned top-level directory:

```bash
cd ~/Downloads
tar -xzf floorterminal-v1.0.0-linux-arm64.tar.gz
cd floorterminal-v1.0.0-linux-arm64
```

The bundle's own manifest protects every delivered file:

```bash
sha256sum -c SHA256SUMS
```

Every row must report `OK`. Confirm the executable target:

```bash
file floorterminal
```

Expected: `ELF 64-bit ... ARM aarch64`.

## 3. Review the delivered bundle

The release contains only:

```text
DEPLOYMENT.txt
LICENSE
SBOM.spdx.json
SHA256SUMS
SOFTWARE_INFORMATION_AND_NOTICES.txt
VERSION
config.json
connector.json
floorterminal-icon.png
install.sh
floorterminal.desktop
floorterminal
floorterminal.service
floorterminal-launch
```

Read `DEPLOYMENT.txt`, `SOFTWARE_INFORMATION_AND_NOTICES.txt`, and `LICENSE`. The
neutral `connector.json` is disabled and contains no credentials. Logs, saved state,
Python source, build caches, customer data, and private deployment passwords are not
distributed. `floorterminal-icon.png` is the original project launcher artwork; it
contains no deployment data.

## 4. Prepare Raspberry Pi OS

```bash
sudo apt update
sudo apt install -y ca-certificates alsa-utils
```

Use a normal graphical kiosk user, not root. Confirm the date/time and timezone,
display rotation, touch calibration, network segmentation, and audio output before
commissioning. The application is not intended to run on a console-only OS without a
display server.

## 5. Install

```bash
chmod +x install.sh floorterminal-launch floorterminal
./install.sh
```

The installer verifies `SHA256SUMS`, prompts for `sudo` only for protected system
locations, installs under `/opt/floorterminal`, enables a hardened per-user
systemd supervisor, and creates graphical-session autostart. It preserves existing
`config.json` and `connector.json` during later upgrades.

The executable is installed into `versions/<version>/` and the running version is
selected by one symbolic link at the deployment root. `bin/floorterminal-launch` is the
supervised launcher: it performs the update boot-watchdog check and then hands over
to the active version. An installation made by an earlier release keeps working and
is migrated the first time this installer runs; the previous executable is preserved
under `update/replaced-executable-<timestamp>` as evidence.

Reboot into the graphical session:

```bash
sudo reboot
```

The console should occupy the available screen without exposing normal desktop
interaction. Closing the window or an unexpected process exit causes the supervisor
to restart it. Authorized maintenance actions still require operating-system and/or
Settings administrator authorization.

## 6. First configuration

The standard release initial password is **`admin@123`**. It is public so a new
installation can be configured without contacting the distributor. A custom build
may have a different initial password supplied by its distributor.

Before production, open Settings, enter your administrator name/ID and the initial
password, then choose **System → Change Settings password**. Enter the current
password, choose a new one, and confirm it using the touch keyboard or a physical
keyboard. The change is saved immediately, independently of other unsaved Settings
edits. Existing local passwords survive installation upgrades and signed updates.
The original password is **not** a recovery/master override. See
[Settings access and recovery](settings-access.md).

Open protected Settings and configure:

1. line name and station order;
2. one to four custom failure choices for every station (`Others` is automatic);
3. escalation and micro-stop timing;
4. Engineering/Quality/Production destination labels;
5. appearance, accessibility, sound, retention, and storage safeguards;
6. external connector selection only when required.

Without an enabled connector, station selection, failure capture, local state,
timers, logs, Settings, and the touchscreen remain available. External response records,
directory lookup, messages, assignments, and asset status become available only when
their independent Connector v1 capabilities validate successfully.

For a managed connector deployment, place the reviewed owner-private file at:

```text
/opt/floorterminal/connector.json
```

Then enforce ownership/mode and restart:

```bash
sudo chown "$USER:$USER" /opt/floorterminal/connector.json
chmod 600 /opt/floorterminal/connector.json
systemctl --user restart floorterminal.service
```

Never paste secrets into GitHub issues, screenshots, build records, or public logs.
Read the [Connector v1 contract](connector.md) before enabling remote operations.

## 7. Verify operation

```bash
systemctl --user status floorterminal.service --no-pager
journalctl --user -u floorterminal.service -n 100 --no-pager
```

Runtime files live under `/opt/floorterminal` and activity logs use:

```text
/opt/floorterminal/logs/YYYY/MM/DD/activity.jsonl
```

Complete the [industrial deployment and acceptance guide](industrial-deployment.md):
exercise every screen state, restart recovery, offline queue, connector capability,
idempotency, touch target, display mode, sound cue, authorized exit, and production
restoration path in a controlled environment before live use.

## Upgrade and rollback

The supported route for a terminal already in service is the offline update drive:
download the update-drive archive, extract it onto a USB drive labelled
`FLOORTERM`, plug it in, and authorize the change on the touchscreen. The terminal
verifies the maintainer signature and the executable checksum itself, keeps the
previous version installed for one-touch rollback, and restores it automatically if
a newly activated version cannot start. Configuration, connector, state, and logs
are never touched. Follow the [update guide](update-user-guide.md).

Reinstalling from a full release bundle remains available, for example to migrate an
older flat installation or to rebuild a terminal:

1. Back up approved runtime configuration, connector, state, and required audit logs.
2. Download and verify the new release independently.
3. Stop the user service: `systemctl --user stop floorterminal.service`.
4. Run the new `install.sh`; existing config/connector files are preserved.
5. Reboot or restart the service and repeat acceptance tests.

Do not restore an old executable over newer persisted state unless the release notes
explicitly declare backward compatibility. For a rollback outside the managed version
slots, restore the complete tested backup as one controlled unit.

## Troubleshooting

- **`Is a directory`:** enter a folder with `cd ~/folder`; do not type its path as a
  command.
- **Permission denied:** run `chmod +x install.sh floorterminal` and verify
  the archive was extracted on a Linux filesystem.
- **Wrong architecture/Exec format:** download Linux ARM64 or build on the target Pi.
- **No window:** confirm a graphical session and `DISPLAY`/Wayland compositor exist;
  inspect the user-service journal.
- **Desktop appears:** confirm the desktop entry and user service are installed for
  the graphical-login user, then reboot.
- **No sound:** see [sound commissioning](sound.md); visual status remains authoritative.
- **Connector unavailable:** review protected Settings validation and test only the
  declared safe diagnostic; local reporting continues.
- **Update indicator is red:** usually the terminal has no route to the internet,
  which is normal on a segmented plant network. USB updates are unaffected. See the
  [update guide](update-user-guide.md).
- **Update drive not detected:** confirm the volume label is `FLOORTERM`, that the
  `floorterminal-update` folder sits at the drive root, and that the desktop
  session mounted the drive. **Scan USB drive** in the update panel checks every
  removable mount regardless of label.

For setup or integration help, contact **Soham Patel** at
[sohampatel1782@gmail.com](mailto:sohampatel1782@gmail.com) or open a non-sensitive
GitHub issue. Support is best-effort under the MIT License.
