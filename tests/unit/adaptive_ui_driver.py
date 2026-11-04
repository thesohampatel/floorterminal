"""Offline kiosk reflow, touch geometry, resize and navigation checks on real Tk.

Optional --capture DIR writes neutral preview images outside deployment data.
Every socket connection is blocked before the app starts; this test cannot call
an operator's configured service or the update channel.
"""

import argparse
import itertools
import json
import shutil
import socket
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

from ui_smoke_driver import (
    ERROR_PANEL,
    SAMPLE_ERROR_PANEL,
    capture_window,
    copy_dialog,
    dialogs,
    isolated_home,
)

SIZES = (
    (320, 400),
    (360, 640),
    (480, 800),
    (640, 400),
    (800, 480),
    (913, 577),
    (1024, 600),
    (1024, 1024),
    (1080, 1920),
    (1366, 768),
    (1920, 1080),
    (2560, 720),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    home = isolated_home()

    def denied(*_args, **_kwargs):
        raise AssertionError("External network is forbidden in GUI verification")

    socket.socket.connect = denied
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp

    root = tk.Tk()
    app = FloorTerminalApp(root)
    app.update_service.stop()
    app.perform = lambda *_a, **_kw: True
    faults = []
    root.report_callback_exception = lambda kind, value, _tb: faults.append(str(value))

    def settle():
        for _ in range(8):
            root.update()

    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)

    def tap(key):
        box = app.hitboxes[key]
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        scale = app.canvas.scale_factor
        event = SimpleNamespace(
            x=x * scale + app.canvas.offset_x, y=y * scale + app.canvas.offset_y
        )
        app.on_press(event)
        app.on_release(event)
        app.render()

    def check_targets(where):
        w, h = app.canvas.logical_width, app.canvas.logical_height
        for key, (a, b, c, d) in app.hitboxes.items():
            if a < -0.1 or b < -0.1 or c > w + 0.1 or d > h + 0.1:
                faults.append(
                    f"{where}: {key} outside viewport: {(a, b, c, d)} vs {(w, h)}"
                )
            if c - a < 43.9 or d - b < 43.9:
                faults.append(
                    f"{where}: {key} target smaller than 44 units: {(c - a, d - b)}"
                )
        for (key, one), (other, two) in itertools.combinations(app.hitboxes.items(), 2):
            if (
                min(one[2], two[2]) - max(one[0], two[0]) > 0.1
                and min(one[3], two[3]) - max(one[1], two[1]) > 0.1
            ):
                faults.append(f"{where}: targets overlap: {key}, {other}")

    original_info = app.provider.INFO
    # Turn capabilities on without a connector or client. No worker runs.
    app.provider.INFO = SimpleNamespace(
        **{
            **vars(original_info),
            "supports_response_records": True,
            "supports_team_directory": True,
            "supports_messaging": True,
        }
    )
    snapshots = 0
    try:
        settle()
        for width, height in SIZES:
            root.geometry(f"{width}x{height}+0+0")
            settle()
            for state in ("RUNNING", "DOWN", "REPAIRING", "ENGINEERING"):
                for dialog in [*dialogs(), {"kind": "support"}]:
                    app.state["status"] = state
                    app.modal = copy_dialog(dialog)
                    app.error_panel = (
                        dict(SAMPLE_ERROR_PANEL)
                        if dialog and dialog["kind"] == ERROR_PANEL
                        else None
                    )
                    app.busy = False
                    # Exercise draft/batch layouts, not removed home-screen pages.
                    for batch in (
                        (False, True)
                        if dialog and dialog.get("kind") == "engineers"
                        else (False,)
                    ):
                        if app.modal:
                            app.modal["batch"] = batch
                        for page in (
                            range(8)
                            if app.modal
                            and app.modal["kind"]
                            in {
                                "password",
                                "text_input",
                                "failures",
                                "engineers",
                                "about",
                            }
                            else (0,)
                        ):
                            if app.modal:
                                app.modal["keys_page"] = page
                                app.modal["layout_page"] = page
                            app.render()
                            check_targets(
                                f"{width}x{height}/{state}/{(dialog or {}).get('kind')}/batch={batch}/{page}"
                            )
                            snapshots += 1
            # Selection, long station names and page boundaries at every width.
            for status, requested in (("REPAIRING", None), ("DOWN", 100)):
                app.state.update(
                    status=status,
                    response_record_id="record-offline",
                    operator_response={
                        "name": "Operator A",
                        "started_at": 1,
                        "requested_at": requested,
                        "handed_over_at": None,
                    },
                )
                for kind in (None, "operator_setup", "operator_options"):
                    app.modal = {"kind": kind} if kind else None
                    app.error_panel = None
                    app.render()
                    check_targets(f"{width}x{height}/operator/{status}/{kind}")
                    snapshots += 1
            app.state["operator_response"] = None
            app.error_panel, app.modal = None, None
            app.state["status"] = "RUNNING"
            app.config["zones"] = [
                f"Station {index} • inspection and assembly" for index in range(1, 104)
            ]
            app.state["issue_zones"] = []
            app.station_page = 0
            app.touch_feedback = None
            app.render()
            if not {"primary", "zone_all", "zone_0"}.issubset(app.hitboxes):
                faults.append(
                    f"{width}x{height}: map and workflow not visible together"
                )
            seen = set()
            for _ in range(104):
                app.render()
                seen.update(
                    key
                    for key in app.hitboxes
                    if key.startswith("zone_") and key != "zone_all"
                )
                check_targets(f"{width}x{height}/103 stations")
                if "stations_next" not in app.hitboxes:
                    break
                tap("stations_next")
            if len(seen) != 103:
                faults.append(f"{width}x{height}: {len(seen)}/103 stations reachable")
            from floorterminal.update.service import StagedUpdate, UpdateStatus

            saved_status = app.update_status
            app.update_status = lambda: UpdateStatus(
                managed=True,
                rollback_version="1.0.0",
                staged=StagedUpdate(
                    version="1.1.0",
                    release_title="Offline test",
                    release_summary="Test only",
                    released_utc="2026-01-01T00:00:00Z",
                    artifact_sha256="a" * 64,
                    signing_key_id="offline",
                    source_mount="/test",
                    highlights=(),
                ),
            )
            for kind in ("update", "update_actions"):
                app.modal = {"kind": kind, "page": "status"}
                app.render()
                check_targets(f"{width}x{height}/{kind}/install-and-rollback")
            app.update_status = saved_status
            # Pending delivery controls must also fit when a real journal item
            # exposes authentication/reconciliation actions, not just when empty.
            from floorterminal.storage.delivery import enqueue

            for method, arguments, expiry in (
                (
                    "create_response_record",
                    ["Example", "Offline test", None, "HIGH", None, []],
                    None,
                ),
                ("send_message", ["Support", "Offline test"], 1),
                ("set_response_record_status", ["R1", "DONE"], None),
            ):
                item = enqueue(
                    app.state,
                    app.provider.remote,
                    method,
                    arguments,
                    {},
                    expires_at=expiry,
                )
                item["phase"] = "attention"
                app.modal = {"kind": "delivery", "item": 0}
                for page in range(8):
                    app.modal["layout_page"] = page
                    app.render()
                    check_targets(f"{width}x{height}/delivery/{method}/{page}")
                    snapshots += 1
                app.state["delivery_outbox"] = []
            app.modal = None
            app.config["zones"] = [
                "Station 1",
                "Station 2",
                "Station 3",
                "Station 4",
                "Station 5",
            ]
            app.station_page = 0
            app.render()
            if args.capture and (width, height) in {
                (800, 480),
                (480, 800),
                (1920, 1080),
            }:
                args.capture.mkdir(parents=True, exist_ok=True)
                app.touch_feedback = None
                app.render()
                settle()
                capture_window(root, args.capture / f"kiosk-{width}x{height}.png")
        # Native settings pages retain edits and expose every category as the
        # SAME panel changes size; small displays scroll forms, not the footer.
        app.modal = None
        settings = app.open_settings()
        settings.vars["line_name"].set("Assembly Line")
        for width, height in SIZES:
            root.geometry(f"{width}x{height}+0+0")
            settle()
            for index in range(6):
                settings.tabs.select(index)
                settle()
                if (
                    settings.win.winfo_x(),
                    settings.win.winfo_y(),
                    settings.win.winfo_width(),
                    settings.win.winfo_height(),
                ) != (0, 0, width, height):
                    faults.append(f"Settings does not fill kiosk: {width}x{height}")
                if any(
                    key in settings.vars
                    for key in (
                        "log_level",
                        "log_retention_days",
                        "log_storage_reserve_mb",
                    )
                ):
                    faults.append("Legacy housekeeping controls are still exposed")
                if settings.tabs.index("current") != index:
                    faults.append(
                        f"Settings page {index} unreachable at {width}x{height}"
                    )
                for widget in descendants(settings.win):
                    if isinstance(widget, tk.Button) and widget.cget("text") in {
                        "SAVE",
                        "SAVE SETTINGS",
                        "SAVE ALL SETTINGS",
                        "CANCEL",
                    }:
                        x, y = (
                            widget.winfo_rootx() - root.winfo_rootx(),
                            widget.winfo_rooty() - root.winfo_rooty(),
                        )
                        if (
                            not widget.winfo_viewable()
                            or x < 0
                            or y < 0
                            or x + widget.winfo_width() > width
                            or y + widget.winfo_height() > height
                        ):
                            faults.append(
                                f"Settings footer off-screen: {width}x{height}/{index}/{widget.cget('text')}"
                            )
                for canvas, _body in settings._scroll_areas:
                    if not canvas.winfo_viewable():
                        continue
                    for pager in canvas.master.winfo_children():
                        if (
                            not getattr(pager, "_ft_form_pager", False)
                            or not pager.winfo_viewable()
                        ):
                            continue
                        canvas.yview_moveto(0)
                        settle()
                        controls = {
                            child.cget("text"): child
                            for child in pager.winfo_children()
                            if isinstance(child, tk.Button)
                        }
                        next_page = controls[settings.t("settings_next")]
                        if str(next_page.cget("state")) != "disabled":
                            next_page.invoke()
                            settle()
                            if canvas.yview()[0] <= 0:
                                faults.append(
                                    f"Settings Next did not move form: {width}x{height}/{index}"
                                )
                            controls[settings.t("settings_previous")].invoke()
                            settle()
                        for button in controls.values():
                            if button.winfo_height() < 44:
                                faults.append(
                                    f"Settings page target below 44px: {width}x{height}/{index}"
                                )
                        canvas.yview_moveto(0)
                        settle()
                if (
                    args.capture
                    and (width, height) in {(480, 800), (800, 480)}
                    and index in {0, 2}
                ):
                    capture_window(
                        root, args.capture / f"settings-{index}-{width}x{height}.png"
                    )
            if settings.vars["line_name"].get() != "Assembly Line":
                faults.append("Resize lost an unsaved setting")
        settings.win.destroy()
        root.geometry("280x240")
        settle()
        app.render()
        if app.hitboxes:
            faults.append("Undersized window still exposes unsafe controls")
    except Exception:  # noqa: BLE001 - report all Tk failures to the parent test
        faults.append(traceback.format_exc())
    finally:
        app.history.close(2)
        app.logger.close(2)
        root.destroy()
        shutil.rmtree(home, ignore_errors=True)
    print(json.dumps({"snapshots": snapshots, "faults": faults}))
    return bool(faults)


if __name__ == "__main__":
    raise SystemExit(main())
