"""Native-pixel screenshots for offline GUI checks on X11 and Wayland.

Pillow and grim are optional test/documentation tools, never runtime dependencies.
Only the requested widget is captured; a failed capture never falls back to the
entire desktop, which might contain unrelated private information.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def capture_widget(widget, image_grab=None, image_module=None):
    if image_grab is None or image_module is None:
        from PIL import Image, ImageGrab

        image_grab, image_module = ImageGrab, Image
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    width, height = widget.winfo_width(), widget.winfo_height()
    if (
        width < 1
        or height < 1
        or x < 0
        or y < 0
        or x + width > widget.winfo_screenwidth()
        or y + height > widget.winfo_screenheight()
    ):
        raise RuntimeError("Capture widget lies outside the display")
    try:
        image = image_grab.grab(bbox=(x, y, x + width, y + height))
    except (OSError, subprocess.CalledProcessError) as exc:
        grim = shutil.which("grim")
        environment = dict(os.environ)
        if hasattr(os, "getuid"):
            environment.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        runtime = environment.get("XDG_RUNTIME_DIR")
        if not grim or not runtime or not Path(runtime).is_dir():
            raise RuntimeError(
                "Screen capture failed; Wayland capture unavailable"
            ) from exc
        environment.setdefault("WAYLAND_DISPLAY", "wayland-0")
        with tempfile.TemporaryDirectory(prefix="floorterminal-grab-") as folder:
            target = Path(folder) / "frame.png"
            try:
                result = subprocess.run(
                    [grim, "-g", f"{x},{y} {width}x{height}", str(target)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                    env=environment,
                )
            except subprocess.TimeoutExpired as timeout:
                raise RuntimeError("Wayland screen capture timed out") from timeout
            if result.returncode or not target.is_file():
                raise RuntimeError("Wayland screen capture failed") from exc
            with image_module.open(target) as captured:
                image = captured.copy()
    image = image.convert("RGB")
    if image.size != (width, height):
        if image.width < width or image.height < height:
            raise RuntimeError("Screen capture returned fewer pixels than requested")
        image = image.resize((width, height), image_module.Resampling.LANCZOS)
    extrema = image.getextrema()
    if not extrema or all(low == high for low, high in extrema):
        raise RuntimeError("Captured frame is blank")
    return image
