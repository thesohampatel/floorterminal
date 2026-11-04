"""Capture a versioned release gallery with disposable, network-disabled fixtures.

Run on an isolated Pi graphical session; never over an operator's live kiosk.
Pillow is a documentation-only dependency. No installed runtime or key is read.
The two conveyor clips use fixed animation steps: they illustrate the renderer,
not a device frame-rate benchmark. Runtime code is never modified by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]


def motion(output):
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]
    from PIL import Image

    from scripts.docs.capture_images import (
        StaticUpdateService,
        _prepare_runtime,
        _snapshots,
    )

    home = _prepare_runtime()
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp
    from floorterminal.core.topology import scope_for
    from scripts.docs.screen_capture import capture_widget
    from tests.unit.test_station_groups import GROUPS

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("1600x960+0+0")
    app = FloorTerminalApp(root)
    app.stop_update_service()
    app.update_service = StaticUpdateService(_snapshots()["current"])
    root.geometry("1600x960+0+0")
    root.update()
    for callback in root.tk.call("after", "info"):
        root.after_cancel(callback)
    app._animation_after = app._render_after = None
    app.toast_until = 0
    try:
        for grouped, filename in (
            (False, "conveyor-motion.webp"),
            (True, "group-motion.webp"),
        ):
            if grouped:
                app.config["station_groups"] = json.loads(json.dumps(GROUPS))
                app.state["parked_incidents"] = {
                    f"example-{i}": {
                        "status": status,
                        "incident_scope": scope_for(app.config, [group["stations"][0]]),
                        "incident_id": f"example-{i}",
                    }
                    for i, (group, status) in enumerate(
                        zip(GROUPS, ("DOWN", "REPAIRING"))
                    )
                }
            app._belt_clocks = {}
            frames = []
            for index in range(72):
                app.animation_start = time.monotonic() - index / 24
                app.render()
                root.update_idletasks()
                time.sleep(0.04)
                assert not app.error_panel and not app.render_blocked
                shot = capture_widget(app.canvas)
                assert shot.size == (1600, 960)
                if grouped and index == 12:
                    shot.save(output / "group-console.png", optimize=True)
                frames.append(shot.resize((1200, 720), Image.Resampling.LANCZOS))
            assert (
                len({hashlib.sha256(frame.tobytes()).hexdigest() for frame in frames})
                > 24
            )
            frames[0].save(
                output / filename,
                save_all=True,
                append_images=frames[1:],
                duration=[42, 42, 41] * 24,
                loop=0,
                lossless=True,
                method=4,
            )
    finally:
        app.update_service.stop()
        app.delivery.close()
        app.sound.close()
        app.history.close(2)
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--logs", type=Path)
    parser.add_argument("--motion-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--manifest-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.motion_only:
        motion(output)
        return
    if args.manifest_only:
        manifest(output)
        return
    if any(output.iterdir()):
        raise SystemExit(
            "Choose an empty output folder; existing media will not be overwritten."
        )
    logs = (
        args.logs.resolve()
        if args.logs
        else Path(tempfile.mkdtemp(prefix="floorterminal-media-logs-"))
    )
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        FLOORTERMINAL_DISABLE_NETWORK="1",
        FLOORTERMINAL_DISABLE_UPDATE_NETWORK="1",
    )
    commands = [
        ("primary", ["scripts/docs/capture_images.py", "--output", str(output)])
    ]
    for folder, driver in (
        ("groups", "group_ui_driver"),
        ("self-fix", "operator_ui_driver"),
        ("layout", "adaptive_ui_driver"),
        ("touch", "touch_budget_driver"),
        ("team", "roster_ui_driver"),
        ("failures", "variable_failure_ui_driver"),
        ("delivery", "delivery_ui_driver"),
        ("controls", "experience_ui_driver"),
    ):
        commands.append(
            (folder, [f"tests/unit/{driver}.py", "--capture", str(output / folder)])
        )
    commands.extend(
        [
            (
                "panel",
                [
                    "tests/unit/panel_ui_driver.py",
                    "--seconds",
                    "2",
                    "--capture",
                    str(output / "panel"),
                ],
            ),
            (
                "render",
                [
                    "tests/unit/render_stress_driver.py",
                    "--groups",
                    "--frames",
                    "30",
                    "--sizes",
                    "1600x960",
                    "1920x1200",
                    "--screenshots",
                    str(output / "render"),
                ],
            ),
            (
                "motion",
                [
                    str(Path(__file__).resolve()),
                    "--motion-only",
                    "--output",
                    str(output),
                ],
            ),
        ]
    )
    for name, command in commands:
        print(f"Capturing {name}…", flush=True)
        with (logs / (name + ".log")).open("w") as log:
            result = subprocess.run(
                [sys.executable, *command],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
        if result.returncode:
            raise SystemExit(
                f"Capture failed: {name}; inspect private log {logs / (name + '.log')}"
            )
    count = manifest(output)
    print(
        f"Verified {count} media assets. Logs remain outside the gallery: {logs}",
        flush=True,
    )


def manifest(output):
    from PIL import Image

    records = []
    for path in sorted(output.rglob("*")):
        if path.suffix not in {".png", ".webp", ".gif"}:
            continue
        with Image.open(path) as image:
            records.append(
                {
                    "file": path.relative_to(output).as_posix(),
                    "width": image.width,
                    "height": image.height,
                    "frames": getattr(image, "n_frames", 1),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    sys.path.insert(0, str(ROOT))
    from scripts.build.build import source_input_manifest

    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    provenance = {
        "application_version": version,
        "source_ref": "v" + version,
        "source_inputs_sha256": source_input_manifest()["sha256"],
        "captured_date": datetime.now(ZoneInfo("America/Toronto")).date().isoformat(),
        "capture_timezone": "America/Toronto",
        "platform": "Raspberry Pi 5 / 64-bit Raspberry Pi OS / Tk 8.6",
        "data": "Disposable neutral offline fixtures; no live integration calls",
        "motion": "72 real-renderer frames at fixed 24 fps steps, reduced from 1600x960 to 1200x720; not a performance measurement",
        "images": records,
    }
    (output / "manifest.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return len(records)


if __name__ == "__main__":
    main()
