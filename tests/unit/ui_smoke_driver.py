#!/usr/bin/env python3
"""Drive the real touchscreen in an isolated deployment root and report faults.

This runs as a subprocess so the deployment root, configuration, state, and logs
are created in a temporary directory before ``floorterminal`` is imported.
Module-level path constants are resolved at import time, so isolation is only
achievable before the first import.

It renders every reachable combination of workflow state and dialog, presses every
registered touch target in each of them, and feeds keyboard input to the text
dialogs. Any exception — including one routed through Tk's callback handler — is
collected and reported as JSON on stdout.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

if os.environ.get("COVERAGE_PROCESS_START"):  # pragma: no cover - measurement only
    # This driver is the only place the touchscreen is exercised, so its coverage
    # has to be recorded explicitly rather than relying on an installed .pth file.
    try:
        import coverage

        coverage.process_startup()
    except ImportError:
        pass

ROOT = Path(__file__).resolve().parents[2]

# Controls that open a modal window, replace the process, or end the session are
# driven by their own tests rather than by the sweep.
EXCLUDED_CONTROLS = frozenset(
    {
        "settings",
        "primary",
        "crew",
        "planned_work",
        "sync_pending",
        "engineering",
        "quality",
        "production",
        "update_install",
        "update_rollback",
    }
)

WORKFLOW_STATES = ("RUNNING", "DOWN", "REPAIRING", "ENGINEERING")


def dialogs():
    """Every dialog the operator can reach, in the shape the controller builds."""
    return [
        None,
        {"kind": "about"},
        {"kind": "update", "page": "status"},
        {"kind": "update", "page": "version"},
        {"kind": "update", "page": "changes"},
        {"kind": "update", "page": "activity"},
        {
            "kind": "confirm_downtime",
            "title": "CONFIRM LINE DOWNTIME",
            "message": "Report the selected station(s) as stopped?",
        },
        {
            "kind": "confirm_done",
            "title": "CONFIRM COMPLETION",
            "message": "Return the line to production?",
        },
        {"kind": "planned"},
        {
            "kind": "password",
            "value": "",
            "shift": True,
            "stage": "identity",
            "purpose": "settings",
            "title": "SETTINGS LOCKED",
            "prompt": "Identify the administrator to continue",
            "administrator": "",
        },
        {
            "kind": "text_input",
            "purpose": "engineer_search",
            "title": "FILTER",
            "prompt": "Enter part of a name",
            "value": "",
            "shift": True,
            "max_length": 64,
            "return_modal": None,
        },
        *[
            {
                "kind": "password", "purpose": "password_change", "stage": stage,
                "title": "CHANGE SETTINGS PASSWORD", "prompt": prompt,
                "value": "", "shift": True,
            }
            for stage, prompt in (
                ("password", "Step 1 of 3 • Enter the current password"),
                ("new_password", "Step 2 of 3 • New password: 8–128 characters, no spaces"),
                ("confirm_password", "Step 3 of 3 • Enter the new password again"),
            )
        ],
        {
            "kind": "failures",
            "station": "Station 1",
            "options": [
                "Mechanical",
                "Electrical",
                "Material / Flow",
                "Sensor / Control",
                "Others",
            ],
            "selected": set(),
        },
        {
            "kind": "engineers",
            "members": [
                {"id": "1", "displayName": "A. Engineer"},
                {"id": "2", "displayName": "B. Engineer"},
            ],
            "selected": set(),
            "page": 0,
            "filter": "",
            "context": {"kind": "repair"},
        },
    ]


def _logical(canvas, item):
    """Return an item's bounding box in the 800x480 logical design space."""
    box = canvas.bbox(item)
    if not box:
        return None
    return tuple(
        round(
            (value - (canvas.offset_x if index % 2 == 0 else canvas.offset_y))
            / canvas.scale_factor,
            1,
        )
        for index, value in enumerate(box)
    )


def copy_dialog(dialog):
    if dialog is None:
        return None
    copied = dict(dialog)
    if "selected" in copied:
        copied["selected"] = set()
    return copied


def isolated_home():
    home = Path(tempfile.mkdtemp(prefix="floorterminal-ui-smoke-"))
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config.update(
        fullscreen_on_linux=False,
        sound_enabled=False,
        software_update_check_enabled=False,
    )
    (home / "config.json").write_text(json.dumps(config), encoding="utf-8")
    profile = json.loads(
        (ROOT / "project_profile.example.json").read_text(encoding="utf-8")
    )
    profile["settings_password"] = "ui-smoke-driver-secret"
    (home / "project_profile.json").write_text(json.dumps(profile), encoding="utf-8")
    os.environ["FLOORTERMINAL_HOME"] = str(home)
    os.environ["FLOORTERMINAL_PROJECT_PROFILE_FILE"] = str(
        home / "project_profile.json"
    )
    os.environ["FLOORTERMINAL_DISABLE_UPDATE_NETWORK"] = "1"
    return home


def main():
    home = isolated_home()
    sys.path.insert(0, str(ROOT / "src"))
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp

    faults = []

    def record(where, error):
        faults.append({"where": where, "error": error})

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(json.dumps({"skipped": f"no display: {exc}"}))
        return 0

    root.geometry("800x480+40+60")
    app = FloorTerminalApp(root, None)
    app.update_service.stop()
    root.report_callback_exception = lambda kind, value, tb: record(
        "tk-callback", f"{kind.__name__}: {value}"
    )
    for _ in range(20):
        root.update()

    def prepare(state, dialog):
        app.state["status"] = state
        app.state["issue_zones"] = [] if state == "RUNNING" else ["Station 1"]
        app.state["failure_selections"] = {}
        app.state["pending_response_record"] = None
        app.state["pending_planned_work"] = None
        app.state["started_at"] = time.time() - 300
        app.state["repair_at"] = time.time() - 60 if state == "REPAIRING" else None
        app.state["engineer_names"] = ["A. Engineer"] if state == "REPAIRING" else []
        app.busy = False
        app.modal = copy_dialog(dialog)

    rendered = 0
    for state, dialog in itertools.product(WORKFLOW_STATES, dialogs()):
        prepare(state, dialog)
        label = f"state={state} dialog={(dialog or {}).get('kind', 'none')}"
        try:
            app.render()
            root.update()
            rendered += 1
        except Exception:
            record(f"render {label}", traceback.format_exc(limit=3))

    pressed = 0
    for state, dialog in itertools.product(WORKFLOW_STATES, dialogs()):
        prepare(state, dialog)
        label = f"state={state} dialog={(dialog or {}).get('kind', 'none')}"
        try:
            app.render()
        except Exception:
            record(f"pre-render {label}", traceback.format_exc(limit=3))
            continue
        for key, box in list(app.hitboxes.items()):
            if key in EXCLUDED_CONTROLS:
                continue
            restore = copy_dialog(app.modal)
            if restore is not None and app.modal and "selected" in app.modal:
                restore["selected"] = set(app.modal["selected"])
            centre_x = (
                box[0] + box[2]
            ) / 2 * app.canvas.scale_factor + app.canvas.offset_x
            centre_y = (
                box[1] + box[3]
            ) / 2 * app.canvas.scale_factor + app.canvas.offset_y
            event = type("Event", (), {"x": centre_x, "y": centre_y})()
            try:
                app.pressed = key
                app.on_release(event)
                app.render()
                pressed += 1
            except Exception:
                record(f"press {key} {label}", traceback.format_exc(limit=3))
            app.modal = restore
            app.busy = False

    for kind in ("password", "text_input"):
        prepare("RUNNING", next(d for d in dialogs() if d and d["kind"] == kind))
        for character in "aZ9 !@#\x00\té":
            try:
                app.on_keypress(type("Event", (), {"keysym": "a", "char": character})())
            except Exception:
                record(f"keypress {kind} {character!r}", traceback.format_exc(limit=3))
        for keysym in ("Return", "KP_Enter", "BackSpace", "Escape", "F11", "Tab"):
            try:
                app.on_keypress(type("Event", (), {"keysym": keysym, "char": ""})())
            except Exception:
                record(f"keysym {kind} {keysym}", traceback.format_exc(limit=3))

    # The Settings dialog writes configuration and reapplies it to live state. It
    # is exercised with failure selections present, which is the ordinary
    # operator situation and the one that reaches the reconciliation code.
    try:
        app.modal = None
        app.select_issue_zone("Station 1")
        app.state["failure_selections"] = {"Station 1": ["Mechanical", "Others"]}
        app.state["failure_notes"] = {"Station 1": "guard interlock open"}
        settings = app.open_settings({"teams": [], "conversations": []})
        for _ in range(10):
            root.update()
        window = settings.win

        # Drive the actual protected change flow and restore the same window.
        # Cancel must keep edits; success must mask input and replace all access.
        app.modal = None
        app.auth_throttle.clear()
        settings.change_password()
        app.render()
        x1, y1, x2, y2 = app.hitboxes["cancel"]
        x = (x1 + x2) / 2 * app.canvas.scale_factor + app.canvas.offset_x
        y = (y1 + y2) / 2 * app.canvas.scale_factor + app.canvas.offset_y
        event = type("Event", (), {"x": x, "y": y})()
        app.on_press(event)
        app.on_release(event)
        root.update()
        if app.modal is not None or window.state() == "withdrawn":
            raise AssertionError("Cancel did not restore Settings")
        settings.change_password()
        for password in ("ui-smoke-driver-secret", "TouchPassword@42", "TouchPassword@42"):
            for character in password:
                app.on_keypress(type("Event", (), {"keysym": character, "char": character})())
            app.render()
            visible_text = [app.canvas.itemcget(item, "text") for item in app.canvas.find_all()
                            if app.canvas.type(item) == "text"]
            if any(password in text for text in visible_text):
                raise AssertionError("A password was drawn without masking")
            app.on_keypress(type("Event", (), {"keysym": "Return", "char": ""})())
        root.update()
        if app.modal is not None or window.state() == "withdrawn":
            raise AssertionError("Password change did not restore Settings")
        if not app.settings_credentials.verify("TouchPassword@42"):
            raise AssertionError("Changed password did not work")
        if app.settings_credentials.verify("ui-smoke-driver-secret"):
            raise AssertionError("Initial password still worked after change")
        password_changed = True

        settings_tabs_checked = 0
        for index, tab_id in enumerate(settings.tabs.tabs()):
            settings.tabs.select(tab_id)
            for _ in range(3):
                root.update()
            if settings.tabs.select() != tab_id:
                record("settings tabs", f"tab {index} could not be selected")
                continue
            tab_box = settings.tabs.bbox(index)
            if not tab_box:
                record("settings tabs", f"tab {index} has no visible tab control")
                continue
            x, _y, width, _height = tab_box
            if x < 0 or x + width > settings.tabs.winfo_width() + 1:
                record(
                    "settings tabs",
                    f"tab {index} lies outside the notebook: {tab_box}",
                )
                continue
            if (
                window.winfo_width() > window.winfo_screenwidth() + 1
                or window.winfo_height() > window.winfo_screenheight() + 1
            ):
                record(
                    "settings bounds",
                    f"window {window.winfo_width()}x{window.winfo_height()} exceeds screen "
                    f"{window.winfo_screenwidth()}x{window.winfo_screenheight()}",
                )
                continue
            settings_tabs_checked += 1

        def find_save(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Button) and "SAVE" in child.cget("text"):
                    return child
                found = find_save(child)
                if found is not None:
                    return found
            return None

        save = find_save(window)
        if save is None:
            record("settings", "no SAVE control was found in the Settings window")
        else:
            save.invoke()
            for _ in range(10):
                root.update()
        settings_saved = True
    except Exception:
        settings_saved = False
        password_changed = False
        settings_tabs_checked = 0
        record("settings save", traceback.format_exc(limit=4))

    # --- layout collisions at every supported panel size --------------------
    # The design is one 800x480 logical canvas scaled uniformly, but font sizes
    # are rounded per scale, so text can grow relative to its container at one
    # size and not another. Each size is therefore checked independently.
    collisions = []
    for label, width, height in (
        ("7-inch 800x480", 800, 480),
        ("HD documentation 1600x960", 1600, 960),
        ("10.1-inch 1280x800", 1280, 800),
        ("desktop 1920x1080", 1920, 1080),
    ):
        root.geometry(f"{width}x{height}")
        for _ in range(15):
            root.update()
        canvas = app.canvas
        if (canvas.winfo_width(), canvas.winfo_height()) != (width, height):
            record(
                "viewport",
                f"requested {width}x{height}, got {canvas.winfo_width()}x{canvas.winfo_height()}",
            )
        for state, dialog in itertools.product(WORKFLOW_STATES, dialogs()):
            prepare(state, dialog)
            app.state["issue_zones"] = ["Station 1", "Station 3"]
            app.toast_until = 0
            where = f"{label} {state}/{(dialog or {}).get('kind', 'none')}"
            try:
                app.render()
                root.update()
            except Exception:
                record(f"geometry render {where}", traceback.format_exc(limit=3))
                continue
            # A dialog paints a full-canvas scrim then draws above it; comparing
            # across that boundary would report the screen underneath.
            floor = 0
            for item in canvas.find_all():
                if canvas.type(item) != "rectangle":
                    continue
                box = _logical(canvas, item)
                if (
                    box
                    and box[0] <= 1
                    and box[1] <= 1
                    and box[2] >= 799
                    and box[3] >= 479
                ):
                    floor = item
            texts = []
            texts_with_ids = []
            for item in canvas.find_all():
                if item < floor or canvas.type(item) != "text":
                    continue
                box = _logical(canvas, item)
                value = canvas.itemcget(item, "text")
                if not box or not value.strip():
                    continue
                texts.append((box, value))
                texts_with_ids.append((item, box, value))
                if box[0] < -1 or box[2] > 801 or box[1] < -1 or box[3] > 481:
                    collisions.append(
                        {
                            "where": where,
                            "kind": "outside canvas",
                            "detail": value[:40],
                            "box": box,
                        }
                    )
            # Text painted over by a later opaque shape is the collision an
            # operator actually notices: the label is simply not there.
            covers = []
            for item in canvas.find_all():
                if item < floor or canvas.type(item) not in {
                    "rectangle",
                    "polygon",
                    "oval",
                }:
                    continue
                try:
                    if not canvas.itemcget(item, "fill"):
                        continue
                except tk.TclError:
                    continue
                box = _logical(canvas, item)
                if box:
                    covers.append((item, box))
            for item, box, value in texts_with_ids:
                area = max(1.0, (box[2] - box[0]) * (box[3] - box[1]))
                for shape_item, shape in covers:
                    if shape_item <= item:
                        continue
                    across = min(box[2], shape[2]) - max(box[0], shape[0])
                    down = min(box[3], shape[3]) - max(box[1], shape[1])
                    if across > 0 and down > 0 and (across * down) / area > 0.45:
                        collisions.append(
                            {
                                "where": where,
                                "kind": "text painted over",
                                "detail": value[:40],
                                "box": box,
                            }
                        )
                        break
            for (first, one), (second, two) in itertools.combinations(texts, 2):
                across = min(first[2], second[2]) - max(first[0], second[0])
                down = min(first[3], second[3]) - max(first[1], second[1])
                if across > 2 and down > 2:
                    collisions.append(
                        {
                            "where": where,
                            "kind": f"text overlap {across:.0f}x{down:.0f}",
                            "detail": f"{one[:26]!r} / {two[:26]!r}",
                            "box": first,
                        }
                    )

    root.destroy()
    shutil.rmtree(home, ignore_errors=True)
    print(
        json.dumps(
            {
                "rendered": rendered,
                "pressed": pressed,
                "settings_saved": settings_saved,
                "settings_tabs_checked": settings_tabs_checked,
                "password_changed": password_changed,
                "collisions": collisions,
                "faults": faults,
            }
        )
    )
    return 1 if faults or collisions else 0


if __name__ == "__main__":
    raise SystemExit(main())
