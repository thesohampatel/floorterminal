#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
BUILD_SCRIPT="$PROJECT_DIR/scripts/build/build.py"
RELEASE_DIR=""

info() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

info "Checking build platform"
[[ "$(uname -s)" == "Linux" ]] || fail "Run this script on 64-bit Raspberry Pi OS."
case "$(uname -m)" in
  aarch64|arm64) ;;
  *) fail "64-bit ARM is required. Detected: $(uname -m)" ;;
esac

[[ -r /etc/os-release ]] || fail "Cannot identify the Linux operating system."
if ! grep -Eqi 'raspbian|raspberry pi|debian' /etc/os-release; then
  fail "Raspberry Pi OS or compatible Debian ARM64 is required."
fi

info "Checking project files"
for path in main.py config.example.json connector.example.json project_profile.example.json scripts/setup_runtime.py src/floorterminal scripts/build/build.py packaging/linux/floorterminal-launch; do
  [[ -e "$PROJECT_DIR/$path" ]] || fail "Missing required project item: $path"
done

available_kb="$(df -Pk "$PROJECT_DIR" | awk 'NR==2 {print $4}')"
[[ "$available_kb" =~ ^[0-9]+$ ]] || fail "Could not determine available storage."
(( available_kb >= 2097152 )) || fail "At least 2 GB of free build space is required."

info "Installing ARM64 build prerequisites"
command -v sudo >/dev/null || fail "sudo is required to install build packages."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  build-essential binutils ca-certificates file python3 python3-dev \
  python3-pip python3-tk zlib1g-dev alsa-utils xauth xvfb

command -v xvfb-run >/dev/null || fail "xvfb-run is required for the touchscreen release gate."

info "Validating Python, Tk, and production configuration"
cd "$PROJECT_DIR"
python3 scripts/setup_runtime.py
python3 - <<'PY'
import platform
import tkinter
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from floorterminal.core.config import load_config

config = load_config()
assert platform.machine().lower() in {"aarch64", "arm64"}
assert tkinter.TkVersion >= 8.6
assert len(config["zones"]) == len(config["station_failure_types"])
print(f"Python {platform.python_version()} • Tk {tkinter.TkVersion} • {len(config['zones'])} stations valid")
PY

info "Running touchscreen release gate and compiling source-free executable"
# SSH build sessions normally have no DISPLAY. A private virtual X server makes
# the real Tk smoke suite render every supported panel size instead of reporting
# six skips, while remaining completely offline and independent of the kiosk's
# active graphical session.
xvfb-run -a -s "-screen 0 1920x1200x24 -dpi 96 -nolisten tcp" python3 "$BUILD_SCRIPT"

info "Locating the recorded release output"
release_relative="$(python3 -c 'import json, pathlib; rows=pathlib.Path("BUILD_HISTORY.jsonl").read_text().splitlines(); print(json.loads(rows[-1])["release_directory"])')"
RELEASE_DIR="$PROJECT_DIR/$release_relative"
case "$RELEASE_DIR" in
  "$PROJECT_DIR"/dist/*) ;;
  *) fail "Builder returned an unsafe release path: $RELEASE_DIR" ;;
esac

info "Verifying release architecture and exact contents"
[[ -x "$RELEASE_DIR/floorterminal" ]] || fail "Compiled executable was not created."
file "$RELEASE_DIR/floorterminal" | grep -Eqi 'ELF 64-bit.*(ARM aarch64|ARM64)' \
  || fail "The generated executable is not Linux ARM64."

expected=$'DEPLOYMENT.txt\nLICENSE\nSBOM.spdx.json\nSHA256SUMS\nSOFTWARE_INFORMATION_AND_NOTICES.txt\nVERSION\nconfig.json\nconnector.json\nfloorterminal\nfloorterminal-icon.png\nfloorterminal-launch\nfloorterminal.desktop\nfloorterminal.service\ninstall.sh'
actual="$(find "$RELEASE_DIR" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort)"
[[ "$actual" == "$expected" ]] || {
  printf 'Expected files:\n%s\n\nActual files:\n%s\n' "$expected" "$actual" >&2
  fail "Release contains missing or unexpected files."
}

if find "$RELEASE_DIR" -mindepth 1 -type d -print -quit | grep -q .; then
  fail "Release contains an unexpected directory."
fi
if find "$RELEASE_DIR" -type f \( -name '*.py' -o -name '*.pyc' -o -name '*.spec' -o -name '*.jsonl' \) -print -quit | grep -q .; then
  fail "Release contains source, cache, build, or log files."
fi

(cd "$RELEASE_DIR" && sha256sum -c SHA256SUMS)

info "BUILD COMPLETE"
printf 'Source-free folder ready to review and transfer:\n%s\n' "$RELEASE_DIR"
printf '\nNo ZIP was created. Create your final ZIP from this folder when ready.\n'
