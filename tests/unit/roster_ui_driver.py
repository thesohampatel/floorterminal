"""Real kiosk roster refresh: isolated files, in-memory transport, denied sockets."""

import argparse
import itertools
import json
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

from ui_smoke_driver import ROOT, capture_window, isolated_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    home = isolated_home()
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

    def denied(*_args, **_kwargs):
        raise AssertionError("Live sockets forbidden")

    socket.socket.connect = denied
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp
    from floorterminal.integration import IntegrationDefinition
    from floorterminal.services.delivery import DeferredIntegration, DeliveryCoordinator
    from floorterminal.services.integration import ExternalIntegration
    from floorterminal.storage.delivery import binding
    from tests.unit.test_delivery_journal import ScriptedTransport

    root = tk.Tk()
    app = FloorTerminalApp(root)
    app.stop_update_service()
    app.history.close(2)
    root.attributes("-fullscreen", False)
    root.geometry("800x480+0+0")
    faults = []
    root.report_callback_exception = lambda _kind, error, _tb: faults.append(str(error))
    data = json.loads((ROOT / "connector.example.json").read_text())
    data["enabled"] = True
    data["connection"]["base_url"] = "https://service.example.test/v1"
    data["credentials"]["access_token"] = "offline-fixture-only"
    path = home / "connector.json"
    path.write_text(json.dumps(data))
    definition = IntegrationDefinition(path)
    transport = ScriptedTransport()
    transport.wait = threading.Event()
    app.config.update(
        engineering_team_name="Maintenance", api_requests_per_minute=10000
    )
    app._api_request_window.set_budget(10000)
    app.delivery.close()
    app.provider = DeferredIntegration(
        app, ExternalIntegration(app.config, app.logger, transport, definition)
    )
    app.delivery = DeliveryCoordinator(
        app,
        lambda config, logger, definition: ExternalIntegration(
            config, logger, transport, definition
        ),
    )
    app.state["roster_cache"] = {
        "binding": binding(app.provider.remote),
        "team_name": "Maintenance",
        "team_id": "t1",
        "members": [{"id": "u1", "displayName": "Saved Engineer"}],
        "saved_at": time.time() - 4000,
    }

    def pump(predicate, timeout=8):
        until = time.monotonic() + timeout
        while not predicate() and time.monotonic() < until:
            app.delivery.next_poll = 0
            root.update()
            time.sleep(0.002)
        assert predicate(), "Timed out waiting for the kiosk"
        assert not faults and not app.error_panel, (faults, app.error_panel)

    def settle():
        for _ in range(12):
            root.update()
            time.sleep(0.02)

    def reveal(settings):
        button = settings.roster_refresh_button
        for canvas, body in settings._scroll_areas:
            if canvas.winfo_viewable():
                top = (
                    button.winfo_rooty()
                    - body.winfo_rooty()
                    - canvas.winfo_height()
                    + button.winfo_height()
                    + 10
                )
                canvas.yview_moveto(max(0, top / body.winfo_height()))
        settle()
        x = button.winfo_rootx() + button.winfo_width() // 2
        y = button.winfo_rooty() + button.winfo_height() // 2
        assert root.winfo_containing(x, y) is button, "Refresh control is occluded"
        assert button.winfo_height() >= 44 and button.winfo_width() >= 44
        assert root.winfo_rooty() <= button.winfo_rooty()
        assert (
            button.winfo_rooty() + button.winfo_height()
            <= root.winfo_rooty() + root.winfo_height()
        )

    try:
        settle()
        before_config, before_connector = (
            (home / "config.json").read_bytes(),
            path.read_bytes(),
        )
        pump(lambda: not app.busy)
        settings = app.open_settings()
        settings.tabs.select(1)
        settle()
        for size in ("800x480", "480x800", "1920x1200"):
            root.geometry(size + "+0+0")
            settle()
            reveal(settings)
            if args.capture:
                args.capture.mkdir(parents=True, exist_ok=True)
                capture_window(root, args.capture / f"saved-team-{size}.png")
        settings.vars["engineering_team_name"].set("Unsaved change")
        settings._refresh_team_members()
        assert "Save team" in settings.error.get()
        assert not transport.requests
        settings.vars["engineering_team_name"].set("Maintenance")
        settings.error.set("")
        root.geometry("800x480+0+0")
        settle()
        reveal(settings)
        settings.roster_refresh_button.invoke()
        pump(transport.entered.is_set)
        pump(lambda: not app.busy)
        times = []

        def heartbeat():
            times.append(time.monotonic())
            if len(times) < 60:
                root.after(20, heartbeat)

        heartbeat()
        settings.win.destroy()
        assert settings._roster_after is None
        for _ in range(30):
            app.load_engineers({"kind": "repair"})
            assert app.modal["members"][0]["displayName"] == "Saved Engineer"
            root.update()
        pump(lambda: len(times) == 60)
        assert not app.busy and app.delivery.active == "roster"
        assert len(transport.requests) == 1
        transport.wait.set()
        pump(lambda: not app.delivery.active and not app.busy)
        assert app.state["roster_cache"]["members"][0]["displayName"] == "Alex Engineer"
        assert app.modal["members"][0]["displayName"] == "Saved Engineer", (
            "Open picker changed beneath the operator"
        )
        app.load_engineers({"kind": "repair"})
        assert app.modal["members"][0]["displayName"] == "Alex Engineer"
        assert len(transport.requests) == 2
        assert (home / "config.json").read_bytes() == before_config
        assert path.read_bytes() == before_connector
        gaps = [(b - a) * 1000 for a, b in itertools.pairwise(times)]
        assert max(gaps) < 500, gaps
        print(
            json.dumps(
                {
                    "viewports": 3,
                    "cached_opens": 30,
                    "requests": len(transport.requests),
                    "max_heartbeat_ms": round(max(gaps), 2),
                    "faults": faults,
                    "live_connections": 0,
                    "config_connector_unchanged": True,
                    "stable_open_picker": True,
                }
            )
        )
    finally:
        transport.wait.set()
        app.delivery.close()
        app.sound.close()
        app.history.close(2)
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home)


if __name__ == "__main__":
    main()
