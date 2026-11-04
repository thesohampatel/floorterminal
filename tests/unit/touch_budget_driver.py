"""Count real kiosk taps through durable workflows; sockets are forbidden."""

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
    parser.add_argument(
        "--sizes",
        nargs="+",
        default=["320x400", "640x400", "800x480", "480x800", "1920x1080"],
        help="Test window sizes; use the actual panel resolution for hardware checks",
    )
    args = parser.parse_args()
    home = isolated_home()
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

    def denied(*_args, **_kwargs):
        raise AssertionError("No real connections permitted in touch-budget tests")

    socket.socket.connect = denied
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp
    from floorterminal.integration import IntegrationDefinition
    from floorterminal.services.delivery import DeferredIntegration
    from floorterminal.services.integration import ExternalIntegration
    from floorterminal.storage.delivery import binding
    from floorterminal.storage.state import StateStore
    from tests.unit.test_delivery_journal import ScriptedTransport

    root = tk.Tk()
    root.overrideredirect(True)
    app = FloorTerminalApp(root)
    app.stop_update_service()
    app.delivery.close()
    app.history.close(2)
    data = json.loads((ROOT / "connector.example.json").read_text())
    data["enabled"] = True
    data["connection"]["base_url"] = "https://service.example.test/v1"
    data["credentials"]["access_token"] = "offline-only"
    path = home / "fixture.connector.json"
    path.write_text(json.dumps(data))
    app.config.update(engineering_team_name="Maintenance", asset_status_tracking=False)
    transport = ScriptedTransport()
    remote = ExternalIntegration(
        app.config, app.logger, transport, IntegrationDefinition(path)
    )
    app.provider = DeferredIntegration(app, remote)
    app.client = app.provider.client
    app.state["roster_cache"] = {
        "binding": binding(remote),
        "team_name": "Maintenance",
        "team_id": "t1",
        "saved_at": time.time(),
        "members": [
            {"id": str(i), "displayName": f"Engineer {i:02}"} for i in range(1, 13)
        ],
    }
    faults, paths = [], []
    root.report_callback_exception = lambda _kind, value, _tb: faults.append(str(value))

    def settle():
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            root.update()
            if not app.busy:
                break
            time.sleep(0.002)
        assert not app.busy and not app.error_panel and not faults, (
            app.error_panel,
            faults,
        )
        app.render()
        w, h = app.canvas.logical_width, app.canvas.logical_height
        for key, (a, b, c, d) in app.hitboxes.items():
            assert -0.1 <= a < c <= w + 0.1 and -0.1 <= b < d <= h + 0.1, (
                key,
                (a, b, c, d),
                (w, h),
            )
            assert c - a >= 43.9 and d - b >= 43.9, (key, "small touch target")
        for (key, one), (other, two) in itertools.combinations(app.hitboxes.items(), 2):
            assert (
                min(one[2], two[2]) - max(one[0], two[0]) <= 0.1
                or min(one[3], two[3]) - max(one[1], two[1]) <= 0.1
            ), (key, other, "overlap")

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

    def run(label, keys, limit):
        for key in keys:
            tap(key)
        assert len(keys) <= limit
        paths.append({"size": size, "action": label, "taps": len(keys), "limit": limit})

    def capture(name):
        if args.capture:
            args.capture.mkdir(parents=True, exist_ok=True)
            app.touch_feedback = None
            app.render()
            root.update_idletasks()
            capture_window(root, args.capture / f"{name}-{size}.png")

    try:
        for size in args.sizes:
            root.geometry(size + "+0+0")
            settle()
            assert "primary" in app.hitboxes and "zone_0" in app.hitboxes
            assert not any(k.startswith("ui_home_") for k in app.hitboxes)
            capture("main")
            tap("zone_0")
            assert all(f"failure_{i}" in app.hitboxes for i in range(5))
            assert "ui_page_next" not in app.hitboxes
            capture("report")
            tap("failure_0")
            tap("failure_report")
            paths.append({"size": size, "action": "report", "taps": 3, "limit": 3})
            assert app.state["status"] == "DOWN"
            tap("primary")
            assert "members_next" not in app.hitboxes
            capture("crew")
            tap("member_0")
            paths.append({"size": size, "action": "arrival", "taps": 2, "limit": 2})
            assert app.state["status"] == "REPAIRING"
            record, started = app.state["response_record_id"], app.state["started_at"]
            run("join", ("crew", "member_1"), 2)
            assert len(app.state["engineer_ids"]) == 2
            run("leave", ("crew", "member_0"), 2)
            assert len(app.state["engineer_ids"]) == 1
            run("last person leaves", ("crew", "member_0"), 2)
            assert (
                app.state["engineer_ids"] == [] and app.state["status"] == "REPAIRING"
            )
            assert (app.state["response_record_id"], app.state["started_at"]) == (
                record,
                started,
            )
            tap("primary")
            assert "ui_page_next" not in app.hitboxes
            capture("resume")
            tap("confirm")
            paths.append({"size": size, "action": "completion", "taps": 2, "limit": 2})
            assert StateStore(app.state_store.path).data["status"] == "RUNNING"
            run("report self-fix", ("zone_0", "failure_1", "failure_self_fix"), 3)
            record, started = app.state["response_record_id"], app.state["started_at"]
            run("request Engineering", ("operator_request",), 2)
            run("handover arrival", ("primary", "member_0"), 2)
            assert not app.operator_resolving()
            assert (app.state["response_record_id"], app.state["started_at"]) == (
                record,
                started,
            )
            run("handover completion", ("primary", "confirm"), 2)
            run("whole-line report", ("zone_all", "confirm"), 3)
            run("whole-line arrival", ("primary", "member_0"), 2)
            run("whole-line completion", ("primary", "confirm"), 2)
            assert not app.modal and app.state["status"] == "RUNNING"

        # Large directories retain every entry and batch choice. Filtering is an
        # optional extra, not falsely counted as a two-tap routine operation.
        app.state["roster_cache"]["members"] = [
            {"id": str(i), "displayName": f"Engineer {i:03}"} for i in range(1, 201)
        ]
        tap("zone_0")
        tap("failure_report")
        tap("primary")
        assert app.modal["visible_member_count"] < 200
        assert len(app.modal["full_members"]) == 200
        tap("members_mode")
        tap("member_0")
        first = set(app.modal["selected"])
        tap("members_search")
        for char in "Engineer 200":
            app.on_keypress(SimpleNamespace(keysym=char, char=char))
        app.on_keypress(SimpleNamespace(keysym="Return", char=""))
        settle()
        assert [m["id"] for m in app.modal["members"]] == ["200"]
        tap("member_0")
        assert app.modal["selected"] == first | {"200"}
        assert app.state["status"] == "DOWN", "Batch must wait for Apply"
        tap("start_engineers")
        assert set(app.state["engineer_ids"]) == first | {"200"}
        tap("primary")
        tap("confirm")
        assert transport.requests == []
        print(
            json.dumps(
                {
                    "paths": paths,
                    "callback_faults": faults,
                    "live_connections": 0,
                    "large_roster_batch_verified": True,
                }
            )
        )
    finally:
        app.delivery.close()
        app.history.close(2)
        app.sound.close()
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
