#!/usr/bin/env python3
"""Regenerate the public UI images from the running FloorTerminal application.

This maintainer utility starts the real Tk interface in a disposable,
connector-disabled runtime directory and feeds documented immutable snapshots into
the update view. It never reads deployment files, signing material, connector
credentials, or network resources.

Pillow is an optional documentation dependency rather than an application
dependency. Run this script from a graphical desktop session after installing it.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "docs" / "images"
CAPTURE_SIZE = (1600, 960)


def _prepare_runtime():
    runtime = Path(tempfile.mkdtemp(prefix="floorterminal-doc-capture-"))
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config.update(
        sound_enabled=False,
        software_update_check_enabled=False,
        fullscreen_on_linux=False,
        animation_interval_ms=1000,
    )
    (runtime / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    shutil.copyfile(ROOT / "connector.example.json", runtime / "connector.json")
    profile = json.loads(
        (ROOT / "project_profile.example.json").read_text(encoding="utf-8")
    )
    profile["settings_password"] = "docs-" + secrets.token_urlsafe(18)
    (runtime / "project_profile.json").write_text(
        json.dumps(profile, indent=2) + "\n", encoding="utf-8"
    )
    os.environ["FLOORTERMINAL_HOME"] = str(runtime)
    os.environ["FLOORTERMINAL_PROJECT_PROFILE_FILE"] = str(
        runtime / "project_profile.json"
    )
    os.environ["FLOORTERMINAL_DISABLE_UPDATE_NETWORK"] = "1"
    return runtime


class StaticUpdateService:
    """Minimal view-only service used solely for deterministic screenshots."""

    def __init__(self, snapshot):
        self.snapshot = snapshot

    def status(self):
        return self.snapshot

    def start(self):
        return self

    def stop(self):
        return None

    def request_scan(self):
        return None


def _snapshots():
    from floorterminal.update import remote
    from floorterminal.update.service import (
        LEVEL_ATTENTION,
        LEVEL_OK,
        LEVEL_UNKNOWN,
        StagedUpdate,
        UpdateStatus,
    )

    now = time.time()
    current_channel = remote.ChannelResult(
        outcome=remote.OUTCOME_OK,
        checked_at_epoch=now,
        checked_at_utc="2026-08-31T12:00:00Z",
        version="1.0.0",
        released_utc="2026-08-31T00:00:00Z",
        release_title="First public open-source release",
        release_summary="The installed release is the latest published version.",
        minimum_upgradable_version="1.0.0",
        archive_name="floorterminal-v1.0.0-linux-arm64.tar.gz",
        signing_key_id="ba1b79d27fddd67a",
    )
    next_channel = remote.ChannelResult(
        outcome=remote.OUTCOME_OK,
        checked_at_epoch=now,
        checked_at_utc="2026-11-14T09:00:00Z",
        version="1.1.0",
        released_utc="2026-11-14T09:00:00Z",
        release_title="Reliability and accessibility update",
        release_summary=(
            "Clearer first-response guidance with update and recovery refinements."
        ),
        minimum_upgradable_version="1.0.0",
        archive_name="floorterminal-v1.1.0-linux-arm64.tar.gz",
        artifact_sha256="a" * 64,
        signing_key_id="ba1b79d27fddd67a",
        features=(
            "Clearer operator guidance during active incidents",
            "Expanded update diagnostics for administrators",
        ),
        fixes=(
            "More resilient restart and recovery handling",
            "Improved touch-target alignment on compact panels",
        ),
        security=("Stricter offline package validation",),
    )
    staged = StagedUpdate(
        version="1.1.0",
        release_title=next_channel.release_title,
        release_summary=next_channel.release_summary,
        released_utc=next_channel.released_utc,
        artifact_sha256="a" * 64,
        signing_key_id="ba1b79d27fddd67a",
        source_mount="/media/operator/FLOORTERM",
        highlights=next_channel.highlights(),
    )
    history = (
        {
            "at_utc": "2026-08-31T12:05:00Z",
            "action": "confirmed",
            "from_version": "",
            "to_version": "1.0.0",
            "outcome": "ok",
            "source": "supervisor",
        },
        {
            "at_utc": "2026-08-31T12:00:00Z",
            "action": "activated",
            "from_version": "0.9.0",
            "to_version": "1.0.0",
            "outcome": "ok",
            "authorized_by": "Site administrator",
        },
    )
    current = UpdateStatus(
        level=LEVEL_OK,
        headline="Version 1.0.0 is up to date",
        detail="This terminal is running the latest verified published release.",
        installed_version="1.0.0",
        managed=True,
        state="active",
        channel=current_channel,
        latest_version="1.0.0",
        history=history,
    )
    available = UpdateStatus(
        level=LEVEL_ATTENTION,
        headline="Version 1.1.0 is available",
        detail=(
            "A newer signed release is published. Download it on another computer "
            "and prepare the documented update drive."
        ),
        installed_version="1.0.0",
        managed=True,
        state="active",
        channel=next_channel,
        update_available=True,
        latest_version="1.1.0",
        history=history,
    )
    ready = UpdateStatus(
        level=LEVEL_ATTENTION,
        headline="Version 1.1.0 is verified and ready",
        detail=(
            "The package on FLOORTERM passed its signature, manifest, and "
            "executable checksum checks."
        ),
        installed_version="1.0.0",
        managed=True,
        state="active",
        channel=next_channel,
        update_available=True,
        latest_version="1.1.0",
        staged=staged,
        media_mount="/media/operator/FLOORTERM",
        rollback_version="0.9.0",
        history=history,
    )
    blocked = UpdateStatus(
        level=LEVEL_UNKNOWN,
        headline="Update availability could not be checked",
        detail=(
            "The signed release channel is unreachable. Reporting and line "
            "response remain fully available; retry later or use an update drive."
        ),
        installed_version="1.0.0",
        managed=True,
        state="active",
        channel_error="Release channel is unreachable",
        history=history,
    )
    return {
        "current": current,
        "available": available,
        "ready": ready,
        "blocked": blocked,
    }


def _settle(root, cycles=8):
    for _ in range(cycles):
        root.update_idletasks()
        root.update()
        time.sleep(0.025)


def _grab(app, root, image_grab, image_module, widget=None):
    app.toast_until = 0
    app.render()
    _settle(root)
    widget = widget or app.canvas
    x = widget.winfo_rootx()
    y = widget.winfo_rooty()
    width = widget.winfo_width()
    height = widget.winfo_height()
    if widget is app.canvas and (width, height) != CAPTURE_SIZE:
        raise RuntimeError(
            f"native capture must be {CAPTURE_SIZE}, got {width}x{height}; "
            "use a display or Xvfb screen at least 1920x1200"
        )
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    if x < 0 or y < 0 or x + width > screen_width or y + height > screen_height:
        raise RuntimeError(
            "capture window lies outside the display: "
            f"window={x},{y},{width}x{height}; screen={screen_width}x{screen_height}"
        )
    try:
        image = image_grab.grab(bbox=(x, y, x + width, y + height))
    except (OSError, subprocess.CalledProcessError) as exc:
        # Raspberry Pi OS uses Wayland/labwc by default. Pillow can be built with
        # X11 capture support yet still fail against the XWayland compatibility
        # surface. ``grim`` is the native compositor capture utility and accepts
        # an exact region, so it is a safe deterministic fallback.
        grim = shutil.which("grim")
        runtime = Path(f"/run/user/{os.getuid()}") if hasattr(os, "getuid") else None
        if not grim or runtime is None or not runtime.is_dir():
            raise RuntimeError(
                "screen capture failed and no Wayland grim fallback is available"
            ) from exc
        environment = dict(os.environ)
        environment.setdefault("XDG_RUNTIME_DIR", str(runtime))
        environment.setdefault("WAYLAND_DISPLAY", "wayland-0")
        with tempfile.TemporaryDirectory(prefix="floorterminal-grab-") as folder:
            target = Path(folder) / "frame.png"
            result = subprocess.run(
                [grim, "-g", f"{x},{y} {width}x{height}", str(target)],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
            if result.returncode != 0 or not target.is_file():
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"Wayland screen capture failed: {detail}") from exc
            with image_module.open(target) as captured:
                image = captured.copy()
    # Upscaling cannot restore glyph edges or icon detail: capture native pixels.
    image = image.convert("RGB")
    if image.size != (width, height):
        if image.width < width or image.height < height:
            raise RuntimeError("screen capture returned fewer pixels than requested")
        image = image.resize((width, height), image_module.Resampling.LANCZOS)
    extrema = image.getextrema()
    if not extrema or all(low == high for low, high in extrema):
        raise RuntimeError("captured frame is blank")
    return image


def _save(image, output, name):
    path = output / name
    image.save(path, optimize=True)
    return path


def generate(output: Path):
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageGrab
    except ImportError as exc:  # pragma: no cover - maintainer workstation only
        raise SystemExit("Pillow is required: python3 -m pip install Pillow") from exc

    runtime = _prepare_runtime()
    sys.path.insert(0, str(ROOT / "src"))
    import tkinter as tk

    from floorterminal.app import FloorTerminalApp

    output.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    width, height = CAPTURE_SIZE
    if root.winfo_screenwidth() < width or root.winfo_screenheight() < height:
        root.destroy()
        shutil.rmtree(runtime, ignore_errors=True)
        raise RuntimeError(
            "HD capture requires at least 1600x960; use the documented Xvfb command"
        )
    root.geometry(f"{width}x{height}+0+0")
    app = FloorTerminalApp(root, None)
    app.update_service.stop()
    root.geometry(f"{width}x{height}+0+0")
    root.deiconify()
    root.lift()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    _settle(root, 12)

    snapshots = _snapshots()
    frames = {}

    def set_update(name):
        app.update_service = StaticUpdateService(snapshots[name])

    try:
        app.state.update(status="RUNNING", issue_zones=[], failure_selections={})
        app.modal = None
        set_update("current")
        frames["console_current"] = _grab(app, root, ImageGrab, Image)
        _save(frames["console_current"], output, "operator-console.png")

        # Record actual conveyor movement; reduce size only for download weight.
        motion = []
        for _ in range(24):
            motion.append(
                _grab(app, root, ImageGrab, Image).resize(
                    (1200, 720), Image.Resampling.LANCZOS
                )
            )
        motion[0].save(
            output / "conveyor-motion.webp",
            save_all=True,
            append_images=motion[1:],
            duration=200,
            loop=0,
            lossless=True,
            method=6,
        )

        app.select_issue_zone("0")
        frames["failures"] = _grab(app, root, ImageGrab, Image)
        _save(frames["failures"], output, "station-failure-selection.png")
        app.modal = None
        app.state.update(issue_zones=[], failure_selections={})

        # Real rendered screens with illustrative local state and no connector.
        from copy import deepcopy

        running_state = deepcopy(app.state)
        for status, filename in (
            ("DOWN", "line-interrupted.png"),
            ("REPAIRING", "response-in-progress.png"),
        ):
            app.state.update(
                status=status,
                issue_zones=["Station 1", "Station 3"],
                failure_selections={"Station 1": ["Mechanical"]},
                started_at=time.time() - 420,
                repair_at=time.time() - 120 if status == "REPAIRING" else None,
                engineer_names=["Example Responder"] if status == "REPAIRING" else [],
                response_record_id="DEMO-001",
            )
            frames[filename] = _grab(app, root, ImageGrab, Image)
            _save(frames[filename], output, filename)
        app.state = running_state

        set_update("available")
        frames["console_available"] = _grab(app, root, ImageGrab, Image)
        _save(frames["console_available"], output, "update-console-amber.png")

        cases = (
            ("current", "status", "update-panel-current.png"),
            ("ready", "status", "update-panel-ready.png"),
            ("ready", "changes", "update-panel-changes.png"),
            ("ready", "version", "update-panel-version.png"),
            ("ready", "activity", "update-panel-activity.png"),
            ("blocked", "status", "update-panel-blocked.png"),
        )
        for status_name, page, filename in cases:
            set_update(status_name)
            app.modal = {"kind": "update", "page": page}
            frames[filename] = _grab(app, root, ImageGrab, Image)
            _save(frames[filename], output, filename)

        set_update("ready")
        app.modal = {"kind": "update", "page": "changes"}
        app.request_update_authorization("install")
        frames["authorization"] = _grab(app, root, ImageGrab, Image)
        _save(frames["authorization"], output, "update-panel-authorization.png")

        # Three real header crops are stacked into a compact status reference.
        strips = []
        for label, name, source in (
            ("CURRENT", "current", frames["console_current"]),
            ("UPDATE AVAILABLE", "available", frames["console_available"]),
            ("CHECK UNAVAILABLE", "blocked", None),
        ):
            if source is None:
                app.modal = None
                set_update(name)
                source = _grab(app, root, ImageGrab, Image)
            crop = source.crop((1250, 0, 1360, 128))
            canvas = Image.new("RGB", (660, 168), "white")
            canvas.paste(crop, (20, 20))
            draw = ImageDraw.Draw(canvas)
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", 24)
            except OSError:
                font = ImageFont.load_default(size=24)
            draw.text((180, 84), label, fill="#14213D", font=font, anchor="lm")
            strips.append(canvas)
        indicator = Image.new("RGB", (660, 504), "#F3F5F9")
        for index, strip in enumerate(strips):
            indicator.paste(strip, (0, index * 168))
        _save(indicator, output, "update-indicator-states.png")

        walkthrough = [
            frames["update-panel-current.png"],
            frames["update-panel-ready.png"],
            frames["update-panel-changes.png"],
            frames["authorization"],
        ]
        gif_frames = [
            frame.resize((1200, 720), Image.Resampling.LANCZOS) for frame in walkthrough
        ]
        gif_frames[0].save(
            output / "update-walkthrough.gif",
            save_all=True,
            append_images=gif_frames[1:],
            duration=(1600, 1800, 2000, 2000),
            loop=0,
            optimize=True,
        )

        app.modal = {"kind": "about"}
        _save(_grab(app, root, ImageGrab, Image), output, "software-information.png")

        app.modal = None
        from floorterminal.ui.settings import SettingsWindow

        settings = SettingsWindow(app, {"teams": [], "conversations": []})
        settings.win.overrideredirect(True)
        for index, name in (
            (0, "settings-line.png"),
            (1, "settings-connector.png"),
            (2, "settings-stations.png"),
            (4, "settings-access.png"),
        ):
            settings.tabs.select(settings.tabs.tabs()[index])
            _settle(root)
            _save(_grab(app, root, ImageGrab, Image, settings.win), output, name)
        settings.win.destroy()

        app.request_password_change(lambda _changed: None)
        _save(_grab(app, root, ImageGrab, Image), output, "settings-password.png")
        app.modal = None

        workflow_frames = [
            frames["console_current"],
            frames["failures"],
            frames["line-interrupted.png"],
            frames["response-in-progress.png"],
            frames["console_current"],
        ]
        workflow_frames[0].save(
            output / "operator-walkthrough.webp",
            save_all=True,
            append_images=workflow_frames[1:],
            duration=[2200, 3000, 2500, 3000, 1800],
            loop=0,
            lossless=True,
            method=6,
        )
    finally:
        app.update_service.stop()
        app.sound.close()
        root.destroy()
        shutil.rmtree(runtime, ignore_errors=True)

    expected = {
        "operator-console.png",
        "software-information.png",
        "station-failure-selection.png",
        "line-interrupted.png",
        "response-in-progress.png",
        "settings-line.png",
        "settings-connector.png",
        "settings-stations.png",
        "settings-access.png",
        "settings-password.png",
        "operator-walkthrough.webp",
        "conveyor-motion.webp",
        "update-console-amber.png",
        "update-indicator-states.png",
        "update-panel-activity.png",
        "update-panel-authorization.png",
        "update-panel-blocked.png",
        "update-panel-changes.png",
        "update-panel-current.png",
        "update-panel-ready.png",
        "update-panel-version.png",
        "update-walkthrough.gif",
    }
    missing = sorted(name for name in expected if not (output / name).is_file())
    if missing:
        raise RuntimeError("documentation capture is incomplete: " + ", ".join(missing))
    print(f"Captured {len(expected)} documentation assets in {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.output.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
