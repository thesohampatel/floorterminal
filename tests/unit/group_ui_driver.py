"""Real Tk multi-group touch flow and adaptive geometry, with sockets denied."""

import argparse
import json
import shutil
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from ui_smoke_driver import ROOT, capture_window, isolated_home


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    home = isolated_home()
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

    def denied(*_args, **_kwargs):
        raise AssertionError("No live connections in group GUI checks")

    socket.socket.connect = denied
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp
    from floorterminal.ui.settings import SettingsWindow
    from tests.unit.test_station_groups import GROUPS

    root = tk.Tk()
    root.overrideredirect(True)
    app = FloorTerminalApp(root)
    app.stop_update_service()
    app.config["station_groups"] = json.loads(json.dumps(GROUPS))
    app.config["reporting_mode"] = "local"
    app.config["zones"] = [s for g in GROUPS for s in g["stations"]]
    app.config["station_failure_types"] = {
        s: ["Mechanical", "Electrical", "Material", "Sensor"]
        for s in app.config["zones"]
    }
    app.reload_connector()
    root.geometry("800x480+0+0")
    faults, views = [], 0
    root.report_callback_exception = lambda _kind, value, _tb: faults.append(str(value))

    def settle():
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            root.update()
            if not app.busy:
                break
            time.sleep(0.003)
        assert not app.busy, "Local action stayed busy"
        assert not app.error_panel, app.error_panel
        assert not faults, faults
        app.render()

    def tap(key):
        settle()
        a, b, c, d = app.hitboxes[key]
        event = SimpleNamespace(
            x=(a + c) / 2 * app.canvas.scale_factor + app.canvas.offset_x,
            y=(b + d) / 2 * app.canvas.scale_factor + app.canvas.offset_y,
        )
        app.on_press(event)
        app.on_release(event)
        settle()

    def geometry_check():
        nonlocal views
        views += 1
        w, h = app.canvas.logical_width, app.canvas.logical_height
        for key, (a, b, c, d) in app.hitboxes.items():
            assert -0.1 <= a < c <= w + 0.1 and -0.1 <= b < d <= h + 0.1, (
                key,
                (a, b, c, d),
                (w, h),
            )
            assert c - a >= 43.5 and d - b >= 43.5, (key, "touch target too small")
        boxes = list(app.hitboxes.items())
        for i, (key, one) in enumerate(boxes):
            for other, two in boxes[i + 1 :]:
                assert (
                    min(one[2], two[2]) - max(one[0], two[0]) < 0.5
                    or min(one[3], two[3]) - max(one[1], two[1]) < 0.5
                ), (key, other, "overlap")

    def capture(name, width, height):
        if args.capture:
            args.capture.mkdir(parents=True, exist_ok=True)
            app.touch_feedback = None
            app.render()
            root.update_idletasks()
            assert (root.winfo_width(), root.winfo_height()) == (width, height)
            capture_window(root, args.capture / (name + ".png"))

    try:
        settle()
        tap("zone_0")
        tap("failure_done")
        tap("primary")
        tap("operator_self_fix")
        first = app.state["incident_id"]
        tap("ui_groups")
        tap("ui_group_pick_1")
        tap("confirm")
        assert len(app.state["parked_incidents"]) == 1
        assert app.state["status"] == "DOWN"
        assert len(app.station_statuses()) == 4
        for width, height in (
            (320, 400),
            (480, 800),
            (800, 480),
            (1024, 600),
            (1920, 1080),
            (2560, 720),
        ):
            root.geometry(f"{width}x{height}+0+0")
            settle()
            geometry_check()
            if width in {480, 800, 1920}:
                capture(f"groups-{width}x{height}", width, height)
            tap("ui_groups")
            geometry_check()
            tap("ui_group_whole")
            assert "Finish open group" in app.modal["group_notice"]
            geometry_check()
            if width == 800:
                capture("group-overview", width, height)
            tap("cancel")
        root.geometry("800x480+0+0")
        settle()
        tap("ui_groups")
        tap("ui_group_pick_0")
        assert app.state["incident_id"] == first
        tap("primary")
        tap("confirm")
        assert app.station_statuses() == {"Station 3": "DOWN", "Station 4": "DOWN"}
        tap("ui_groups")
        tap("ui_group_pick_1")
        tap("primary")
        assert app.state["status"] == "REPAIRING"
        tap("primary")
        tap("confirm")
        assert not app.station_statuses()
        assert app.state["delivery_outbox"] == []
        tap("ui_groups")
        tap("ui_group_search")
        for char in "Packing":
            app.on_keypress(SimpleNamespace(keysym=char, char=char))
        app.on_keypress(SimpleNamespace(keysym="Return", char=""))
        settle()
        assert "ui_group_pick_2" in app.hitboxes
        assert "ui_group_pick_0" not in app.hitboxes
        tap("ui_group_pick_2")
        assert app.modal["kind"] == "confirm_downtime"
        assert app.state["status"] == "RUNNING"
        tap("cancel")
        settings = SettingsWindow(app, {})
        settings.tabs.select(2)
        root.update()
        settings.group_name.set("Assembly")
        settings.group_scope.set(settings.t("group_only"))
        settings._store_station()
        assert settings.configured_groups()[0]["stop_scope"] == "group"
        # Group inputs remain within the paged content and survive resize.
        for size in ("800x480", "480x800", "1920x1080"):
            root.geometry(size + "+0+0")
            root.update()
            assert settings.group_name.get() == "Assembly"
        root.geometry("800x480+0+0")
        for _ in range(8):
            root.update()
        assert settings.group_entry.winfo_width() >= 350, (
            "Station list crowded out the group editor after HD resize"
        )
        for canvas, body in settings._scroll_areas:
            if canvas.winfo_viewable():
                top = settings.group_entry.winfo_rooty() - body.winfo_rooty() - 34
                canvas.yview_moveto(max(0, top / body.winfo_height()))
        root.update()
        capture("group-settings", 800, 480)
        # Exercise the actual save path, including the visible validation error,
        # group-wide propagation, serialization and normal config loading.
        settings.group_name.set("")
        settle()
        settings.save()
        assert "group name" in settings.error.get(), settings.error.get()
        settings.group_name.set("Assembly")
        settings.group_scope.set(settings.t("group_whole_line"))
        settle()
        settings.save()
        assert not settings.win.winfo_exists(), settings.error.get()
        from floorterminal.core.config import CONFIG_FILE, load_config

        saved = json.loads(CONFIG_FILE.read_text())
        assert saved["station_groups"][0]["stop_scope"] == "line"
        assert saved["station_groups"][0]["stations"] == ["Station 1", "Station 2"]
        assert load_config()["station_groups"] == saved["station_groups"]
        print(
            json.dumps(
                {
                    "views": views,
                    "incidents": 2,
                    "callback_faults": faults,
                    "live_connections": 0,
                }
            )
        )
    finally:
        app.history.close(2)
        app.delivery.close()
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
