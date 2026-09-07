#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Homebrew installations on Apple Silicon can coexist with an older Intel
# Python earlier in PATH. Select a native interpreter that can import the real
# Tk extension so PyInstaller cannot silently create a non-opening GUI bundle.
if [ "$(uname -s)" = "Darwin" ]; then
    native_arch=$(uname -m)
    for candidate in /opt/homebrew/bin/python3 python3 /usr/local/bin/python3 /usr/bin/python3; do
        if command -v "$candidate" >/dev/null 2>&1 && \
           "$candidate" -c 'import _tkinter, platform, sys; sys.exit(0 if platform.machine() == sys.argv[1] else 1)' "$native_arch" >/dev/null 2>&1; then
            exec "$candidate" "$SCRIPT_DIR/build.py"
        fi
    done
    printf '%s\n' "ERROR: No native macOS Python with Tkinter was found." >&2
    printf '%s\n' "Install it with: brew install python python-tk" >&2
    exit 1
fi

exec python3 "$SCRIPT_DIR/build.py"
