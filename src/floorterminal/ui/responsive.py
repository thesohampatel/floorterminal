"""Resolution-independent Tk canvas and screen-fit geometry."""

from __future__ import annotations

import tkinter as tk

DESIGN_WIDTH = 800.0
DESIGN_HEIGHT = 480.0


def fitted_window_geometry(
    screen_width, screen_height, width_ratio=1.0, height_ratio=1.0
):
    """Return a positive, centered window rectangle guaranteed to fit the screen."""
    screen_width = max(1, int(screen_width))
    screen_height = max(1, int(screen_height))
    width_ratio = min(1.0, max(0.1, float(width_ratio)))
    height_ratio = min(1.0, max(0.1, float(height_ratio)))
    width = max(1, min(screen_width, round(screen_width * width_ratio)))
    height = max(1, min(screen_height, round(screen_height * height_ratio)))
    return width, height, (screen_width - width) // 2, (screen_height - height) // 2


def design_scale(
    width, height, logical_width=DESIGN_WIDTH, logical_height=DESIGN_HEIGHT
):
    """Calculate uniform scale for an arbitrary viewport without cropping."""
    return min(
        max(1.0, float(width)) / float(logical_width),
        max(1.0, float(height)) / float(logical_height),
    )


class ResponsiveCanvas(tk.Canvas):
    """Render a logical design grid into a centered, uniformly scaled viewport."""

    def __init__(
        self,
        master,
        logical_width=DESIGN_WIDTH,
        logical_height=DESIGN_HEIGHT,
        **kwargs,
    ):
        self.logical_width = float(logical_width)
        self.logical_height = float(logical_height)
        self.scale_factor = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        super().__init__(master, **kwargs)

    def set_viewport(self, width, height):
        width = max(1.0, float(width))
        height = max(1.0, float(height))
        self.scale_factor = design_scale(
            width, height, self.logical_width, self.logical_height
        )
        self.offset_x = (width - self.logical_width * self.scale_factor) / 2
        self.offset_y = (height - self.logical_height * self.scale_factor) / 2

    def to_logical(self, x, y):
        return (
            (x - self.offset_x) / self.scale_factor,
            (y - self.offset_y) / self.scale_factor,
        )

    def _coordinates(self, values):
        flat = (
            list(values[0])
            if len(values) == 1 and isinstance(values[0], (list, tuple))
            else list(values)
        )
        result = []
        for index, value in enumerate(flat):
            result.append(
                (float(value) * self.scale_factor)
                + (self.offset_x if index % 2 == 0 else self.offset_y)
            )
        return result

    def _style(self, options):
        options = dict(options)
        if "width" in options and isinstance(options["width"], (int, float)):
            options["width"] = max(1, float(options["width"]) * self.scale_factor)
        if "arrowshape" in options:
            options["arrowshape"] = tuple(
                float(value) * self.scale_factor for value in options["arrowshape"]
            )
        return options

    def create_rectangle(self, *coords, **options):
        return super().create_rectangle(
            *self._coordinates(coords), **self._style(options)
        )

    def create_oval(self, *coords, **options):
        return super().create_oval(*self._coordinates(coords), **self._style(options))

    def create_polygon(self, *coords, **options):
        return super().create_polygon(
            *self._coordinates(coords), **self._style(options)
        )

    def create_line(self, *coords, **options):
        return super().create_line(*self._coordinates(coords), **self._style(options))

    def create_arc(self, *coords, **options):
        """Scale arc geometry and stroke width like every other canvas primitive."""
        return super().create_arc(*self._coordinates(coords), **self._style(options))

    def create_image(self, x, y, **options):
        """Place a pre-sized image at scaled logical coordinates."""
        px, py = self._coordinates((x, y))
        return super().create_image(px, py, **options)

    def create_text(self, x, y, **options):
        options = dict(options)
        font = options.get("font")
        if (
            isinstance(font, (tuple, list))
            and len(font) >= 2
            and isinstance(font[1], (int, float))
        ):
            scaled = list(font)
            scaled[1] = max(1, round(float(font[1]) * self.scale_factor))
            options["font"] = tuple(scaled)
        if isinstance(options.get("width"), (int, float)):
            options["width"] = float(options["width"]) * self.scale_factor
        px, py = self._coordinates((x, y))
        return super().create_text(px, py, **options)
