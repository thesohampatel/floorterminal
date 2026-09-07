#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
# The production location is fixed. The override exists so this installer can be
# exercised by the offline test suite and by staged deployment tooling; it is read
# from the environment of the administrator who is already running the script, so
# it grants no privilege that person does not already have.
TARGET_DIR="${FLOORTERMINAL_INSTALL_ROOT:-/opt/floorterminal}"
APP_NAME="floorterminal"

(cd "$SOURCE_DIR" && sha256sum -c SHA256SUMS)

if [[ -z "$TARGET_HOME" ]]; then
  echo "ERROR: Cannot determine home directory for $TARGET_USER" >&2
  exit 1
fi

VERSION="$(tr -d '[:space:]' < "$SOURCE_DIR/VERSION")"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]]; then
  echo "ERROR: VERSION does not contain a supported release identifier" >&2
  exit 1
fi
SLOT_DIR="$TARGET_DIR/versions/$VERSION"

# The deployment root holds configuration, connectors, state, and logs. Each
# release lives in its own immutable slot and the running version is selected by
# one symbolic link, so an update or a rollback replaces nothing but that link.
sudo install -d -m 700 -o "$TARGET_USER" -g "$TARGET_USER" \
  "$TARGET_DIR" "$TARGET_DIR/bin" "$TARGET_DIR/versions" "$SLOT_DIR" \
  "$TARGET_DIR/update" "$TARGET_DIR/update/staging"

sudo install -m 700 -o "$TARGET_USER" -g "$TARGET_USER" "$SOURCE_DIR/$APP_NAME" "$SLOT_DIR/$APP_NAME"
sudo install -m 700 -o "$TARGET_USER" -g "$TARGET_USER" "$SOURCE_DIR/floorterminal-launch" "$TARGET_DIR/bin/floorterminal-launch"
sudo install -m 644 -o "$TARGET_USER" -g "$TARGET_USER" "$SOURCE_DIR/floorterminal-icon.png" "$TARGET_DIR/floorterminal-icon.png"
for document in LICENSE SOFTWARE_INFORMATION_AND_NOTICES.txt SBOM.spdx.json VERSION; do
  sudo install -m 644 -o "$TARGET_USER" -g "$TARGET_USER" "$SOURCE_DIR/$document" "$SLOT_DIR/$document"
  sudo install -m 644 -o "$TARGET_USER" -g "$TARGET_USER" "$SOURCE_DIR/$document" "$TARGET_DIR/$document"
done

# An installation made by an earlier release put the executable directly at the
# deployment root. It is preserved as evidence, not deleted silently, and the
# root path becomes the managed link.
if [[ -f "$TARGET_DIR/$APP_NAME" && ! -L "$TARGET_DIR/$APP_NAME" ]]; then
  ARCHIVED="$TARGET_DIR/update/replaced-executable-$(date -u +%Y%m%dT%H%M%SZ)"
  sudo mv "$TARGET_DIR/$APP_NAME" "$ARCHIVED"
  sudo chown "$TARGET_USER:$TARGET_USER" "$ARCHIVED"
  echo "Preserved the previously installed executable at $ARCHIVED"
  echo "Its version is unknown, so it is not offered as a rollback target."
fi

# Switch the active version with a rename, which is atomic: an interruption
# leaves either the old slot or the new slot active, never a partial file.
sudo -u "$TARGET_USER" ln -sfn "versions/$VERSION/$APP_NAME" "$TARGET_DIR/.$APP_NAME.installing"
sudo -u "$TARGET_USER" mv -f "$TARGET_DIR/.$APP_NAME.installing" "$TARGET_DIR/$APP_NAME"

sudo -u "$TARGET_USER" tee "$TARGET_DIR/update/boot_state" >/dev/null <<STATE
SCHEMA=1
STATUS=confirmed
ACTIVE=$VERSION
PREVIOUS=
ATTEMPTS=0
LIMIT=3
UPDATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
STATE
sudo chmod 600 "$TARGET_DIR/update/boot_state"
sudo chown "$TARGET_USER:$TARGET_USER" "$TARGET_DIR/update/boot_state"

if [[ ! -e "$TARGET_DIR/config.json" ]]; then
  sudo install -m 600 -o "$TARGET_USER" -g "$TARGET_USER" "$SOURCE_DIR/config.json" "$TARGET_DIR/config.json"
else
  echo "Preserved existing config.json"
fi
if [[ ! -e "$TARGET_DIR/connector.json" ]]; then
  sudo install -m 600 -o "$TARGET_USER" -g "$TARGET_USER" "$SOURCE_DIR/connector.json" "$TARGET_DIR/connector.json"
else
  echo "Preserved existing connector.json"
fi

install -d -m 700 "$TARGET_HOME/.config/autostart"
install -m 644 "$SOURCE_DIR/floorterminal.desktop" "$TARGET_HOME/.config/autostart/floorterminal.desktop"
install -d -m 700 "$TARGET_HOME/.config/systemd/user/default.target.wants"
install -m 644 "$SOURCE_DIR/floorterminal.service" "$TARGET_HOME/.config/systemd/user/floorterminal.service"
ln -sfn ../floorterminal.service "$TARGET_HOME/.config/systemd/user/default.target.wants/floorterminal.service"
sudo chown -R "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart" "$TARGET_HOME/.config/systemd/user"

TARGET_UID="$(id -u "$TARGET_USER")"
if [[ -S "/run/user/$TARGET_UID/bus" ]]; then
  sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user daemon-reload
  sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user enable floorterminal.service
else
  echo "User service installed and enabled by symlink; it will load at the next graphical login."
fi

echo "Installed version $VERSION to $SLOT_DIR"
echo "Active version link: $TARGET_DIR/$APP_NAME"
echo "Open password-protected Settings to verify the deployment connector if required."
echo "Supervised kiosk autostart enabled for $TARGET_USER. The app restarts after crashes or unauthorized closure."
echo "Later versions install offline from a USB drive labelled FLOORTERM; see docs/update-user-guide.md."
echo "Reboot to launch fullscreen. For authorized maintenance, use: systemctl --user stop floorterminal.service"
