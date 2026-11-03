"""Offline real-Tk frame/resource benchmark; run on an isolated display.

No runtime files, credentials or remote services are used. Synthetic elapsed time
exercises days-old animation phases; it is not a substitute for a physical soak.
Screenshots require optional Pillow, not an application dependency.
"""

import argparse
import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path

from ui_smoke_driver import ROOT, capture_window, isolated_home


def rss_kib():
    path = Path("/proc/self/status")
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=2000)
    parser.add_argument(
        "--sizes", nargs="+", default=["800x480", "1280x800", "1920x1080"]
    )
    parser.add_argument("--legacy-redraw", action="store_true")
    parser.add_argument("--dialog", choices=("about", "failures", "engineers"))
    parser.add_argument(
        "--groups",
        action="store_true",
        help="Render independent stopped, responding and running groups",
    )
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    home = isolated_home()
    sys.path.insert(0, str(ROOT / "src"))
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp
    from floorterminal.integration.runtime import UrllibTransport

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Network access is forbidden in this offline driver")

    UrllibTransport.send = forbidden
    os.environ["FLOORTERMINAL_DISABLE_UPDATE_NETWORK"] = "1"
    root = tk.Tk()
    root.overrideredirect(True)
    app = FloorTerminalApp(root, None)
    root.update()
    app.stop_update_service()
    if args.groups:
        from floorterminal.core.topology import scope_for

        zones = app.config["zones"]
        app.config["station_groups"] = [
            {
                "id": f"cell-{i}",
                "name": f"Cell {i + 1}",
                "stations": zones[i * 2 : (i + 1) * 2],
                "stop_scope": "group",
            }
            for i in range(len(zones) // 2)
        ]
        # Rendering-only scene; no workflow writes, connections or timers.
        app.state["parked_incidents"] = {
            f"scene-{i}": {
                "status": status,
                "incident_scope": scope_for(app.config, [zones[i * 2]]),
                "incident_id": f"scene-{i}",
            }
            for i, status in enumerate(("DOWN", "REPAIRING"))
        }
    for callback in root.tk.call("after", "info"):
        root.after_cancel(callback)
    app._animation_after = app._render_after = None
    app.toast_until = 0
    if args.dialog:
        from ui_smoke_driver import copy_dialog, dialogs

        app.modal = copy_dialog(
            next(d for d in dialogs() if d and d.get("kind") == args.dialog)
        )
    if args.legacy_redraw:
        app.canvas.begin_frame = lambda: app.canvas.delete("all")
        app.canvas.end_frame = lambda: None
    results = []
    try:
        for size in args.sizes:
            root.geometry(size + "+0+0")
            root.update()
            timings = []
            start_cpu = time.process_time()
            first_rss = None
            retained_ids, recreated_items = set(), 0
            for frame in range(args.frames + 200):
                # Continuous motion after 180 days, with 200 warm-up frames.
                app.animation_start = time.monotonic() - 180 * 86400 - frame / 30
                before = time.perf_counter()
                app.render()
                root.update_idletasks()
                duration = (time.perf_counter() - before) * 1000
                if frame == 199:
                    first_rss = rss_kib()
                    start_cpu = time.process_time()
                    retained_ids = set(app.canvas.find_all())
                if frame >= 200:
                    timings.append(duration)
                    current_ids = set(app.canvas.find_all())
                    recreated_items += len(current_ids - retained_ids)
                    retained_ids = current_ids
            rss = rss_kib()
            result = {
                "size": size,
                "dialog": args.dialog,
                "frames": len(timings),
                "mean_ms": round(statistics.mean(timings), 3),
                "p95_ms": round(sorted(timings)[int(len(timings) * 0.95)], 3),
                "cpu_seconds": round(time.process_time() - start_cpu, 3),
                "items": len(app.canvas.find_all()),
                "recreated_items_after_warmup": recreated_items,
                "images": len(root.tk.call("image", "names")),
                "cached_decoded_bytes": app.canvas.raster.bytes_used,
                "rss_growth_kib": rss - first_rss if rss and first_rss else None,
            }
            results.append(result)
            print(json.dumps(result), flush=True)
            if args.screenshots:
                args.screenshots.mkdir(parents=True, exist_ok=True)

                def capture(name, size=size):
                    root.update()
                    capture_window(root, args.screenshots / f"{size}-{name}.png")

                capture("console")
                app.busy = True
                app.busy_message = "Recording downtime…"
                app.busy_started = time.monotonic() - 25
                app.render()
                capture("working")
                app.busy = False
                app.modal = None
                settings = app.open_settings()
                for index, name in enumerate(
                    (
                        "general",
                        "connector",
                        "stations",
                        "messages",
                        "system",
                        "appearance",
                    )
                ):
                    settings.tabs.select(index)
                    capture("settings-" + name)
                settings._create_connector_wizard()
                capture("connector-wizard")
                settings.win.destroy()
                app.render()
        return results
    finally:
        app.sound.close()
        app.history.close(2)
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home)


if __name__ == "__main__":
    main()
