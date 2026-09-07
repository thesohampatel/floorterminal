#!/usr/bin/env python3
"""Source launcher for the production application."""

from __future__ import annotations

import sys
from pathlib import Path


def load_main():
    """Load the source package without depending on the caller's directory."""
    source_dir = Path(__file__).resolve().parent / "src"
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
    from floorterminal.app import main

    return main


if __name__ == "__main__":
    load_main()()
