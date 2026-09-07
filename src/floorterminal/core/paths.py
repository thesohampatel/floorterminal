"""Cross-platform source and frozen-application filesystem locations."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _runtime_root() -> Path:
    override = os.environ.get("FLOORTERMINAL_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[3]
    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix.lower() == ".app":
            return parent.parent
    # Direct launches must use the same data root as the supervised launcher.
    # Resolving the active symlink places sys.executable inside a version slot.
    if executable.parent.parent.name == "versions":
        return executable.parent.parent.parent
    return executable.parent


RUNTIME_ROOT = _runtime_root()
