"""Opt-in fullscreen check on a real panel; never run against a live kiosk.

Uses disposable local-only data, disables sound/update checks and denies sockets.
This measures event-loop/render timings, not physical finger-to-display latency.
"""

import argparse
import faulthandler
import itertools
import json
import shutil
import socket
import sys
import time
from pathlib import Path

from ui_smoke_driver import ROOT, capture_window, copy_dialog, dialogs, isolated_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument(
        "--without-brand",
        action="store_true",
        help="Diagnostic: omit the static logo to isolate image readback",
    )
    parser.add_argument("--seconds", type=int, choices=range(2, 301), default=30)
    parser.add_argument(
        "--native-shapes",
        action="store_true",
        help="Diagnostic: use native canvas primitives without rounded PNG surfaces",
    )
    args = parser.parse_args()
    faulthandler.dump_traceback_later(45, repeat=True)
    home = isolated_home()
    config_file = home / "config.json"
    config = json.loads(config_file.read_text())
    config.update(
        line_name="Offline panel check",
        reporting_mode="local",
        fullscreen_on_linux=True,
    )
    config_file.write_text(json.dumps(config))
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Network access forbidden in panel check")

    socket.socket.connect = forbidden
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp

    if args.without_brand:
        FloorTerminalApp.draw_brand_mark = lambda *_args: False
    if args.native_shapes:
        from floorterminal.ui.responsive import ResponsiveCanvas

        original_init = ResponsiveCanvas.__init__

        def native_init(self, *values, **options):
            original_init(self, *values, **options)
            self.antialias = False

        ResponsiveCanvas.__init__ = native_init

    root = tk.Tk()
    faults = []
    root.report_callback_exception = lambda _kind, value, _tb: faults.append(str(value))
    app = FloorTerminalApp(root)

    def pump(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            root.update()
            time.sleep(0.002)
        assert not faults, faults
        assert not app.error_panel, app.error_panel

    def capture(name):
        if args.capture:
            args.capture.mkdir(parents=True, exist_ok=True)
            capture_window(root, args.capture / (name + ".png"))

    def measure(seconds):
        render = app.render
        frames, heartbeat = [], []

        def timed_render():
            start = time.perf_counter()
            try:
                return render()
            finally:
                frames.append((time.perf_counter() - start) * 1000)

        timer = None

        def beat():
            nonlocal timer
            heartbeat.append(time.monotonic())
            # Dump only if the real event loop stops responding, not simply
            # because a deliberately long soak lasts more than 45 seconds.
            faulthandler.dump_traceback_later(45, repeat=True)
            timer = root.after(20, beat)

        app.render = timed_render
        started, cpu = time.monotonic(), time.process_time()
        beat()
        stop = root.after(round(seconds * 1000), root.quit)
        try:
            root.mainloop()
        finally:
            root.after_cancel(timer)
            root.after_cancel(stop)
            app.render = render
        assert not faults, faults
        assert not app.error_panel, app.error_panel
        gaps = [(b - a) * 1000 for a, b in itertools.pairwise(heartbeat)]
        assert len(frames) > 0 and gaps and max(gaps) < 500, (len(frames), gaps[-10:])
        return {
            "seconds": round(time.monotonic() - started, 2),
            "frames": len(frames),
            "render_p95_ms": round(sorted(frames)[int(len(frames) * 0.95)], 2),
            "heartbeat_max_ms": round(max(gaps), 2),
            "process_cpu_percent": round(
                100 * (time.process_time() - cpu) / (time.monotonic() - started), 2
            ),
        }

    try:
        pump(2)
        app.stop_update_service()
        assert not app.busy, "Startup did not settle"
        assert root.attributes("-fullscreen")
        assert (root.winfo_width(), root.winfo_height()) == (
            root.winfo_screenwidth(),
            root.winfo_screenheight(),
        )
        main_stats = measure(args.seconds)
        assert app.modal is None, "The main-screen sample was interrupted by input"
        capture("native-main")
        for kind in ("about", "password"):
            app.modal = copy_dialog(
                next(d for d in dialogs() if d and d["kind"] == kind)
            )
            app.request_render()
            pump(0.5)
            capture("native-" + kind)
        static_stats = measure(2)
        for kind in ("engineers", "failures"):
            app.modal = copy_dialog(
                next(d for d in dialogs() if d and d["kind"] == kind)
            )
            app.request_render()
            pump(0.3)
            capture("native-" + kind)
        app.modal = None
        settings_beats = [time.monotonic()]
        settings_timer = None

        def settings_heartbeat():
            nonlocal settings_timer
            settings_beats.append(time.monotonic())
            settings_timer = root.after(20, settings_heartbeat)

        settings_heartbeat()
        settings_started = time.perf_counter()
        settings = app.open_settings(deferred=True)
        settings_first_feedback_ms = round(
            (time.perf_counter() - settings_started) * 1000, 2
        )
        while not settings._ready:
            assert time.monotonic() - settings_started < 10, (
                "Settings did not finish building"
            )
            assert settings.win.cover.winfo_ismapped(), (
                "Unfinished controls were exposed"
            )
            root.update()
            time.sleep(0.002)
        root.after_cancel(settings_timer)
        settings_gaps = [(b - a) * 1000 for a, b in itertools.pairwise(settings_beats)]
        settings_open_ms = round((time.perf_counter() - settings_started) * 1000, 2)
        assert settings.win._ready and not settings.win.cover.winfo_ismapped()
        try:
            for index, name in enumerate(
                ("general", "connector", "stations", "messages", "system", "colors")
            ):
                settings.tabs.select(index)
                pump(0.5)
                # Footer actions must remain mapped and outside page content.
                footer = settings.win.content.winfo_children()[1]
                assert footer.winfo_viewable()
                bottom = footer.winfo_rooty() + footer.winfo_height()
                assert bottom <= root.winfo_screenheight()
                assert (
                    settings.tabs.winfo_rooty() + settings.tabs.winfo_height()
                    <= footer.winfo_rooty()
                )
                for button in footer.winfo_children():
                    if not callable(getattr(button, "invoke", None)):
                        continue
                    assert button.winfo_viewable()
                    assert button.winfo_height() >= 44
                    x = button.winfo_rootx() + button.winfo_width() // 2
                    y = button.winfo_rooty() + button.winfo_height() // 2
                    # Mapped does not necessarily mean touchable: a sibling
                    # might cover it while all reported bounds still look valid.
                    target = root.winfo_containing(x, y)
                    while target is not None and target is not button:
                        target = target.master
                    assert target is button, "Settings footer is occluded"
                capture("native-settings-" + name)
        finally:
            settings.win.destroy()
        print(
            json.dumps(
                {
                    "screen": [root.winfo_width(), root.winfo_height()],
                    "fullscreen": True,
                    "main": main_stats,
                    "static_dialog": static_stats,
                    "settings_construct_and_layout_ms": settings_open_ms,
                    "settings_first_feedback_ms": settings_first_feedback_ms,
                    "settings_build_max_event_gap_ms": round(max(settings_gaps), 2),
                    "callback_faults": faults,
                    "live_connections": 0,
                }
            ),
            flush=True,
        )
    finally:
        faulthandler.cancel_dump_traceback_later()
        app.stop_update_service()
        app.delivery.close()
        app.sound.close()
        app.history.close(2)
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
