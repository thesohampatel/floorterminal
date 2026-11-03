"""Offline real-Tk responsiveness check during a blocked external write.

Uses an isolated deployment, denied sockets and an in-memory connector transport.
Optional captures contain only neutral fixtures. No installed kiosk is touched.
"""

import argparse
import itertools
import json
import shutil
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ui_smoke_driver import ROOT, capture_window, isolated_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    home = isolated_home()
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

    def denied(*_args, **_kwargs):
        raise AssertionError("Network access forbidden in offline GUI test")

    socket.socket.connect = denied
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp
    from floorterminal.integration import IntegrationDefinition
    from floorterminal.services.delivery import DeferredIntegration, DeliveryCoordinator
    from floorterminal.services.integration import ExternalIntegration
    from floorterminal.storage.delivery import enqueue
    from tests.unit.test_delivery_journal import ScriptedTransport

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("800x480+0+0")
    app = FloorTerminalApp(root)
    app.stop_update_service()
    root.geometry("800x480+0+0")
    root.update()
    faults = []
    root.report_callback_exception = lambda _kind, value, _tb: faults.append(str(value))
    data = json.loads((ROOT / "connector.example.json").read_text())
    data["enabled"] = True
    data["connection"]["base_url"] = "https://service.example.test/v1"
    data["credentials"]["access_token"] = "offline-only"
    path = home / "fixture-connector.json"
    path.write_text(json.dumps(data))
    definition = IntegrationDefinition(path)
    transport = ScriptedTransport()
    transport.wait = threading.Event()
    app.config.update(engineering_team_name="", api_requests_per_minute=10000)
    app._api_request_window.set_budget(10000)
    app.delivery.close()
    app.provider = DeferredIntegration(
        app, ExternalIntegration(app.config, app.logger, transport, definition)
    )
    app.client = app.provider.client
    app.delivery = DeliveryCoordinator(
        app,
        lambda config, logger, definition: ExternalIntegration(
            config, logger, transport, definition
        ),
    )

    def pump_until(predicate, timeout=8):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            app.delivery.next_poll = 0
            root.update()
            time.sleep(0.002)
        assert predicate(), "GUI operation did not finish within its time bound"
        assert not faults, faults

    def perform(function):
        # A legitimate background history acknowledgement can briefly own the
        # local-state worker. Wait for readiness, never bypass its durable lock.
        pump_until(lambda: not app.busy)
        assert app.perform("Offline GUI verification", function)
        pump_until(lambda: not app.busy)
        assert app.error_panel is None, app.error_panel

    def tap(key):
        app.render()
        a, b, c, d = app.hitboxes[key]
        event = SimpleNamespace(
            x=(a + c) / 2 * app.canvas.scale_factor + app.canvas.offset_x,
            y=(b + d) / 2 * app.canvas.scale_factor + app.canvas.offset_y,
        )
        app.on_press(event)
        app.on_release(event)
        root.update()

    try:
        root.update()
        app.state["issue_zones"] = [app.config["zones"][0]]
        perform(app.report_downtime)
        pump_until(transport.entered.is_set)
        assert not app.busy and app.delivery.active
        times = []

        def heartbeat():
            times.append(time.monotonic())
            if len(times) < 100:
                root.after(20, heartbeat)

        heartbeat()
        tap("about")
        assert app.modal["kind"] == "about"
        tap("cancel")
        perform(lambda: app.start_repair(None, []))
        perform(app.finish_work)
        assert app.state["status"] == "RUNNING"
        pump_until(lambda: len(times) == 100)
        gaps = [(b - a) * 1000 for a, b in itertools.pairwise(times)]
        assert max(gaps) < 500, f"Event-loop stall: {max(gaps):.1f} ms"
        assert not app.busy and app.delivery.active
        transport.wait.set()
        pump_until(
            lambda: not app.state["delivery_outbox"] and not app.delivery.active, 15
        )
        assert len(transport.ids) == 1
        # A stalled SD-card fsync must not own the Tk event loop either. Exercise
        # both durable dispatch and its acknowledgement through the real worker.
        app.history.close(2)
        pump_until(lambda: not app.busy)
        from floorterminal.storage import state as state_module

        enqueue(
            app.state,
            app.provider.remote,
            "set_response_record_status",
            ["R1", "DONE"],
            {},
        )
        app.save_state()
        original_write = state_module.write_json
        write_threads, slow_times = [], []

        def slow_write(*positional, **keywords):
            write_threads.append(threading.current_thread() is threading.main_thread())
            time.sleep(0.8)
            return original_write(*positional, **keywords)

        def slow_heartbeat():
            slow_times.append(time.monotonic())
            if len(slow_times) < 120:
                root.after(20, slow_heartbeat)

        slow_heartbeat()
        with mock.patch.object(state_module, "write_json", side_effect=slow_write):
            pump_until(
                lambda: not app.state["delivery_outbox"] and not app.delivery.active
            )
            # Station/failure selection uses the same off-screen persistence
            # worker and advances its dialog only after a successful save.
            tap("zone_0")
            pump_until(lambda: not app.busy)
            assert app.modal["kind"] == "failures"
            tap("failure_0")
            tap("failure_done")
            pump_until(lambda: not app.busy)
            assert app.modal is None
            pump_until(lambda: len(slow_times) == 120)
        slow_gaps = [(b - a) * 1000 for a, b in itertools.pairwise(slow_times)]
        assert len(write_threads) >= 4 and not any(write_threads), write_threads
        assert max(slow_gaps) < 500, (
            f"Slow-storage event-loop stall: {max(slow_gaps):.1f} ms"
        )
        app.delivery.close()
        item = enqueue(
            app.state,
            app.provider.remote,
            "create_response_record",
            ["Example line event", "Offline verification", None, "HIGH", None, []],
            {},
        )
        item.update(
            phase="attention",
            error="Remote acceptance uncertain • connection ended before a response arrived",
        )
        for size in ("800x480", "480x800", "1920x1080"):
            root.geometry(size + "+0+0")
            for _ in range(8):
                root.update()
            app.modal = {"kind": "delivery", "item": 0}
            app.render()
            root.update_idletasks()
            if args.capture:
                args.capture.mkdir(parents=True, exist_ok=True)
                capture_window(root, args.capture / f"delivery-{size}.png")
        asset = enqueue(
            app.state,
            app.provider.remote,
            "set_asset_status",
            ["OFFLINE", "UNPLANNED", "Offline fixture", "2026-01-01T10:00:00Z"],
            {},
        )
        asset.update(phase="attention", error="Remote acceptance uncertain")
        for size in ("800x480", "480x800", "1920x1080"):
            root.geometry(size + "+0+0")
            for _ in range(8):
                root.update()
            app.modal = {"kind": "delivery", "item": 1}
            app.render()
            bounds = app.hitboxes["ui_delivery_asset_confirm"]
            viewport = app.viewport()
            assert 0 <= bounds[0] < bounds[2] <= viewport.width
            assert 0 <= bounds[1] < bounds[3] <= viewport.height
            if args.capture:
                capture_window(root, args.capture / f"asset-review-{size}.png")
            tap("ui_delivery_asset_confirm")
            assert app.modal["kind"] == "text_input"
            app.modal["value"] = "verified-event-18"
            app.submit_text_input()
            assert app.modal["kind"] == "password"
            assert app.modal["purpose"] == "delivery_asset_confirm"
            assert app.modal["record_id"] == "verified-event-18"
            assert asset["phase"] == "attention", (
                "Evidence alone must not authorize reconciliation"
            )
        print(
            json.dumps(
                {
                    "heartbeat_count": len(times),
                    "maximum_gap_ms": round(max(gaps), 2),
                    "slow_storage_maximum_gap_ms": round(max(slow_gaps), 2),
                    "slow_storage_writes": len(write_threads),
                    "requests": len(transport.requests),
                    "duplicate_records": len(transport.ids) - 1,
                    "callback_faults": faults,
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
