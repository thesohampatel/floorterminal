"""Touch-through operator response on real Tk, in a socket-denied deployment."""

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
        raise AssertionError("No network in operator GUI verification")

    socket.socket.connect = denied
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp
    from floorterminal.storage.state import StateStore

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("800x480+0+0")
    app = FloorTerminalApp(root)
    app.stop_update_service()
    root.geometry("800x480+0+0")
    root.update()
    faults = []
    root.report_callback_exception = lambda _kind, value, _tb: faults.append(str(value))

    def settle():
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            root.update()
            if not app.busy:
                break
            time.sleep(0.002)
        assert not app.busy, "Local action stayed busy"
        assert not app.error_panel, app.error_panel
        assert not faults, faults

    def tap(key):
        app.render()
        a, b, c, d = app.hitboxes[key]
        event = SimpleNamespace(
            x=(a + c) / 2 * app.canvas.scale_factor + app.canvas.offset_x,
            y=(b + d) / 2 * app.canvas.scale_factor + app.canvas.offset_y,
        )
        app.on_press(event)
        app.on_release(event)
        settle()

    def capture(name):
        if args.capture:
            args.capture.mkdir(parents=True, exist_ok=True)
            app.touch_feedback = None
            app.render()
            root.update_idletasks()
            assert (root.winfo_width(), root.winfo_height()) == (800, 480), (
                "Capture must show the whole kiosk"
            )
            capture_window(root, args.capture / (name + ".png"))

    try:
        settle()
        for handover in (False, True):
            app.state["issue_zones"] = [app.config["zones"][0]]
            tap("primary")
            capture("operator-response-choice")
            tap("operator_details")
            tap("operator_name")
            assert app.modal["purpose"] == "operator_name"
            app.modal["value"] = "Operator A"
            tap("pwd_enter")
            assert app.modal["name"] == "Operator A"
            capture("operator-response-setup")
            tap("operator_start")
            assert app.state["status"] == "REPAIRING"
            record, started = app.state["response_record_id"], app.state["started_at"]
            assert (
                StateStore(app.state_store.path).data["operator_response"]["name"]
                == "Operator A"
            )
            capture("operator-response-active")
            capture("operator-response-handover")
            if handover:
                tap("operator_request")
                assert app.state["status"] == "DOWN"
                tap("primary")
                assert not app.operator_resolving()
                assert app.state["response_record_id"] == record
                assert app.state["started_at"] == started
            tap("primary")
            tap("confirm")
            assert app.state["status"] == "RUNNING"
        creates = [
            item
            for item in app.state["delivery_outbox"]
            if item["method"] == "create_response_record"
        ]
        assert len(creates) == 2, "One creation per incident required"
        app.modal = {
            "kind": "password",
            "stage": "identity",
            "value": "",
            "title": "SETTINGS ACCESS",
        }
        capture("kiosk-password")
        print(
            json.dumps({"incidents": 2, "callback_faults": faults, "remote_calls": 0})
        )
    finally:
        app.delivery.close()
        app.history.close(2)
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
