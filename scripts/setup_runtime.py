#!/usr/bin/env python3
"""Create private runtime files from tracked, credential-free examples."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ("config.example.json", "config.json"),
    ("connector.example.json", "connector.json"),
    ("project_profile.example.json", "project_profile.json"),
)


def main():
    for source_name, target_name in FILES:
        source = ROOT / source_name
        target = ROOT / target_name
        if target.exists():
            print(f"Preserved {target_name}")
            continue
        if not source.is_file():
            raise SystemExit(f"Missing tracked template: {source_name}")
        with source.open("rb") as input_stream, target.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream)
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print(f"Created private {target_name}")


if __name__ == "__main__":
    main()
