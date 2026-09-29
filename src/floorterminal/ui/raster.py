"""Anti-aliased rounded shapes for Tk canvases that draw without smoothing.

Tk's X11 and Windows canvases rasterize polygons and ovals without
anti-aliasing, which leaves stair steps on every rounded corner and circle. This
module pre-renders those shapes once per size and colour as small photo images
whose edge pixels carry the correct partial coverage.

Every pixel is either fully transparent or fully opaque. Partially covered edge
pixels are blended against the surface the shape sits on, so Tk keeps its fast
masked-image drawing path instead of per-frame alpha compositing, which matters
on a Raspberry Pi redrawing at kiosk frame rates. Only standard-library code is
used: images are encoded as PNG with :mod:`zlib`.
"""

from __future__ import annotations

import struct
import zlib
from collections import OrderedDict

#: Edge pixels with less coverage than this are left transparent.
MIN_COVERAGE = 0.04
#: Shapes larger than this (device pixels) are drawn natively; a full-screen
#: image would cost more memory than its smoother corners are worth.
MAX_RASTER_PIXELS = 2_600_000


def _clamp(value):
    return max(0.0, min(1.0, value))


def _mix(color, backdrop, amount):
    """Mix ``color`` over ``backdrop`` with opacity ``amount``."""
    return tuple(
        round(c * amount + b * (1.0 - amount)) for c, b in zip(color, backdrop)
    )


def _png(width, height, rows):
    """Encode RGBA rows (bytes, one per scanline) as a PNG file."""

    def chunk(kind, payload):
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 1))
        + chunk(b"IEND", b"")
    )


def rounded_rectangle_png(width, height, radius, fill, outline, line_width, backdrop):
    """Render one rounded rectangle; colours are ``(r, g, b)`` tuples or ``None``.

    ``fill=None`` leaves the interior transparent (an outline-only ring). The
    shape is symmetric, so one quadrant of each corner row is computed and
    mirrored; straight edges are pixel-aligned and need no coverage at all.
    """
    width, height = max(1, int(width)), max(1, int(height))
    radius = max(0.0, min(float(radius), width / 2.0, height / 2.0))
    line_width = max(0, round(line_width)) if outline else 0
    if not line_width:
        outline = None
    if fill is None and outline is None:
        return None
    inner_radius = max(0.0, radius - line_width)
    transparent = b"\x00\x00\x00\x00"

    def pixel(coverage_outer, coverage_inner):
        """Colour for one pixel from its outer-shape and interior coverage."""
        ring = max(0.0, coverage_outer - coverage_inner)
        if fill is None:
            if ring < MIN_COVERAGE:
                return transparent
            return bytes((*_mix(outline, backdrop, ring), 255))
        if coverage_outer < MIN_COVERAGE:
            return transparent
        if outline is None:
            return bytes((*_mix(fill, backdrop, coverage_outer), 255))
        # Interior over the ring over the backdrop.
        base = _mix(outline, backdrop, coverage_outer)
        interior = coverage_inner / coverage_outer if coverage_outer else 0.0
        return bytes((*_mix(fill, base, interior), 255))

    ring_px = bytes((*outline, 255)) if outline else None
    fill_px = bytes((*fill, 255)) if fill else transparent
    corner = int(radius + 0.999)

    def straight_row(y_from_edge):
        """A row outside the corner bands, or the middle of a corner band."""
        if outline is not None and y_from_edge < line_width:
            return ring_px
        return fill_px

    rows_top = []
    for row in range(min(corner, (height + 1) // 2)):
        cy = radius - (row + 0.5)
        left = []
        for column in range(min(corner, (width + 1) // 2)):
            cx = radius - (column + 0.5)
            if cx > 0 and cy > 0:
                distance = (cx * cx + cy * cy) ** 0.5
                outer = _clamp(radius - distance + 0.5)
                inner = (
                    _clamp(inner_radius - distance + 0.5)
                    if outline is not None
                    else outer
                )
                # Pixels whose centre lies inside the band of the straight
                # border also belong to the ring.
                if outline is not None and (row < line_width or column < line_width):
                    inner = 0.0
            else:
                outer = 1.0
                inner = (
                    0.0
                    if outline is not None and (row < line_width or column < line_width)
                    else 1.0
                )
            left.append(pixel(outer, inner))
        middle_count = width - 2 * len(left)
        right = list(reversed(left))
        if middle_count < 0:
            # Odd width: the centre column belongs to both halves once.
            right = right[-middle_count:]
        middle = straight_row(row) * max(0, middle_count)
        rows_top.append(b"".join(left) + middle + b"".join(right))
    band = len(rows_top)
    middle_rows = []
    if height - 2 * band > 0:
        edge_width = line_width if outline is not None else 0
        edge = ring_px * edge_width if edge_width else b""
        row_bytes = edge + fill_px * max(0, width - 2 * edge_width) + edge
        middle_rows = [row_bytes] * (height - 2 * band)
    rows = rows_top + middle_rows + list(reversed(rows_top))
    if height % 2 and band * 2 > height:
        rows = rows_top + list(reversed(rows_top[:-1]))
    return _png(width, height, rows[:height])


class RasterCache:
    """Bounded cache of rendered shapes, keyed by exact pixels and colours."""

    def __init__(self, factory, limit=600):
        self.factory = factory
        self.limit = limit
        self.images = OrderedDict()

    def get(self, key, render):
        image = self.images.get(key)
        if image is not None:
            self.images.move_to_end(key)
            return image
        data = render()
        if data is None:
            return None
        image = self.factory(data)
        self.images[key] = image
        while len(self.images) > self.limit:
            self.images.popitem(last=False)
        return image

    def clear(self):
        self.images.clear()
