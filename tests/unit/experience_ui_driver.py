"""Offline lifecycle checks for asynchronous Settings and touch selectors."""

import argparse
import json
import shutil
import socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

from ui_smoke_driver import ROOT, capture_window, isolated_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    home = isolated_home()
    sys.path.insert(0, str(ROOT / "src"))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No network in Settings lifecycle checks")

    socket.socket.connect = forbidden
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp
    from floorterminal.ui.choices import TouchChoice
    from floorterminal.ui.settings import SettingsWindow
    from floorterminal.ui.touch_button import TouchButton

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("800x480+0+0")
    app = FloorTerminalApp(root)
    faults = []
    root.report_callback_exception = lambda _kind, value, _tb: faults.append(str(value))

    def pump(until=None, seconds=0.3):
        deadline = time.monotonic() + (10 if until else seconds)
        while time.monotonic() < deadline:
            root.update()
            if until and until():
                return
            time.sleep(0.002)
        assert until is None, "UI did not settle"

    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)

    try:
        pump(lambda: not app.busy)
        app.stop_update_service()
        before = dict(app.config)
        seen = []
        original = SettingsWindow._general_tab

        def checked(settings):
            assert settings.win.cover.winfo_ismapped()
            seen.append(True)
            original(settings)

        with patch.object(SettingsWindow, "_general_tab", checked):
            settings = app.open_settings(deferred=True)
            assert not settings._ready
            pump(lambda: settings._ready)
        pump()
        assert seen and not settings.win.cover.winfo_ismapped()
        settings.vars["line_name"].set("Unsaved fixture")
        for index in range(36):
            settings.tabs.select(index % 6)
            root.update()
        pump()
        assert settings.vars["line_name"].get() == "Unsaved fixture"
        assert settings.tabs._transition_after is None
        settings.tabs.select(0)
        pump()
        choice = next(
            w
            for w in descendants(settings.win)
            if isinstance(w, TouchChoice) and "local" in w.cget("values")
        )
        for size in ("800x480", "320x400", "1280x800"):
            root.geometry(size + "+0+0")
            pump()
            choice._open()
            pump()
            picker = choice.picker
            assert root.grab_current() is picker
            if args.capture and size == "800x480":
                args.capture.mkdir(parents=True, exist_ok=True)
                capture_window(root, args.capture / "settings-choice-800x480.png")
            for widget in descendants(picker):
                if isinstance(widget, TouchButton) and widget.winfo_viewable():
                    assert widget.winfo_height() >= 44
                    x, y = (
                        widget.winfo_rootx() - root.winfo_rootx(),
                        widget.winfo_rooty() - root.winfo_rooty(),
                    )
                    assert x >= 0 and y >= 0
                    assert x + widget.winfo_width() <= root.winfo_width()
                    assert y + widget.winfo_height() <= root.winfo_height()
            back = next(
                w
                for w in descendants(picker)
                if isinstance(w, TouchButton) and w.cget("text") == "Back"
            )
            back.invoke()
            pump()
            assert root.grab_current() is settings.win
        settings.win.destroy()
        assert app.config == before, "Cancel changed configuration"
        settings = app.open_settings(deferred=True)
        settings.win.destroy()
        pump()
        assert settings._build_after is None

        def failed(_settings):
            raise RuntimeError("Deliberate construction failure")

        with patch.object(SettingsWindow, "_general_tab", failed):
            settings = app.open_settings(deferred=True)
            pump(lambda: bool(app.error_panel))
        assert not settings.win.winfo_exists()
        app.dismiss_error_panel()
        pump()
        assert not faults, faults
        print(
            json.dumps(
                {
                    "callback_faults": faults,
                    "ready": True,
                    "cancel_preserved_config": True,
                    "failure_recovered": True,
                    "picker_sizes": 3,
                    "live_connections": 0,
                }
            )
        )
    finally:
        app.stop_update_service()
        app.delivery.close()
        app.sound.close()
        app.history.close(2)
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
