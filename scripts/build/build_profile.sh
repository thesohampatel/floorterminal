#!/usr/bin/env sh
set -eu
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /absolute/or/relative/path/to/deployment-profile.json" >&2
  exit 2
fi
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROFILE_DIR=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
PROFILE="$PROFILE_DIR/$(basename -- "$1")"
[ -f "$PROFILE" ] || { echo "Deployment profile not found: $PROFILE" >&2; exit 2; }
export FLOORTERMINAL_PROJECT_PROFILE_FILE="$PROFILE"
exec "$SCRIPT_DIR/build.sh"
