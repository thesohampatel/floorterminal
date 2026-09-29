"""Resolution-independent Tk canvas and screen-fit geometry."""

from __future__ import annotations

import tkinter as tk
from contextlib import contextmanager

from .raster import MAX_RASTER_PIXELS, RasterCache, rounded_rectangle_png

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
    """Render a logical design grid into a centered, uniformly scaled viewport.

    Tk draws X11 and Windows canvas shapes without anti-aliasing, which leaves
    visible stair steps on rounded corners and circles. With ``antialias`` on,
    rounded rectangles and circles are drawn as cached pre-rendered images whose
    edge pixels carry real coverage, blended against ``aa_backdrop`` — the
    surface the shape sits on, which the view sets while drawing on a coloured
    control. Other filled shapes get a one-pixel edge in the halfway colour.
    """

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
        self.aa_backdrop = None
        self._rgb_cache = {}
        self._mix_cache = {}
        super().__init__(master, **kwargs)
        # Aqua already anti-aliases the canvas, and there an image would be
        # drawn at 1x on a Retina display, so pre-rendering is X11/Windows only.
        try:
            windowing = str(self.tk.call("tk", "windowingsystem"))
        except tk.TclError:
            windowing = ""
        self.antialias = windowing in {"x11", "win32"}
        self.raster = RasterCache(
            lambda data: tk.PhotoImage(master=self, data=data, format="png")
        )

    @contextmanager
    def surface(self, color):
        """Blend anti-aliased edges drawn inside the block against ``color``."""
        previous = self.aa_backdrop
        if color:
            self.aa_backdrop = color
        try:
            yield
        finally:
            self.aa_backdrop = previous

    def _rgb(self, color):
        if not color:
            return None
        cached = self._rgb_cache.get(color)
        if cached is None:
            try:
                red, green, blue = self.winfo_rgb(color)
            except tk.TclError:
                return None
            cached = self._rgb_cache[color] = (red // 257, green // 257, blue // 257)
        return cached

    def edge_color(self, color, backdrop=None, amount=0.5):
        """Blend ``color`` toward the backdrop; ``None`` when either is unknown."""
        backdrop = backdrop or self.aa_backdrop
        if not color or not backdrop:
            return None
        key = (color, backdrop, amount)
        if key not in self._mix_cache:
            first, second = self._rgb(color), self._rgb(backdrop)
            if first is None or second is None:
                self._mix_cache[key] = None
            else:
                red, green, blue = (
                    round(a * (1 - amount) + b * amount) for a, b in zip(first, second)
                )
                self._mix_cache[key] = f"#{red:02X}{green:02X}{blue:02X}"
        return self._mix_cache[key]

    def create_rounded(
        self, x1, y1, x2, y2, radius, fill="", outline="", width=1, tags=()
    ):
        """Draw an anti-aliased rounded rectangle; ``None`` asks for a fallback.

        Like a Tk polygon outline, the ring is centred on the logical edge. The
        shape is snapped to whole device pixels so straight edges stay crisp.
        """
        if not self.antialias:
            return None
        fill_rgb, outline_rgb = self._rgb(fill), self._rgb(outline)
        if (fill and fill_rgb is None) or (outline and outline_rgb is None):
            return None
        if fill_rgb is None and outline_rgb is None:
            return None
        backdrop = self._rgb(self.aa_backdrop or self.cget("background"))
        if backdrop is None:
            return None
        scale = self.scale_factor
        line = max(1, round(float(width) * scale)) if outline_rgb else 0
        grow = line / 2.0
        left = round(x1 * scale + self.offset_x - grow)
        top = round(y1 * scale + self.offset_y - grow)
        right = round(x2 * scale + self.offset_x + grow)
        bottom = round(y2 * scale + self.offset_y + grow)
        pixel_width, pixel_height = right - left, bottom - top
        if (
            pixel_width < 1
            or pixel_height < 1
            or pixel_width * pixel_height > MAX_RASTER_PIXELS
        ):
            return None
        pixel_radius = round((float(radius) * scale + grow) * 4) / 4
        key = (
            pixel_width,
            pixel_height,
            pixel_radius,
            fill_rgb,
            outline_rgb,
            line,
            backdrop,
        )
        try:
            image = self.raster.get(
                key,
                lambda: rounded_rectangle_png(
                    pixel_width,
                    pixel_height,
                    pixel_radius,
                    fill_rgb,
                    outline_rgb,
                    line,
                    backdrop,
                ),
            )
        except tk.TclError:
            # An image format problem must never stop the console from drawing.
            self.antialias = False
            return None
        if image is None:
            return None
        tags = tuple(tags) if isinstance(tags, (list, tuple)) else (tags,)
        tags += ("ft-shape", "ft-filled" if fill_rgb else "ft-ring")
        return super().create_image(left, top, image=image, anchor="nw", tags=tags)

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
        flat = self._coordinates(coords)
        if self.antialias and len(flat) == 4:
            x1, y1, x2, y2 = (
                list(coords[0]) if len(coords) == 1 else list(coords)
            )
            if abs(abs(x2 - x1) - abs(y2 - y1)) < 0.01:
                # A circle is a rounded square with a radius of half its side.
                item = self.create_rounded(
                    min(x1, x2),
                    min(y1, y2),
                    max(x1, x2),
                    max(y1, y2),
                    abs(x2 - x1) / 2,
                    fill=options.get("fill", ""),
                    outline=options.get("outline", "black"),
                    width=options.get("width", 1),
                    tags=options.get("tags", ()),
                )
                if item is not None:
                    return item
        return super().create_oval(*flat, **self._style(options))

    def create_polygon(self, *coords, **options):
        return self._edge_smoothed(
            super().create_polygon, self._coordinates(coords), self._style(options)
        )

    def _edge_smoothed(self, create, coords, options):
        """Give an unoutlined filled shape a halfway-colour edge pixel."""
        if self.antialias and self.aa_backdrop and options.get("fill") and not options.get(
            "outline"
        ):
            edge = self.edge_color(options["fill"])
            if edge:
                options["outline"] = edge
                options["width"] = 1
        return create(*coords, **options)

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
