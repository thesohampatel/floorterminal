"""Small nine-slice field surfaces shared by all Settings inputs."""

import tkinter as tk

from .raster import _png, rounded_rectangle_png


def chevron_png(size):
    """Original antialiased chevron; no font glyph or downloaded icon required."""
    size = max(16, min(64, round(size)))
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            px, py = x / size, y / size
            # Distance from the two strokes forming a downward V.
            target = 0.64 - abs(px - 0.5)
            coverage = (
                max(0, min(1, (0.045 - abs(py - target)) * size))
                if 0.24 <= px <= 0.76
                else 0
            )
            # Tk's X11 partial-alpha path reads the drawable back via XGetImage.
            # On Pi/XWayland this can stall the display server. Preblend edge
            # coverage and use a binary mask, just like the shared rasterizer.
            if coverage <= 0.04:
                row.extend((0, 0, 0, 0))
            else:
                row.extend(
                    round(c * coverage + b * (1 - coverage))
                    for c, b in zip((70, 108, 180), (242, 246, 252))
                )
                row.append(255)
        rows.append(bytes(row))
    return _png(size, size, rows)


def configure_fields(style, owner, scale):
    """One set per Tcl interpreter; never accumulate elements across resizes."""
    root = owner._root()
    images = getattr(root, "_field_images", None)
    if images is None:
        images = root._field_images = {
            key: tk.PhotoImage(master=root)
            for key in ("normal", "focus", "disabled", "arrow")
        }
        style.element_create(
            "FloorField.field",
            "image",
            str(images["normal"]),
            ("disabled", str(images["disabled"])),
            ("focus", str(images["focus"])),
            border=10,
            sticky="nsew",
        )
        style.element_create(
            "FloorField.downarrow", "image", str(images["arrow"]), sticky=""
        )
    for key, fill, edge in (
        ("normal", (242, 246, 252), (185, 202, 224)),
        ("focus", (248, 251, 255), (36, 107, 253)),
        ("disabled", (241, 244, 248), (214, 223, 235)),
    ):
        images[key].configure(
            data=rounded_rectangle_png(30, 30, 9, fill, edge, 1, (255, 255, 255)),
            format="png",
        )
    images["arrow"].configure(data=chevron_png(24 * scale), format="png")
    style.layout(
        "Settings.TCombobox",
        [
            (
                "FloorField.field",
                {
                    "sticky": "nswe",
                    "children": [
                        ("FloorField.downarrow", {"side": "right", "sticky": "ns"}),
                        (
                            "Combobox.padding",
                            {
                                "expand": 1,
                                "sticky": "nswe",
                                "children": [("Combobox.textarea", {"sticky": "nswe"})],
                            },
                        ),
                    ],
                },
            )
        ],
    )
    style.layout(
        "Settings.TEntry",
        [
            (
                "FloorField.field",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Entry.padding",
                            {
                                "sticky": "nswe",
                                "children": [("Entry.textarea", {"sticky": "nswe"})],
                            },
                        ),
                    ],
                },
            )
        ],
    )
    style.configure(
        "Settings.TEntry",
        padding=(round(12 * scale), round(7 * scale)),
        foreground="#14213D",
        fieldbackground="#F2F6FC",
        insertcolor="#14213D",
    )
