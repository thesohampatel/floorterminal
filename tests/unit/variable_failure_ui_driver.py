"""Real-Tk catalogue selection/editor checks, disposable data and blocked sockets."""

import argparse
import itertools
import json
import shutil
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from ui_smoke_driver import ROOT, capture_window, isolated_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    home = isolated_home()
    sys.path.insert(0, str(ROOT / "src"))

    def denied(*_args, **_kwargs):
        raise AssertionError("External network is forbidden")

    socket.socket.connect = denied
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp

    root = tk.Tk()
    app = FloorTerminalApp(root)
    faults = []
    root.report_callback_exception = lambda _kind, value, _tb: faults.append(str(value))

    def settle():
        for _ in range(5):
            root.update()
            time.sleep(0.005)
        assert not faults, faults
        assert not app.error_panel, app.error_panel

    def tap(key):
        a, b, c, d = app.hitboxes[key]
        event = SimpleNamespace(
            x=(a + c) / 2 * app.canvas.scale_factor + app.canvas.offset_x,
            y=(b + d) / 2 * app.canvas.scale_factor + app.canvas.offset_y,
        )
        app.on_press(event)
        app.on_release(event)
        app.render()
        settle()

    def check():
        w, h = app.canvas.logical_width, app.canvas.logical_height
        for a, b, c, d in app.hitboxes.values():
            assert a >= 0 and b >= 0 and c <= w + 0.1 and d <= h + 0.1
            assert c - a >= 43.9 and d - b >= 43.9
        for one, two in itertools.combinations(app.hitboxes.values(), 2):
            assert (
                min(one[2], two[2]) - max(one[0], two[0]) < 0.1
                or min(one[3], two[3]) - max(one[1], two[1]) < 0.1
            )

    try:
        settle()
        app.stop_update_service()
        app.delivery.close()
        app.history.close(2)
        root.attributes("-fullscreen", False)
        cases = 0
        for width, height in (
            (320, 400),
            (800, 480),
            (480, 800),
            (1280, 800),
            (1920, 1200),
        ):
            root.geometry(f"{width}x{height}+0+0")
            settle()
            for count in (0, 1, 4, 8, 53, 1000):
                reasons = [
                    f"Failure {i}: station-specific reason" for i in range(count)
                ]
                app.config["station_failure_types"]["Station 1"] = reasons
                app.state["issue_zones"] = ["Station 1"]
                app.open_failure_selection("Station 1")
                app.render()
                check()
                assert f"failure_{count}" in app.hitboxes  # Others always accessible.
                tap("failure_all")
                assert len(app.modal["selected"]) == count + 1
                tap("failure_clear")
                assert not app.modal["selected"]
                if app.modal["reason_pages"] > 1:
                    tap("failure_0")
                    tap("failure_next")
                    check()
                    assert reasons[0] in app.modal["selected"]
                    tap("failure_search")
                    app.modal["value"] = reasons[-1]
                    app.submit_text_input()
                    app.render()
                    assert f"failure_{count - 1}" in app.hitboxes
                    tap(f"failure_{count - 1}")
                    assert reasons[-1] in app.modal["selected"]
                    check()
                if args.capture and count == 53 and width in (800, 480):
                    args.capture.mkdir(parents=True, exist_ok=True)
                    app.open_failure_selection("Station 1")
                    until = time.monotonic() + 0.8
                    while time.monotonic() < until:
                        root.update()
                        time.sleep(0.02)
                    app.render()
                    capture_window(
                        root, args.capture / f"failure-reasons-{width}x{height}.png"
                    )
                cases += 1
        # A bounded editor must preserve reasons beyond the visible four rows.
        app.modal = None
        app.config["station_failure_types"]["Station 1"] = [
            f"Reason {i}" for i in range(101)
        ]
        root.geometry("800x480+0+0")
        settle()
        settings = app.open_settings()
        settings.tabs.select(2)
        settle()
        settings.change_failure_page(25)
        assert settings.failure_vars[0].get() == "Reason 100"
        settings.failure_vars[0].set("Edited last reason")
        settings._store_station()
        settings._refresh_station_list(1)
        settings._store_station()
        settings._refresh_station_list(0)
        assert settings.stations[0]["failures"][-1] == "Edited last reason"
        settings.add_failure()
        settings.failure_vars[1].set("Added reason")
        assert len(settings._collect_failures()) == 102
        settings.remove_failure(1)
        assert len(settings._collect_failures()) == 101
        settings._load_failures([])
        assert settings._collect_failures() == []
        before = (home / "config.json").read_bytes()
        old_status, old_started = app.state["status"], app.state.get("started_at")
        app.state.update(status="DOWN", started_at=time.time())
        settings.save()
        assert "Complete all group incidents" in settings.error.get(), settings.error.get()
        assert (home / "config.json").read_bytes() == before
        app.state.update(status=old_status, started_at=old_started)
        settings.win.destroy()
        print(
            json.dumps(
                {
                    "cases": cases,
                    "editor_preserved": True,
                    "active_edit_blocked": True,
                    "faults": faults,
                    "live_connections": 0,
                }
            )
        )
    finally:
        app.stop_update_service()
        app.delivery.close()
        app.history.close(2)
        app.sound.close()
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
