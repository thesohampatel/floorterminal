"""Offline real-Tk touch/clock/keyboard checks; never uses deployment files."""

import argparse
import itertools
import json
import re
import shutil
import socket
import string
import sys
import time
from types import SimpleNamespace

from ui_smoke_driver import ROOT, capture_window, isolated_home


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture")
    args = parser.parse_args()
    home = isolated_home()
    sys.path.insert(0, str(ROOT / "src"))

    def denied(*_args, **_kwargs):
        raise AssertionError("Network forbidden in refinement verification")

    socket.socket.connect = denied
    import tkinter as tk
    from pathlib import Path

    from floorterminal.app import FloorTerminalApp
    from floorterminal.ui.layout import header_regions

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

    def render():
        app.render()
        settle()
        w, h = app.canvas.logical_width, app.canvas.logical_height
        for key, (a, b, c, d) in app.hitboxes.items():
            assert 0 <= a < c <= w + 0.1 and 0 <= b < d <= h + 0.1, (key, (a, b, c, d))
            assert c - a >= 43.9 and d - b >= 43.9, (key, c - a, d - b)
        for one, two in itertools.combinations(app.hitboxes.values(), 2):
            assert (
                min(one[2], two[2]) - max(one[0], two[0]) < 0.1
                or min(one[3], two[3]) - max(one[1], two[1]) < 0.1
            )

    def tap(key):
        a, b, c, d = app.hitboxes[key]
        event = SimpleNamespace(
            x=(a + c) / 2 * app.canvas.scale_factor + app.canvas.offset_x,
            y=(b + d) / 2 * app.canvas.scale_factor + app.canvas.offset_y,
        )
        app.on_press(event)
        app.on_release(event)
        render()

    def capture(name):
        if args.capture:
            app.touch_feedback = None
            app._released_control = None
            app._page_transition_until = 0
            app.render()
            output = Path(args.capture)
            output.mkdir(parents=True, exist_ok=True)
            capture_window(root, output / name)

    try:
        settle()
        app.stop_update_service()
        app.delivery.close()
        app.history.close(2)
        root.attributes("-fullscreen", False)
        cases = 0
        for width, height in ((320, 400), (800, 480), (480, 800), (1920, 1200)):
            root.geometry(f"{width}x{height}+0+0")
            app.modal = None
            app.config["line_name"] = (
                "Demonstration production line • long name for layout"
            )
            settle()
            render()
            clock_items = [
                item
                for item in app.canvas.find_all()
                if app.canvas.type(item) == "text"
                and re.fullmatch(
                    r"\d{2}:\d{2}:\d{2}", app.canvas.itemcget(item, "text")
                )
            ]
            assert clock_items
            clock = header_regions(app.viewport().width)[1]
            bounds = app.canvas.bbox(clock_items[0])
            assert bounds
            scale = app.canvas.scale_factor
            assert (
                bounds[0] >= clock[0] * scale - 1 and bounds[2] <= clock[2] * scale + 1
            ), (bounds, clock)
            capture(f"main-{width}x{height}.png")
            app.modal = {
                "kind": "password",
                "stage": "password",
                "value": "",
                "shift": True,
            }
            render()
            capture(f"keyboard-{width}x{height}.png")
            seen = set()
            for symbols in (False, True):
                if symbols:
                    tap("pwd_symbols")
                pages = app.modal["keys_pages"]
                for page in range(pages):
                    app.modal["keys_page"] = page
                    render()
                    for key in list(app.hitboxes):
                        if key.startswith("pwd_") and key[4:].isdigit():
                            char = chr(int(key[4:]))
                            tap(key)
                            assert app.modal["value"].endswith(char)
                            seen.add(char)
                if symbols:
                    capture(f"symbols-{width}x{height}.png")
            assert seen == set(
                string.ascii_uppercase + string.digits + string.punctuation
            )
            tap("pwd_symbols")
            tap("pwd_shift")
            app.modal["keys_page"] = 0
            render()
            assert not app.modal["shift"]
            before = app.modal["value"]
            tap("pwd_back")
            assert app.modal["value"] == before[:-1]
            for count in (0, 4, 6, 19, 101):
                app.config["station_failure_types"]["Station 1"] = [
                    f"Reason {i + 1}" for i in range(count)
                ]
                app.open_failure_selection("Station 1")
                render()
                rectangles = [
                    box
                    for key, box in app.hitboxes.items()
                    if key.startswith("failure_") and key[8:].isdigit()
                ]
                assert (
                    len(
                        {
                            (round(c - a, 2), round(d - b, 2))
                            for a, b, c, d in rectangles
                        }
                    )
                    == 1
                )
                if count == 6:
                    capture(f"failure-grid-{width}x{height}.png")
                tap("failure_all")
                assert len(app.modal["selected"]) == count + 1
                tap("failure_clear")
                assert not app.modal["selected"]
            app.modal = {"kind": "about"}
            for tab in ("overview", "license", "safety"):
                render()
                tap("ui_about_" + tab)
                capture(f"about-{tab}-{width}x{height}.png")
            app.modal = {"kind": "update", "page": "status"}
            render()
            capture(f"update-{width}x{height}.png")
            cases += 1
        from floorterminal.ui.settings import SettingsWindow

        app.modal = None
        settings = SettingsWindow(
            app, {"teams": [], "conversations": ["Maintenance help", "Inspector"]}
        )
        settle()
        expected = []
        for index, label in enumerate(
            ("Maintenance team", "Quality technician", "Production supervisor")
        ):
            destination = ("Maintenance help", "Inspector", "Supervisor")[index]
            settings.vars[f"integration_support_{index}_label"].set(label)
            settings.vars[f"integration_support_{index}_destination"].set(destination)
            settings.support_enabled[index].set(index != 2)
            expected.append(
                {"enabled": index != 2, "label": label, "destination": destination}
            )
        settings.save()
        settle()
        assert app.config["support_buttons"] == expected
        assert (
            json.loads((home / "config.json").read_text())["support_buttons"]
            == expected
        )
        app.provider.INFO = SimpleNamespace(
            **{**vars(app.provider.INFO), "supports_messaging": True}
        )
        app.toast_until = 0
        app.call_team = lambda name: dispatched.append(name)
        dispatched = []
        render()
        assert "engineering" in app.hitboxes and "quality" in app.hitboxes
        assert "production" not in app.hitboxes
        tap("engineering")
        assert dispatched == ["Engineering"]
        capture("custom-support-1920x1200.png")
        for item in app.config["support_buttons"]:
            item["enabled"] = False
        render()
        assert not set(app.hitboxes).intersection(
            {"engineering", "quality", "production", "ui_support"}
        )
        print(
            json.dumps(
                {
                    "sizes": cases,
                    "faults": faults,
                    "network_calls": 0,
                    "keyboard_characters_per_size": 68,
                    "support_settings_saved": True,
                }
            )
        )
    finally:
        app._closing = True
        app.stop_update_service()
        app.delivery.close()
        app.history.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
